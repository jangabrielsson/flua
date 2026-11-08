import * as path from "path";
import * as vscode from "vscode";
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
    const result = await execFlua(fluaExecutable(), ["--tool", "hubList"]);
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
          `flua: cannot read the hub — ${result.stderr.trim() || result.stdout.trim()}`
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
      item.iconPath = new vscode.ThemeIcon("server");
      const bits: string[] = [];
      if (hub.reachable) {
        if (hub.model) bits.push(hub.model);
        if (hub.firmware) bits.push(hub.firmware);
      }
      item.description = bits.join(" · ") || hub.error || "";
      item.tooltip = hub.url ? `${hub.name ?? "HC3 hub"} — ${hub.url}` : hub.error ?? "";
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

  async getChildren(node?: TreeNode): Promise<TreeNode[]> {
    if (node) {
      return node.kind === "hub"
        ? (node.doc.qas ?? []).map((qa) => ({ kind: "qa", qa }))
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

function registerCommands(
  context: vscode.ExtensionContext,
  provider: HubProvider
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("flua.hub.refresh", () => provider.refresh()),

    vscode.commands.registerCommand("flua.hub.showActions", async (qa: QaInfo) => {
      const dir = knownDir(context, qa.id);
      const labels = [
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
      if (picked.label === "Download") {
        const target = downloadDir(qa);
        if (!target) {
          return;
        }
        rememberDir(context, qa.id, target.fsPath);
        runFluaTool(["--tool", "downloadQA", "-d", target.fsPath, String(qa.id)]);
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

    vscode.commands.registerCommand("flua.hub.download", (qa: QaInfo) => {
      const target = downloadDir(qa);
      if (!target) {
        return;
      }
      rememberDir(context, qa.id, target.fsPath);
      runFluaTool(["--tool", "downloadQA", "-d", target.fsPath, String(qa.id)]);
    }),

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
