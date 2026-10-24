import * as path from "path";
import * as vscode from "vscode";
import { fluaExecutable } from "./flua";

const SERVER_KEY = "flua";

/** The python interpreter flua runs on: flua at <venv>/bin/flua ->
 * <venv>/bin/python (<venv>/Scripts/python.exe on Windows). Falls back to
 * `python` on PATH — the same command docs/mcp.md documents for Copilot. */
function pythonInterpreter(): string {
  const flua = fluaExecutable();
  if (!flua.includes(path.sep)) {
    return "python";
  }
  for (const [suffix, replacement] of [
    [path.join("bin", "flua"), path.join("bin", "python")],
    [path.join("Scripts", "flua.exe"), path.join("Scripts", "python.exe")],
  ] as const) {
    if (flua.endsWith(suffix)) {
      return flua.slice(0, -suffix.length) + replacement;
    }
  }
  return "python";
}

interface McpServerEntry {
  command: string;
  args?: string[];
  [key: string]: unknown;
}

interface McpConfig {
  mcpServers?: Record<string, McpServerEntry>;
}

async function mcpTargets(): Promise<
  { folder: vscode.WorkspaceFolder; file: vscode.Uri } | undefined
> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    void vscode.window.showWarningMessage("flua: open a workspace folder first");
    return undefined;
  }
  return { folder, file: vscode.Uri.joinPath(folder.uri, ".vscode", "mcp.json") };
}

async function readConfig(file: vscode.Uri): Promise<McpConfig> {
  try {
    const raw = await vscode.workspace.fs.readFile(file);
    return JSON.parse(Buffer.from(raw).toString("utf8")) as McpConfig;
  } catch {
    return {};
  }
}

/** Write/merge the flua-mcp stdio server into the workspace's
 * .vscode/mcp.json (VS Code Copilot's MCP config) — other servers in the
 * file are left untouched. Idempotent. */
export async function registerMcp(): Promise<void> {
  const targets = await mcpTargets();
  if (!targets) {
    return;
  }
  const { folder, file } = targets;
  const config = await readConfig(file);
  const servers = config.mcpServers ?? {};
  const entry: McpServerEntry = {
    command: pythonInterpreter(),
    args: ["-m", "flua.mcp.server"],
  };
  const existing = servers[SERVER_KEY];
  const unchanged =
    existing !== undefined &&
    existing.command === entry.command &&
    JSON.stringify(existing.args ?? []) === JSON.stringify(entry.args);
  servers[SERVER_KEY] = entry;
  config.mcpServers = servers;
  await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(folder.uri, ".vscode"));
  await vscode.workspace.fs.writeFile(
    file,
    Buffer.from(JSON.stringify(config, null, 2) + "\n")
  );
  void vscode.window.showInformationMessage(
    `flua: flua-mcp registered in .vscode/mcp.json (command: ${entry.command})${
      unchanged ? " — already up to date" : " — reload VS Code for Copilot to pick it up"
    }`
  );
}

export async function unregisterMcp(): Promise<void> {
  const targets = await mcpTargets();
  if (!targets) {
    return;
  }
  const config = await readConfig(targets.file);
  if (!config.mcpServers?.[SERVER_KEY]) {
    void vscode.window.showInformationMessage(
      "flua: flua-mcp is not registered in .vscode/mcp.json"
    );
    return;
  }
  delete config.mcpServers[SERVER_KEY];
  await vscode.workspace.fs.writeFile(
    targets.file,
    Buffer.from(JSON.stringify(config, null, 2) + "\n")
  );
  void vscode.window.showInformationMessage(
    "flua: flua-mcp removed from .vscode/mcp.json"
  );
}
