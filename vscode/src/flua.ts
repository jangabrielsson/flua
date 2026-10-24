import * as cp from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

/**
 * Resolve the flua executable: the `flua.executable` setting, else a
 * `.venv/bin/flua` (`.venv/Scripts/flua.exe` on Windows) walked up from
 * each workspace folder, else `flua` on PATH.
 */
export function fluaExecutable(): string {
  const configured = vscode.workspace
    .getConfiguration("flua")
    .get<string>("executable", "");
  if (configured) {
    return configured;
  }
  for (const root of vscode.workspace.workspaceFolders ?? []) {
    let dir: string | null = root.uri.fsPath;
    while (dir) {
      for (const candidate of [
        path.join(dir, ".venv", "bin", "flua"),
        path.join(dir, ".venv", "Scripts", "flua.exe"),
      ]) {
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      }
      const parent = path.dirname(dir);
      dir = parent === dir ? null : parent;
    }
  }
  return "flua"; // PATH lookup at spawn time
}

export interface ExecResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

/** Run flua, capturing stdout/stderr. Resolves even when spawn itself
 * fails (ENOENT etc.) — code is -1 and the error lands in stderr. */
export function execFlua(
  flua: string,
  args: string[],
  cwd?: string
): Promise<ExecResult> {
  return new Promise((resolve) => {
    const child = cp.spawn(flua, args, { cwd });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    child.on("error", (err) =>
      resolve({ code: -1, stdout, stderr: String(err) })
    );
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function shellQuote(arg: string): string {
  if (/^[a-zA-Z0-9_./:=@%+\-]+$/.test(arg)) {
    return arg;
  }
  return `"${arg.replace(/"/g, '\\"')}"`;
}

/** Run flua in a shared "flua" terminal — visible output, interactive
 * credential prompts keep working. */
export function runInTerminal(flua: string, args: string[], cwd?: string) {
  const terminal = vscode.window.createTerminal({ name: "flua", cwd });
  terminal.show();
  terminal.sendText([flua, ...args].map(shellQuote).join(" "));
}

let outputChannel: vscode.OutputChannel | undefined;

/** Run a flua command: in the shared terminal by default (visible output,
 * interactive prompts), or captured into the output channel. The single
 * entry point every command (and the .fqa editor) uses. */
export function runFluaTool(args: string[], cwd?: string) {
  const flua = fluaExecutable();
  const inTerminal = vscode.workspace
    .getConfiguration("flua")
    .get<boolean>("runToolsInTerminal", true);
  if (inTerminal) {
    runInTerminal(flua, args, cwd);
    return;
  }
  void (async () => {
    const result = await execFlua(flua, args, cwd);
    outputChannel ??= vscode.window.createOutputChannel("flua");
    outputChannel.appendLine(`$ ${flua} ${args.join(" ")}`);
    if (result.stdout) {
      outputChannel.append(result.stdout);
    }
    if (result.stderr) {
      outputChannel.append(result.stderr);
    }
    outputChannel.show();
  })();
}
