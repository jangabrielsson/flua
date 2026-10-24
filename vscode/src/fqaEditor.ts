import * as vscode from "vscode";
import { runFluaTool } from "./flua";

/**
 * Custom editor for .fqa packages: a metadata summary (name, type,
 * interfaces, file table) plus a per-file Lua preview — no raw JSON dump.
 * The plain JSON view stays available via "Reopen Editor With... Text
 * Editor", with the contributed schema validation. The package contents
 * are parsed and re-rendered as text (escaped); no remote content.
 */
export class FqaEditorProvider implements vscode.CustomTextEditorProvider {
  public static readonly viewType = "flua.fqaViewer";

  public async resolveCustomTextEditor(
    document: vscode.TextDocument,
    panel: vscode.WebviewPanel
  ): Promise<void> {
    panel.webview.options = { enableScripts: true };
    panel.webview.html = getHtml(panel.webview);

    const post = () => {
      try {
        panel.webview.postMessage({ type: "update", pkg: JSON.parse(document.getText()) });
      } catch (error) {
        panel.webview.postMessage({ type: "invalid", message: String(error) });
      }
    };
    const subscription = vscode.workspace.onDidChangeTextDocument((event) => {
      if (event.document.uri.toString() === document.uri.toString()) {
        post();
      }
    });
    panel.onDidDispose(() => subscription.dispose());
    panel.webview.onDidReceiveMessage((message) => {
      if (message.command === "unpack") {
        runFluaTool(["--tool", "unpack", document.uri.fsPath]);
      } else if (message.command === "upload") {
        runFluaTool(["--tool", "uploadFQA", document.uri.fsPath]);
      }
    });
    post();
  }
}

function getHtml(webview: vscode.Webview): string {
  const nonce = randomNonce();
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<title>flua QA package</title>
<style>
  :root {
    --bg: var(--vscode-editor-background, #1e1e1e);
    --fg: var(--vscode-foreground, #cccccc);
    --dim: var(--vscode-descriptionForeground, #8b8b8b);
    --border: var(--vscode-panel-border, #3c3c3c);
    --accent: var(--vscode-focusBorder, #007fd4);
    --btn: var(--vscode-button-background, #0e639c);
    --btn-fg: var(--vscode-button-foreground, #ffffff);
    --kw: #c586c0; --str: #ce9178; --num: #b5cea8; --com: #6a9955; --fn: #dcdcaa;
  }
  body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
         font-family: var(--vscode-font-family, monospace); font-size: 13px;
         display: flex; flex-direction: column; height: 100vh; }
  header { padding: 12px 16px 8px; border-bottom: 1px solid var(--border); flex: none; }
  h1 { margin: 0 0 4px; font-size: 18px; font-weight: 600; }
  .meta { color: var(--dim); }
  .badge { display: inline-block; padding: 1px 7px; margin-left: 8px;
           border-radius: 9px; background: var(--btn); color: var(--btn-fg);
           font-size: 11px; vertical-align: 2px; }
  #error { margin: 12px 16px; padding: 8px 12px; border-left: 3px solid #f14c4c;
           background: rgba(241, 76, 76, 0.12); display: none; flex: none; }
  #propsBox { flex: none; border-bottom: 1px solid var(--border);
           display: flex; flex-direction: column; }
  dl#properties { display: grid; grid-template-columns: max-content 1fr;
           gap: 1px 16px; margin: 0; padding: 8px 16px; flex: none;
           max-height: 35vh; overflow-y: auto; scrollbar-gutter: stable;
           align-content: start; }
  dl#properties::-webkit-scrollbar { width: 10px; }
  dl#properties::-webkit-scrollbar-thumb { background: var(--dim);
           border-radius: 5px; border: 2px solid var(--bg); }
  dl#properties dt { color: var(--dim); }
  dl#properties dd { margin: 0; white-space: pre-wrap; word-break: break-word;
           font-family: var(--vscode-editor-font-family, monospace); }
  #propsHandle { height: 5px; cursor: ns-resize; flex: none; }
  #propsHandle:hover { background: var(--btn); }
  .split { display: flex; flex: 1; min-height: 0; }
  ul#files { list-style: none; margin: 0; padding: 8px 0; width: 260px;
             border-right: 1px solid var(--border); overflow-y: auto; }
  ul#files li { padding: 5px 14px; cursor: pointer; white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis; }
  ul#files li:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }
  ul#files li.selected { background: var(--vscode-list-activeSelectionBackground, #094771); }
  ul#files .size { color: var(--dim); font-size: 11px; margin-left: 6px; }
  #preview { flex: 1; margin: 0; padding: 10px 16px; overflow: auto;
             white-space: pre; font-family: var(--vscode-editor-font-family, monospace); }
  .tok-kw { color: var(--kw); } .tok-str { color: var(--str); }
  .tok-num { color: var(--num); } .tok-com { color: var(--com); }
  .tok-fn { color: var(--fn); }
  footer { padding: 10px 16px; border-top: 1px solid var(--border);
           background: var(--bg); flex: none; }
  button { background: var(--btn); color: var(--btn-fg); border: none;
           padding: 5px 14px; margin-right: 8px; cursor: pointer; border-radius: 2px; }
  .hint { color: var(--dim); }
</style>
</head>
<body>
<header>
  <h1 id="title">QA package</h1>
  <div class="meta" id="meta"></div>
</header>
<div id="error"></div>
<div id="propsBox">
  <dl id="properties"></dl>
  <div id="propsHandle" title="Drag to resize"></div>
</div>
<div class="split">
  <ul id="files"></ul>
  <pre id="preview"></pre>
</div>
<footer>
  <button id="unpack">Unpack into project</button>
  <button id="upload">Upload as new QA</button>
  <span class="hint">JSON view: right-click the tab → Reopen Editor With… Text Editor</span>
</footer>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  let pkg = null;
  let current = 0;
  let propsHeight = null;
  const saved = vscode.getState && vscode.getState();
  if (saved && saved.propsHeight) propsHeight = saved.propsHeight;

  const $ = (id) => document.getElementById(id);

  function applyPropsHeight() {
    const dl = $("properties");
    if (propsHeight !== null) {
      dl.style.maxHeight = "none";
      dl.style.height = propsHeight + "px";
    }
  }

  function wireResizeHandle() {
    const handle = $("propsHandle");
    handle.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const startY = event.clientY;
      const dl = $("properties");
      const startH = dl.getBoundingClientRect().height || 200;
      const move = (e) => {
        propsHeight = Math.max(
          60,
          Math.min(window.innerHeight * 0.75, startH + (e.clientY - startY))
        );
        applyPropsHeight();
      };
      const up = () => {
        if (vscode.setState) vscode.setState({ propsHeight });
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // minimal Lua tokenizer: comments, strings (incl. long brackets),
  // numbers, and keywords — enough to read a QA
  function highlight(source) {
    const lines = String(source).split("\\n");
    let inLong = false, longLevel = "";
    const out = [];
    for (const line of lines) {
      if (inLong) {
        out.push('<span class="tok-str">' + escapeHtml(line) + "</span>");
        if (line.includes("]" + "=".repeat(longLevel.length) + "]")) inLong = false;
        continue;
      }
      let html = "", i = 0;
      while (i < line.length) {
        const rest = line.slice(i);
        let m;
        if ((m = rest.match(/^--/))) {
          // line comment (a --[[ long comment renders as comments too)
          html += '<span class="tok-com">' + escapeHtml(rest) + "</span>";
          i = line.length;
        } else if ((m = rest.match(/^\\[=*\\[/))) {
          longLevel = m[0].slice(1, -1);
          inLong = true; i = line.length;
          html += '<span class="tok-str">' + escapeHtml(rest) + "</span>";
        } else if ((m = rest.match(/^"(?:[^"\\\\]|\\\\.)*"/)) ||
                   (m = rest.match(/^'(?:[^'\\\\]|\\\\.)*'/))) {
          html += '<span class="tok-str">' + escapeHtml(m[0]) + "</span>";
          i += m[0].length;
        } else if ((m = rest.match(/^(0x[0-9a-fA-F]+|\\d+(?:\\.\\d+)?)/))) {
          html += '<span class="tok-num">' + escapeHtml(m[0]) + "</span>";
          i += m[0].length;
        } else if ((m = rest.match(/^[a-zA-Z_][a-zA-Z0-9_]*/))) {
          const word = m[0];
          const kw = ["local","function","end","if","then","else","elseif","for",
            "while","do","repeat","until","return","break","and","or","not",
            "nil","true","false","in"].includes(word);
          const call = rest[m[0].length] === "(";
          html += (kw ? '<span class="tok-kw">' : call ? '<span class="tok-fn">' : "")
            + escapeHtml(word) + (kw || call ? "</span>" : "");
          i += word.length;
        } else {
          html += escapeHtml(line[i]);
          i += 1;
        }
      }
      out.push(html);
    }
    return out.join("\\n");
  }

  function lineCount(text) { return String(text).split("\\n").length; }
  function byteSize(text) { return new Blob([text]).size; }

  function fmtValue(value) {
    if (value === null || value === undefined) return "nil";
    if (typeof value === "string") return escapeHtml(value);
    if (typeof value === "boolean" || typeof value === "number") return String(value);
    try {
      const json = JSON.stringify(value);
      return escapeHtml(json.length > 80 ? json.slice(0, 80) + "…" : json);
    } catch {
      return escapeHtml(String(value));
    }
  }

  // initialProperties -> a compact definition list: scalars as-is,
  // quickAppVariables one row per variable, and the big UI structures
  // (viewLayout/uiView/uiCallbacks) collapsed to a single "UI" row
  function renderProperties(pkg) {
    const box = $("properties");
    box.innerHTML = "";
    const init =
      pkg.initialProperties && typeof pkg.initialProperties === "object"
        ? pkg.initialProperties
        : null;
    const interfaces = Array.isArray(pkg.initialInterfaces) ? pkg.initialInterfaces : [];
    const hasInit = init && Object.keys(init).length > 0;
    if (!hasInit && !pkg.name && !pkg.type && !interfaces.length) {
      box.style.display = "none";
      return;
    }
    box.style.display = "";
    const add = (label, valueHtml) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.innerHTML = valueHtml;
      box.appendChild(dt);
      box.appendChild(dd);
    };
    // the package identity first — name, type and interfaces live at the
    // top level of the .fqa, not inside initialProperties
    if (pkg.name) add("name", escapeHtml(pkg.name));
    if (pkg.type) add("type", escapeHtml(pkg.type));
    if (interfaces.length) add("interfaces", escapeHtml(interfaces.join(", ")));
    const skip = [
      "uiView", "viewLayout", "uiCallbacks", "quickAppVariables",
      "typeTemplateInitialized", // an internal flag the HC3 export carries — noise in the viewer
    ];
    for (const [key, value] of Object.entries(init || {})) {
      if (skip.includes(key) || value === null || value === undefined) continue;
      add(key, fmtValue(value));
    }
    const vars = init && Array.isArray(init.quickAppVariables) ? init.quickAppVariables : [];
    for (const variable of vars) {
      if (variable && variable.name !== undefined) {
        add("var " + variable.name, fmtValue(variable.value));
      }
    }
    const ui = [];
    if (init && Array.isArray(init.uiView) && init.uiView.length) {
      ui.push(init.uiView.length + " uiView elements");
    } else if (init && init.uiView) {
      ui.push("uiView");
    }
    if (init && init.viewLayout) ui.push("viewLayout");
    if (init && Array.isArray(init.uiCallbacks) && init.uiCallbacks.length) {
      ui.push(init.uiCallbacks.length + " callbacks");
    }
    if (ui.length) add("UI", escapeHtml(ui.join(", ")));
    applyPropsHeight();
  }

  function render(pkgData) {
    pkg = pkgData;
    const files = Array.isArray(pkg.files) ? pkg.files : [];
    $("title").textContent = pkg.name || "QuickApp";
    const parts = [];
    if (pkg.type) parts.push(escapeHtml(pkg.type));
    parts.push(files.length + " file" + (files.length === 1 ? "" : "s"));
    $("meta").innerHTML = parts.join(" · ");
    const ifaces = Array.isArray(pkg.initialInterfaces) ? pkg.initialInterfaces : [];
    if (ifaces.length) {
      $("meta").innerHTML += ' <span class="badge">' + escapeHtml(ifaces.join(", ")) + "</span>";
    }
    const list = $("files");
    list.innerHTML = "";
    files.forEach((file, index) => {
      const li = document.createElement("li");
      li.className = index === current ? "selected" : "";
      const name = file.name || "file " + index;
      li.innerHTML = (file.isMain ? "★ " : "") + escapeHtml(name)
        + '<span class="size">' + lineCount(file.content || "") + " lines</span>";
      li.addEventListener("click", () => select(index));
      list.appendChild(li);
    });
    if (files.length) select(current < files.length ? current : 0, true);
    else $("preview").textContent = "(no files in this package)";
    $("error").style.display = "none";
    renderProperties(pkg);
  }

  function select(index, force) {
    if (!force && index === current) return;
    current = index;
    const file = pkg.files[index];
    $("preview").innerHTML = highlight(file.content || "");
    const items = $("files").children;
    for (let i = 0; i < items.length; i++) {
      items[i].className = i === index ? "selected" : "";
    }
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message.type === "update") render(message.pkg);
    else if (message.type === "invalid") {
      $("error").style.display = "block";
      $("error").textContent = "Not valid JSON: " + message.message;
    }
  });

  $("unpack").addEventListener("click", () => vscode.postMessage({ command: "unpack" }));
  $("upload").addEventListener("click", () => vscode.postMessage({ command: "upload" }));
  wireResizeHandle();
</script>
</body>
</html>`;
}

function randomNonce(): string {
  let text = "";
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}
