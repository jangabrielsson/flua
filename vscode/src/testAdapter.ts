import * as path from "path";
import * as vscode from "vscode";
import { execFlua, fluaExecutable } from "./flua";

/** The flua test adapter for the VS Code Test Explorer: self-asserting
 * test QAs (`*_test.lua`, the quickapp-test pattern) appear as test items
 * and run through `flua test --json` — the same CLI contract agents get.
 * The adapter is a thin shell: discovery is `flua test --list`, execution
 * is `flua test --json`, nothing lives only in the extension. */

interface JsonEntry {
  file: string;
  status: "pass" | "fail" | "timeout";
  exitCode: number | null;
  failures: number | null;
  output: string;
}

function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

/** Discovered test files: one TestItem per file, id = the runner's
 * display path (relative to the workspace root). */
async function discover(root: string): Promise<Map<string, vscode.TestItem>> {
  const files = new Map<string, vscode.TestItem>();
  const result = await execFlua(fluaExecutable(), ["test", "--list"], root);
  if (result.code !== 0) {
    return files;
  }
  for (const line of result.stdout.split("\n")) {
    const absolute = line.trim();
    if (!absolute.endsWith(".lua")) {
      continue;
    }
    const display = absolute.startsWith(root)
      ? path.relative(root, absolute)
      : absolute;
    const item = controller!.createTestItem(
      display,
      path.basename(display),
      vscode.Uri.file(absolute)
    );
    files.set(display, item);
  }
  return files;
}

/** The controller, created once on activation, and the current item set
 * (display path -> item), shared between refresh and run. */
let controller: vscode.TestController | undefined;
const itemsByFile = new Map<string, vscode.TestItem>();

export function registerTestAdapter(context: vscode.ExtensionContext): void {
  controller = vscode.tests.createTestController("flua.tests", "flua tests");
  context.subscriptions.push(controller);

  controller.refreshHandler = async () => {
    const root = workspaceRoot();
    if (!root) {
      return;
    }
    const files = await discover(root);
    itemsByFile.clear();
    for (const [display, item] of files) {
      itemsByFile.set(display, item);
    }
    controller!.items.replace([...files.values()]);
  };

  controller.createRunProfile(
    "Run",
    vscode.TestRunProfileKind.Run,
    async (request, token) => {
      const root = workspaceRoot();
      const run = controller!.createTestRun(request);
      if (!root) {
        void vscode.window.showWarningMessage(
          "flua: open a workspace folder to run QA tests"
        );
        run.end();
        return;
      }
      if (!itemsByFile.size) {
        const files = await discover(root);
        itemsByFile.clear();
        for (const [display, item] of files) {
          itemsByFile.set(display, item);
        }
        controller!.items.replace([...files.values()]);
      }
      if (!itemsByFile.size) {
        void vscode.window.showInformationMessage(
          "flua: no *_test.lua files in the workspace"
        );
        run.end();
        return;
      }
      for (const item of itemsByFile.values()) {
        run.enqueued(item);
      }
      const result = await execFlua(fluaExecutable(), ["test", "--json"], root);
      if (result.code === -1) {
        for (const item of itemsByFile.values()) {
          run.failed(item, new vscode.TestMessage(`cannot run: ${result.stderr}`));
        }
        run.end();
        return;
      }
      let doc: { files: JsonEntry[] };
      try {
        doc = JSON.parse(result.stdout);
      } catch {
        // e.g. "no *_test.lua files found" — nothing to report
        run.end();
        return;
      }
      for (const entry of doc.files) {
        const item = itemsByFile.get(entry.file);
        if (!item) {
          continue;
        }
        if (entry.status === "pass") {
          run.passed(item);
          continue;
        }
        const message = new vscode.TestMessage(
          entry.status === "timeout"
            ? "timed out (the QA never exited — end tests with t:finish()/exit(...))"
            : entry.output || `failed (failures: ${entry.failures ?? "?"})`
        );
        message.location = new vscode.Location(
          item.uri ?? vscode.Uri.file(entry.file),
          new vscode.Position(0, 0)
        );
        run.failed(item, message);
      }
      run.end();
    },
    true
  );
}
