import * as path from "path";
import * as vscode from "vscode";
import { checkDocument, registerCheckDiagnostics } from "./check";
import { execFlua, fluaExecutable, runFluaTool } from "./flua";
import { FqaEditorProvider } from "./fqaEditor";
import { registerMcp, unregisterMcp } from "./mcp";

export function activate(context: vscode.ExtensionContext) {
  registerCheckDiagnostics(context);
  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(
      FqaEditorProvider.viewType,
      new FqaEditorProvider()
    )
  );
  void maybeNudgeSetup();

  context.subscriptions.push(
    vscode.commands.registerCommand("flua.setup", async () => {
      const dir = await pickDirectory();
      if (dir === undefined) {
        return;
      }
      runFluaTool(["--tool", "setup", dir]);
    }),

    vscode.commands.registerCommand("flua.check", async (uri?: vscode.Uri) => {
      const target = uri ?? vscode.window.activeTextEditor?.document.uri;
      if (!target) {
        void vscode.window.showWarningMessage("No Lua file to check");
        return;
      }
      await checkDocument(target);
    }),

    vscode.commands.registerCommand("flua.pack", (uri: vscode.Uri) =>
      runFluaTool(["--tool", "pack", uri.fsPath])
    ),

    vscode.commands.registerCommand("flua.unpack", (uri: vscode.Uri) =>
      runFluaTool(["--tool", "unpack", uri.fsPath])
    ),

    vscode.commands.registerCommand("flua.uploadFile", (uri: vscode.Uri) =>
      runFluaTool(["--tool", "uploadFile", uri.fsPath])
    ),

    vscode.commands.registerCommand("flua.uploadFqa", (uri: vscode.Uri) =>
      runFluaTool(["--tool", "uploadFQA", uri.fsPath])
    ),

    vscode.commands.registerCommand("flua.updateQa", async (uri: vscode.Uri) => {
      const id = await askQaId("Update this QA's files on the HC3");
      if (!id) {
        return;
      }
      runFluaTool(["--tool", "updateQA", id, uri.fsPath]);
    }),

    vscode.commands.registerCommand("flua.downloadQa", async () => {
      const id = await askQaId("Download this QA from the HC3");
      if (!id) {
        return;
      }
      runFluaTool(["--tool", "downloadQA", id]);
    }),

    vscode.commands.registerCommand("flua.newQa", async (uri?: vscode.Uri) => {
      const folder = uri ? path.dirname(uri.fsPath) : undefined;
      const type = await pickTemplateType();
      if (!type) {
        return;
      }
      const name = await vscode.window.showInputBox({
        prompt: "QA name (--%%name) — empty for the template's own name",
      });
      if (name === undefined) {
        return; // cancelled
      }
      const args = ["--tool", "newQA", type];
      if (name) {
        args.push(name);
      }
      runFluaTool(args, folder);
    }),

    vscode.commands.registerCommand("flua.mcpRegister", () => void registerMcp()),

    vscode.commands.registerCommand("flua.mcpUnregister", () => void unregisterMcp())
  );
}

export function deactivate() {}

/** One-time onboarding nudge: a workspace with Lua files but no
 * .luarc.json/.luals has no HC3 autocomplete — offer to run Setup
 * workspace. Off by default after "Don't ask again" (the flua.setupNudge
 * setting) or once setup has been run (the files exist). */
async function maybeNudgeSetup(): Promise<void> {
  if (!vscode.workspace.getConfiguration("flua").get<boolean>("setupNudge", true)) {
    return;
  }
  let target: vscode.WorkspaceFolder | undefined;
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const luaFiles = await vscode.workspace.findFiles(
      new vscode.RelativePattern(folder, "**/*.lua"),
      null,
      20
    );
    if (!luaFiles.length) {
      continue;
    }
    let configured = false;
    for (const marker of [".luarc.json", ".luals"]) {
      try {
        await vscode.workspace.fs.stat(vscode.Uri.joinPath(folder.uri, marker));
        configured = true;
        break;
      } catch {
        // marker absent — keep looking
      }
    }
    if (!configured) {
      target = folder;
      break;
    }
  }
  if (!target) {
    return;
  }
  const action = await vscode.window.showInformationMessage(
    "flua: this workspace has Lua files but no HC3 completion config " +
      "(.luarc.json/.luals). Run Setup workspace?",
    "Run setup",
    "Don't ask again"
  );
  if (action === "Run setup") {
    runFluaTool(["--tool", "setup", target.uri.fsPath]);
  } else if (action === "Don't ask again") {
    await vscode.workspace
      .getConfiguration("flua")
      .update("setupNudge", false, vscode.ConfigurationTarget.Global);
  }
}

async function askQaId(prompt: string): Promise<string | undefined> {
  return vscode.window.showInputBox({
    prompt,
    validateInput: (value) =>
      /^\d+$/.test(value) ? undefined : "The QA id must be a number",
  });
}

/** Quick Pick over `flua --tool newQA`'s template list (always in sync
 * with the installed flua), falling back to free text when flua is
 * missing or the listing cannot be parsed. */
async function pickTemplateType(): Promise<string | undefined> {
  const flua = fluaExecutable();
  const result = await execFlua(flua, ["--tool", "newQA"]);
  const templates: string[] = [];
  let listing = false;
  for (const line of result.stdout.split("\n")) {
    if (line.startsWith("available QA templates")) {
      listing = true;
      continue;
    }
    if (!listing) {
      continue;
    }
    const name = line.trim();
    if (name) {
      templates.push(name);
    }
  }
  if (templates.length) {
    return vscode.window.showQuickPick(templates, {
      placeHolder: "QA device type (41 templates)",
    });
  }
  return vscode.window.showInputBox({
    prompt: "QA device type (e.g. binarySwitch, motionSensor)",
  });
}

async function pickDirectory(): Promise<string | undefined> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFolders: true,
    canSelectFiles: false,
    canSelectMany: false,
    openLabel: "Setup flua here",
    defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
    title: "flua: setup workspace",
  });
  return picked?.[0]?.fsPath;
}
