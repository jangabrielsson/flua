import * as vscode from "vscode";
import { fluaExecutable, runInTerminal } from "./flua";

/** The configured viewer port (default 8090, the flua --ui default). */
function viewerPort(): number {
  return vscode.workspace.getConfiguration("flua").get<number>("viewerPort", 8090);
}

/** The QA document to act on: the URI argument, else the active editor. */
function targetDoc(uri?: vscode.Uri): vscode.Uri | undefined {
  if (uri) {
    return uri;
  }
  const doc = vscode.window.activeTextEditor?.document;
  return doc && doc.languageId === "lua" ? doc.uri : undefined;
}

/** Run the QA in the shared flua terminal: `flua --ui PORT <file>`, plus
 * --watch for the watch variant. The port is explicit — --ui takes an
 * optional PORT argument and would otherwise swallow the file path. */
export function runQa(uri?: vscode.Uri, watch = false): void {
  const target = targetDoc(uri);
  if (!target) {
    void vscode.window.showWarningMessage("flua: no Lua QA to run — open one first");
    return;
  }
  const args = ["--ui", String(viewerPort())];
  if (watch) {
    args.push("--watch");
  }
  args.push(target.fsPath);
  runInTerminal(fluaExecutable(), args);
}

/** Is a flua UI server answering on this port? (the viewer's channel). */
async function isServing(port: number): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 800);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/flua/devices`, {
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** Start-or-reuse `flua --ui` on the configured port (no script: the
 * server session hosts the viewer, timeline and docs until stopped), then
 * wait for it to answer. */
async function ensureServing(): Promise<number | undefined> {
  const port = viewerPort();
  if (await isServing(port)) {
    return port;
  }
  runInTerminal(fluaExecutable(), ["--ui", String(port)]);
  for (let attempt = 0; attempt < 40; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (await isServing(port)) {
      return port;
    }
  }
  return undefined;
}

const PAGE_TITLES = new Map<string, string>([
  ["flua.viewer", "flua viewer"],
  ["flua.timeline", "flua timeline"],
  ["flua.docs", "flua docs"],
]);

const PAGE_PATHS = new Map<string, string>([
  ["flua.viewer", "/"],
  ["flua.timeline", "/timeline"],
  ["flua.docs", "/docs/"],
]);

const openPanels = new Map<string, vscode.WebviewPanel>();

/** Open a served flua page (viewer/timeline/docs) in a VS Code webview,
 * starting the server session on demand. The webview loads the page
 * through VS Code's port mapping (asExternalUri); when that is not
 * available the system browser opens instead. */
export async function openFluaPage(kind: "viewer" | "timeline" | "docs"): Promise<void> {
  const viewType = `flua.${kind}`;
  const existing = openPanels.get(viewType);
  if (existing) {
    existing.reveal();
    return;
  }
  const port = await ensureServing();
  if (port === undefined) {
    void vscode.window.showWarningMessage(
      "flua: the UI server did not answer — check the flua terminal"
    );
    return;
  }
  const url = vscode.Uri.parse(`http://127.0.0.1:${port}${PAGE_PATHS.get(viewType) ?? "/"}`);
  try {
    const mapped = await vscode.env.asExternalUri(url);
    const panel = vscode.window.createWebviewPanel(
      viewType,
      PAGE_TITLES.get(viewType) ?? "flua",
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    openPanels.set(viewType, panel);
    panel.onDidDispose(() => openPanels.delete(viewType));
    panel.webview.html = `<!doctype html><html><body style="margin:0;padding:0;overflow:hidden">
<iframe src="${mapped.toString()}" style="border:0;width:100vw;height:100vh"></iframe>
</body></html>`;
  } catch {
    void vscode.env.openExternal(url);
  }
}

// -- the running QA (lenses poke it through the sim API) ----------------------

interface RunningDevice {
  id: number;
  name: string;
}

/** The QA's --%%name (the first header token), if declared. */
async function qaName(document: vscode.TextDocument): Promise<string | undefined> {
  for (let i = 0; i < Math.min(document.lineCount, 60); i++) {
    const match = document.lineAt(i).text.match(/^--%%name:\s*(\S+)/);
    if (match) {
      return match[1];
    }
  }
  return undefined;
}

/** The running device with this name (the latest one when several). */
async function runningDevice(name: string): Promise<RunningDevice | undefined> {
  try {
    const res = await fetch(`http://127.0.0.1:${viewerPort()}/flua/devices`);
    if (!res.ok) {
      return undefined;
    }
    const devices = (await res.json()) as Array<{ id: number; name?: string }>;
    const matches = devices.filter((d) => d.name === name);
    return matches.length
      ? { id: matches[matches.length - 1].id, name }
      : undefined;
  } catch {
    return undefined;
  }
}

/** The running device for this document; offers to start the QA when the
 * server has no device of that name. */
async function ensureQaRunning(
  document: vscode.TextDocument
): Promise<RunningDevice | undefined> {
  const name = await qaName(document);
  if (!name) {
    void vscode.window.showWarningMessage(
      "flua: the QA has no --%%name — add one so it can be found when running"
    );
    return undefined;
  }
  const existing = await runningDevice(name);
  if (existing) {
    return existing;
  }
  const action = await vscode.window.showInformationMessage(
    `flua: "${name}" is not running — start it?`,
    "Run QA"
  );
  if (action !== "Run QA") {
    return undefined;
  }
  runQa(document.uri);
  for (let attempt = 0; attempt < 40; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const device = await runningDevice(name);
    if (device) {
      return device;
    }
  }
  return undefined;
}

/** "true/false" -> boolean, numbers -> number, everything else a string. */
function parseArg(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "true") {
    return true;
  }
  if (trimmed === "false") {
    return false;
  }
  if (trimmed !== "" && !isNaN(Number(trimmed))) {
    return Number(trimmed);
  }
  return trimmed;
}

/** Prompt for a method's arguments (comma-separated, Lua-literal-ish). */
async function promptArgs(params: string[]): Promise<unknown[] | undefined> {
  if (!params.length) {
    return [];
  }
  const input = await vscode.window.showInputBox({
    prompt: `arguments for ${params.join(", ")} — comma-separated (numbers, true/false, or strings)`,
    placeHolder: params.join(", "),
  });
  if (input === undefined) {
    return undefined;
  }
  return input.split(",").map(parseArg);
}

/** Call an action method on the running QA: POST /devices/{id}/action/{name}. */
export async function callAction(
  uri: vscode.Uri,
  action: string,
  params: string[]
): Promise<void> {
  const document = await vscode.workspace.openTextDocument(uri);
  const device = await ensureQaRunning(document);
  if (!device) {
    return;
  }
  const args = await promptArgs(params);
  if (args === undefined) {
    return; // cancelled
  }
  try {
    const res = await fetch(
      `http://127.0.0.1:${viewerPort()}/devices/${device.id}/action/${encodeURIComponent(action)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args }),
      }
    );
    void vscode.window.showInformationMessage(
      `flua: ${action}(${args.map(String).join(", ")}) on ${device.name} → HTTP ${res.status}`
    );
  } catch (error) {
    void vscode.window.showWarningMessage(`flua: call failed: ${String(error)}`);
  }
}

interface UiElement {
  kind: string; // button | switch | slider | select | multi
  name: string;
}

const UI_EVENT_TYPES = new Map<string, string>([
  ["button", "onReleased"],
  ["switch", "onReleased"],
  ["slider", "onChanged"],
  ["select", "onToggled"],
  ["multi", "onToggled"],
]);

/** The UI elements declared on a --%%u: line (one or more; both quote
 * styles — the directive syntax takes Lua literals). */
function elementsOnLine(line: string): UiElement[] {
  const elements: UiElement[] = [];
  for (const match of line.matchAll(/\{(button|switch|slider|select|multi)=['"]([^'"]+)['"]/g)) {
    elements.push({ kind: match[1], name: match[2] });
  }
  return elements;
}

/** Inject a UI event for one element: the same GET the viewer uses. */
export async function injectUiEvent(
  uri: vscode.Uri,
  element?: UiElement,
  line?: number
): Promise<void> {
  const document = await vscode.workspace.openTextDocument(uri);
  let target = element;
  if (!target) {
    const index = typeof line === "number" ? line : 0;
    const candidates = elementsOnLine(document.lineAt(index).text);
    if (candidates.length > 1) {
      const picked = await vscode.window.showQuickPick(
        candidates.map((e) => `${e.kind} '${e.name}'`),
        { placeHolder: "which element?" }
      );
      target = picked
        ? candidates.find((e) => `${e.kind} '${e.name}'` === picked)
        : undefined;
    } else {
      target = candidates[0];
    }
  }
  if (!target) {
    void vscode.window.showWarningMessage("flua: no UI element on that line");
    return;
  }
  const device = await ensureQaRunning(document);
  if (!device) {
    return;
  }
  const eventType = UI_EVENT_TYPES.get(target.kind) ?? "onReleased";
  const needsValue = ["switch", "slider", "select", "multi"].includes(target.kind);
  let value: string | undefined;
  if (target.kind === "switch") {
    value = await vscode.window.showInputBox({
      prompt: `value for ${target.name} (onReleased)`,
      value: "true",
    });
  } else if (target.kind === "slider") {
    value = await vscode.window.showInputBox({
      prompt: `value for slider ${target.name} (onChanged)`,
    });
  } else if (target.kind === "select") {
    value = await vscode.window.showInputBox({
      prompt: `option value for ${target.name} (onToggled)`,
    });
  } else if (target.kind === "multi") {
    value = await vscode.window.showInputBox({
      prompt: `option values for ${target.name}, comma-separated (onToggled)`,
    });
  }
  if (needsValue && value === undefined) {
    return; // cancelled
  }
  const query = new URLSearchParams({
    deviceID: String(device.id),
    elementName: target.name,
    eventType,
  });
  if (value !== undefined && value !== "") {
    query.set("value", value);
  }
  try {
    const res = await fetch(
      `http://127.0.0.1:${viewerPort()}/plugins/callUIEvent?${query.toString()}`
    );
    void vscode.window.showInformationMessage(
      `flua: ${eventType} on ${target.name} (${device.name}) → HTTP ${res.status}`
    );
  } catch (error) {
    void vscode.window.showWarningMessage(`flua: UI event failed: ${String(error)}`);
  }
}

// -- CodeLens ----------------------------------------------------------------

/** ▶ lenses: Run QA on onInit/selfTest; Call <action> on every other
 * QuickApp method; one lens per --%%u: line that injects the declared
 * element's UI event into the running QA. */
class FluaCodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChange.event;

  refresh(): void {
    this._onDidChange.fire();
  }

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (!vscode.workspace.getConfiguration("flua").get<boolean>("codeLens", true)) {
      return [];
    }
    const interact = vscode.workspace
      .getConfiguration("flua")
      .get<boolean>("codeLensInteract", true);
    const lenses: vscode.CodeLens[] = [];
    for (let i = 0; i < document.lineCount; i++) {
      const line = document.lineAt(i).text;
      const range = new vscode.Range(i, 0, i, line.length);
      const method = line.match(/^\s*function\s+QuickApp:(\w+)\s*\(([^)]*)\)/);
      if (method) {
        const name = method[1];
        const params = method[2]
          .split(",")
          .map((p) => p.trim().split(/\s/)[0])
          .filter((p) => p && p !== "self");
        if (name === "onInit" || name === "selfTest") {
          lenses.push(
            new vscode.CodeLens(range, {
              title: name === "selfTest" ? "▶ Run selfTest" : "▶ Run QA",
              command: "flua.run",
              arguments: [document.uri],
            })
          );
        } else if (interact) {
          lenses.push(
            new vscode.CodeLens(range, {
              title: `▶ Call ${name}`,
              command: "flua.callAction",
              arguments: [document.uri, name, params],
            })
          );
        }
        continue;
      }
      if (interact && /^\s*--%%u:/.test(line)) {
        const elements = elementsOnLine(line);
        if (!elements.length) {
          continue;
        }
        const one = elements.length === 1 ? elements[0] : undefined;
        lenses.push(
          new vscode.CodeLens(range, {
            title: one
              ? `▶ ${one.kind} '${one.name}'`
              : `▶ UI events (${elements.length})`,
            command: "flua.uiEvent",
            arguments: [document.uri, one, i],
          })
        );
      }
    }
    return lenses;
  }
}

/** Register the run/watch commands, the served-page webviews, the action/
 * UI-event lenses and their commands. */
export function registerRun(context: vscode.ExtensionContext): void {
  const lenses = new FluaCodeLensProvider();
  context.subscriptions.push(
    vscode.commands.registerCommand("flua.run", (uri?: vscode.Uri) => runQa(uri)),
    vscode.commands.registerCommand("flua.runWatch", (uri?: vscode.Uri) =>
      runQa(uri, true)
    ),
    vscode.commands.registerCommand("flua.openViewer", () => void openFluaPage("viewer")),
    vscode.commands.registerCommand("flua.openTimeline", () => void openFluaPage("timeline")),
    vscode.commands.registerCommand("flua.openDocs", () => void openFluaPage("docs")),
    vscode.commands.registerCommand(
      "flua.callAction",
      (uri: vscode.Uri, action: string, params: string[]) =>
        void callAction(uri, action, params)
    ),
    vscode.commands.registerCommand(
      "flua.uiEvent",
      (uri: vscode.Uri, element?: UiElement, line?: number) =>
        void injectUiEvent(uri, element, line)
    ),
    vscode.languages.registerCodeLensProvider({ language: "lua" }, lenses),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("flua.codeLens") ||
          event.affectsConfiguration("flua.codeLensInteract")) {
        lenses.refresh();
      }
    })
  );
}
