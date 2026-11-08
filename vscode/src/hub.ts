import * as path from "path";
import * as vscode from "vscode";
import { QaCache } from "./cache";
import { execFlua, fluaExecutable, runFluaTool, runInTerminal } from "./flua";

/** `flua --tool hubList`'s JSON document — the contract the tree renders. */
interface HubInfo {
  url: string;
  reachable: boolean;
  name?: string;
  model?: string;
  firmware?: string;
  error?: string;
}

interface QaInfo {
  id: number;
  name: string;
  type: string;
  room: string | null;
  modified?: number | null;
}

interface HubListDoc {
  hub: HubInfo;
  qas: QaInfo[];
}

type TreeNode =
  | { kind: "hub"; doc: HubListDoc }
  | { kind: "qa"; qa: QaInfo };

class HubProvider implements vscode.TreeDataProvider<TreeNode> {
  private doc?: HubListDoc;
  private resolvedFlua?: string;
  private sortMode: "name" | "id" = "name";
  private filter = "";
  private readonly onChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.onChange.event;

  constructor(
    private readonly context: vscode.ExtensionContext
  ) {}

  refresh(): void {
    this.doc = undefined;
    this.onChange.fire();
    void this.fetch();
  }

  async fetch(): Promise<void> {
    const flua = fluaExecutable();
    this.resolvedFlua = flua;
    const result = await execFlua(flua, ["--tool", "hubList"]);
    if (result.code === 2) {
      // no HC3 credentials — the tree explains itself, no popup noise
      this.doc = {
        hub: { url: "", reachable: false, error: result.stderr.trim() || "no HC3 credentials" },
        qas: [],
      };
      this.onChange.fire();
      return;
    }
    // exit code 1 means "hub reachable but the house call failed" — the
    // JSON on stdout still carries the hub object and the error; show it
    try {
      const parsed = JSON.parse(result.stdout) as HubListDoc;
      if (parsed.hub) {
        this.doc = parsed;
      } else {
        throw new Error("no hub object");
      }
    } catch {
      if (result.code !== 0) {
        void vscode.window.showWarningMessage(
          `flua: cannot read the hub (flua at ${flua}) — ` +
            `${result.stderr.trim() || result.stdout.trim()}`
        );
        return;
      }
      this.doc = {
        hub: { url: "", reachable: false, error: "cannot parse `flua --tool hubList` output" },
        qas: [],
      };
    }
    this.onChange.fire();
  }

  getTreeItem(node: TreeNode): vscode.TreeItem {
    if (node.kind === "hub") {
      const hub = node.doc.hub;
      const item = new vscode.TreeItem(
        hub.name || "HC3 hub",
        vscode.TreeItemCollapsibleState.Expanded
      );
      item.contextValue = "fluaHub";
      item.iconPath = new vscode.ThemeIcon("home");
      const bits: string[] = [];
      if (hub.reachable) {
        if (hub.model) bits.push(hub.model);
        if (hub.firmware) bits.push(hub.firmware);
        const qas = this.visibleQas(node.doc.qas);
        bits.push(`${qas.length} QAs`);
        if (this.filter) bits.push(`filter "${this.filter}"`);
        if (this.sortMode === "id") bits.push("by id");
      }
      item.description = bits.join(" · ") || hub.error || "";
      item.tooltip = hub.url
        ? `${hub.name ?? "HC3 hub"} — ${hub.url}`
        : hub.error ?? "";
      if (this.resolvedFlua) {
        item.tooltip += `\nflua: ${this.resolvedFlua}`;
      }
      return item;
    }
    const qa = node.qa;
    const item = new vscode.TreeItem(
      qa.name,
      vscode.TreeItemCollapsibleState.None
    );
    item.contextValue = "fluaQa";
    item.description = `${qa.id} · ${qa.type}`;
    item.tooltip = qa.room ? `${qa.name} (${qa.id}) — ${qa.room}` : `${qa.name} (${qa.id})`;
    item.command = {
      command: "flua.hub.showActions",
      title: "QA actions",
      arguments: [qa],
    };
    return item;
  }

  /** Sort + filter, applied to the QA children of the hub node. */
  private visibleQas(qas: QaInfo[]): QaInfo[] {
    let out = qas;
    const needle = this.filter.trim().toLowerCase();
    if (needle) {
      out = out.filter(
        (qa) =>
          qa.name.toLowerCase().includes(needle) ||
          String(qa.id).includes(needle)
      );
    }
    return [...out].sort((a, b) =>
      this.sortMode === "id"
        ? (a.id ?? 0) - (b.id ?? 0)
        : a.name.localeCompare(b.name)
    );
  }

  cycleSort(): void {
    this.sortMode = this.sortMode === "name" ? "id" : "name";
    this.onChange.fire();
  }

  /** The cache key: the hub's serial (hcName), else the URL — several
   * hubs must never share one cache directory. */
  hubSerial(): string {
    const hub = this.doc?.hub;
    return (hub?.name || hub?.url || "hub").replace(/[^A-Za-z0-9_.-]+/g, "_");
  }

  async setFilter(): Promise<void> {
    const next = await vscode.window.showInputBox({
      prompt: "Filter QAs by name (or id) — empty clears",
      value: this.filter,
      placeHolder: "e.g. heating",
    });
    if (next === undefined) {
      return; // cancelled
    }
    this.filter = next;
    this.onChange.fire();
  }

  async getChildren(node?: TreeNode): Promise<TreeNode[]> {
    if (node) {
      return node.kind === "hub"
        ? this.visibleQas(node.doc.qas ?? []).map((qa) => ({ kind: "qa", qa }))
        : [];
    }
    if (!this.doc) {
      await this.fetch();
    }
    return this.doc ? [{ kind: "hub", doc: this.doc }] : [];
  }
}

/** The directory a QA downloads into: <workspace>/<sanitized-name>-<id> —
 * deterministic, so Run/Update/Pack find the project again. */
function downloadDir(qa: QaInfo): vscode.Uri | undefined {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!root) {
    void vscode.window.showWarningMessage("flua: open a workspace folder first");
    return undefined;
  }
  const safe = qa.name.replace(/[^A-Za-z0-9_.-]+/g, "_");
  return vscode.Uri.joinPath(root, `${safe}-${qa.id}`);
}

function rememberDir(context: vscode.ExtensionContext, id: number, dir: string): void {
  const dirs = context.workspaceState.get<Record<string, string>>("hub.dirs", {});
  dirs[String(id)] = dir;
  void context.workspaceState.update("hub.dirs", dirs);
}

function knownDir(context: vscode.ExtensionContext, id: number): string | undefined {
  return context.workspaceState.get<Record<string, string>>("hub.dirs", {})[String(id)];
}

/** The QA's main Lua file in a downloaded project: the first top-level .lua. */
async function findMainLua(dir: vscode.Uri): Promise<vscode.Uri | undefined> {
  const files = await vscode.workspace.findFiles(
    new vscode.RelativePattern(dir, "*.lua"),
    null,
    50
  );
  return files[0];
}

async function mainLuaFor(
  context: vscode.ExtensionContext,
  qa: QaInfo
): Promise<vscode.Uri | undefined> {
  const known = knownDir(context, qa.id);
  if (known) {
    return findMainLua(vscode.Uri.file(known));
  }
  const picked = await vscode.window.showOpenDialog({
    canSelectFolders: true,
    canSelectFiles: false,
    canSelectMany: false,
    openLabel: "Select the QA's project folder",
    title: `flua: where is ${qa.name} (${qa.id}) unpacked?`,
    defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
  });
  if (!picked?.[0]) {
    return undefined;
  }
  rememberDir(context, qa.id, picked[0].fsPath);
  return findMainLua(picked[0]);
}

function viewerPort(): number {
  return vscode.workspace.getConfiguration("flua").get<number>("viewerPort", 8090);
}

async function actionRunUi(context: vscode.ExtensionContext, qa: QaInfo): Promise<void> {
  const main = await mainLuaFor(context, qa);
  if (!main) {
    void vscode.window.showWarningMessage(
      `flua: no Lua files found for ${qa.name} — download it first`
    );
    return;
  }
  runInTerminal(fluaExecutable(), ["--ui", String(viewerPort()), main.fsPath],
    path.dirname(main.fsPath));
}

async function actionUpdate(context: vscode.ExtensionContext, qa: QaInfo): Promise<void> {
  const main = await mainLuaFor(context, qa);
  if (!main) {
    return;
  }
  runFluaTool(["--tool", "updateQA", String(qa.id), main.fsPath]);
}

async function actionPack(context: vscode.ExtensionContext, qa: QaInfo): Promise<void> {
  const main = await mainLuaFor(context, qa);
  if (!main) {
    return;
  }
  runFluaTool(["--tool", "pack", main.fsPath]);
}

/** Download for editing: cache-or-fetch the .fqa (one export call at
 * most), then unpack the cached package into the workspace project dir. */
async function downloadForEdit(
  context: vscode.ExtensionContext,
  provider: HubProvider,
  qa: QaInfo
): Promise<void> {
  const target = downloadDir(qa);
  if (!target) {
    return;
  }
  rememberDir(context, qa.id, target.fsPath);
  const fqa = await new QaCache(context).ensure(provider.hubSerial(), qa);
  if (!fqa) {
    return;
  }
  runFluaTool(["--tool", "unpack", fqa.fsPath, "-d", target.fsPath]);
}

/** View: open the (cached) .fqa in the flua package editor, no unpacking. */
async function viewFqa(
  context: vscode.ExtensionContext,
  provider: HubProvider,
  qa: QaInfo
): Promise<void> {
  const fqa = await new QaCache(context).ensure(provider.hubSerial(), qa);
  if (!fqa) {
    return;
  }
  await vscode.commands.executeCommand("vscode.openWith", fqa, "flua.fqaViewer");
}

function registerCommands(
  context: vscode.ExtensionContext,
  provider: HubProvider
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("flua.hub.refresh", () => provider.refresh()),

    vscode.commands.registerCommand("flua.hub.sort", () => provider.cycleSort()),

    vscode.commands.registerCommand("flua.hub.filter", () => void provider.setFilter()),

    vscode.commands.registerCommand("flua.hub.showActions", async (qa: QaInfo) => {
      const dir = knownDir(context, qa.id);
      const labels = [
        { label: "View (.fqa)", detail: "open in the flua package editor (cached)" },
        { label: "Download", detail: dir ? `into ${dir}` : "download + unpack into the workspace" },
        { label: "Update (upload local changes)" },
        { label: "Run (UI)" },
        { label: "Pack into .fqa" },
        { label: "Copy id" },
      ];
      const picked = await vscode.window.showQuickPick(labels, {
        placeHolder: `${qa.name} (${qa.id})`,
      });
      if (!picked) {
        return;
      }
      if (picked.label === "View (.fqa)") {
        await viewFqa(context, provider, qa);
      } else if (picked.label === "Download") {
        await downloadForEdit(context, provider, qa);
      } else if (picked.label.startsWith("Update")) {
        await actionUpdate(context, qa);
      } else if (picked.label === "Run (UI)") {
        await actionRunUi(context, qa);
      } else if (picked.label === "Pack into .fqa") {
        await actionPack(context, qa);
      } else if (picked.label === "Copy id") {
        await vscode.env.clipboard.writeText(String(qa.id));
        void vscode.window.showInformationMessage(`flua: copied QA id ${qa.id}`);
      }
    }),

    vscode.commands.registerCommand("flua.hub.download", (qa: QaInfo) =>
      void downloadForEdit(context, provider, qa)
    ),

    vscode.commands.registerCommand("flua.hub.view", (qa: QaInfo) =>
      void viewFqa(context, provider, qa)
    ),

    vscode.commands.registerCommand("flua.hub.update", (qa: QaInfo) =>
      void actionUpdate(context, qa)
    ),

    vscode.commands.registerCommand("flua.hub.runUi", (qa: QaInfo) =>
      void actionRunUi(context, qa)
    ),

    vscode.commands.registerCommand("flua.hub.pack", (qa: QaInfo) =>
      void actionPack(context, qa)
    ),

    vscode.commands.registerCommand("flua.hub.copyId", async (qa: QaInfo) => {
      await vscode.env.clipboard.writeText(String(qa.id));
      void vscode.window.showInformationMessage(`flua: copied QA id ${qa.id}`);
    })
  );
}

export function registerHub(context: vscode.ExtensionContext): void {
  const provider = new HubProvider(context);
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("flua.hub", provider)
  );
  registerCommands(context, provider);
  void provider.fetch();
}
