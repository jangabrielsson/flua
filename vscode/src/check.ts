import * as path from "path";
import * as vscode from "vscode";
import { execFlua, fluaExecutable } from "./flua";

interface Finding {
  file: string;
  severity: "error" | "warning";
  message: string;
}

interface CheckPayload {
  ok?: boolean;
  findings?: Finding[];
}

const collection = vscode.languages.createDiagnosticCollection("flua");
// URIs last written by a check — cleared before the next one so findings
// for --%%file includes that got fixed do not linger.
let lastUris = new Set<string>();

export function registerCheckDiagnostics(context: vscode.ExtensionContext) {
  context.subscriptions.push(
    collection,
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.languageId === "lua") {
        void checkDocument(doc.uri);
      }
    }),
    vscode.workspace.onDidCloseTextDocument((doc) => {
      if (doc.languageId === "lua") {
        collection.delete(doc.uri);
      }
    })
  );
}

/** Run `flua --check --json` on a QA file and publish the findings as
 * editor diagnostics. Findings for --%%file includes land on those files. */
export async function checkDocument(uri: vscode.Uri): Promise<void> {
  const flua = fluaExecutable();
  const result = await execFlua(flua, ["--check", "--json", uri.fsPath]);
  if (result.code === -1) {
    void vscode.window.showWarningMessage(
      `flua not found (${result.stderr.trim()}) — set flua.executable`
    );
    return;
  }
  let payload: CheckPayload;
  try {
    payload = JSON.parse(result.stdout) as CheckPayload;
  } catch {
    return; // non-JSON stdout: --check output went elsewhere; stay silent
  }
  for (const old of lastUris) {
    collection.delete(vscode.Uri.file(old));
  }
  lastUris = new Set<string>();
  const findings = payload.findings ?? [];
  const byFile = new Map<string, vscode.Diagnostic[]>();
  for (const finding of findings) {
    const line = extractLine(finding.message);
    const range =
      line !== undefined
        ? new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER)
        : new vscode.Range(0, 0, 0, Number.MAX_SAFE_INTEGER);
    const diagnostic = new vscode.Diagnostic(
      range,
      finding.message,
      finding.severity === "error"
        ? vscode.DiagnosticSeverity.Error
        : vscode.DiagnosticSeverity.Warning
    );
    diagnostic.source = "flua";
    const key = finding.file || uri.fsPath;
    const list = byFile.get(key) ?? [];
    list.push(diagnostic);
    byFile.set(key, list);
  }
  for (const [file, diagnostics] of byFile) {
    const fileUri = vscode.Uri.file(file);
    lastUris.add(file);
    collection.set(fileUri, diagnostics);
  }
  if (!findings.length) {
    // the checked file is clean — no diagnostics to show, nothing to clear
    lastUris.add(uri.fsPath);
  }
  if (result.code !== 0) {
    const basename = path.basename(uri.fsPath);
    void vscode.window.showWarningMessage(
      `flua: ${basename} has ${findings.length} finding(s) — see the Problems panel`
    );
  }
}

/** Lua/lupa error messages embed line numbers ("line 12", "[string ...]:3"). */
function extractLine(message: string): number | undefined {
  const match = message.match(/line\s+(\d+)/i);
  if (match) {
    return Math.max(0, parseInt(match[1], 10) - 1);
  }
  return undefined;
}
