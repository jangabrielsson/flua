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

/** ▶ Run QA CodeLens on QuickApp:onInit / selfTest lines (flua.codeLens). */
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
    const lenses: vscode.CodeLens[] = [];
    for (let i = 0; i < document.lineCount; i++) {
      const match = document.lineAt(i).text.match(/^\s*function\s+QuickApp:(onInit|selfTest)\b/);
      if (!match) {
        continue;
      }
      const range = new vscode.Range(i, 0, i, document.lineAt(i).text.length);
      lenses.push(
        new vscode.CodeLens(range, {
          title: match[1] === "selfTest" ? "▶ Run selfTest" : "▶ Run QA",
          command: "flua.run",
          arguments: [document.uri],
        })
      );
    }
    return lenses;
  }
}

/** Register the run/watch commands, the served-page webviews, and the
 * CodeLens provider. */
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
    vscode.languages.registerCodeLensProvider({ language: "lua" }, lenses),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("flua.codeLens")) {
        lenses.refresh();
      }
    })
  );
}
