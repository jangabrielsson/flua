import * as path from "path";
import * as vscode from "vscode";
import { execFlua, fluaExecutable } from "./flua";

interface Finding {
  file: string;
  severity: "error" | "warning";
  message: string;
  line?: number; // 1-based, from flua --check --json
  column?: number; // 1-based, optional
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
    const range = findingRange(finding);
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

/** The finding's editor range: the structured line/column (1-based) from
 * flua's JSON, anchored at the column when present; whole-line otherwise.
 * Older flua versions embed the line in the message instead — fall back. */
function findingRange(finding: Finding): vscode.Range {
  let line: number | undefined;
  let column: number | undefined;
  if (typeof finding.line === "number" && finding.line > 0) {
    line = finding.line - 1;
    column = typeof finding.column === "number" && finding.column > 0
      ? finding.column - 1
      : 0;
  } else {
    line = extractLine(finding.message);
    column = 0;
  }
  if (line === undefined) {
    return new vscode.Range(0, 0, 0, Number.MAX_SAFE_INTEGER);
  }
  return new vscode.Range(line, column, line, Number.MAX_SAFE_INTEGER);
}

/** Lua/lupa error messages embed line numbers ("line 12", "[string ...]:3"). */
function extractLine(message: string): number | undefined {
  const match = message.match(/line\s+(\d+)/i);
  if (match) {
    return Math.max(0, parseInt(match[1], 10) - 1);
  }
  return undefined;
}
