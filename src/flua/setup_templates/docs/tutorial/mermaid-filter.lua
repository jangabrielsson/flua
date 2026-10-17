-- Pandoc filter for the PDF build: emit mermaid code blocks as raw HTML.
-- Two things matter for mermaid 11:
--   * the element must be a plain <pre class="mermaid"> (NOT <pre><code>…</code>
--     </pre> — mermaid mis-reads the nested code element and reports
--     "Syntax error in text" even for valid diagrams);
--   * the text must be entity-escaped so the browser's textContent hands
--     mermaid the literal <br/>/<i> tags back.

local ESCAPE = { ["<"] = "&lt;", [">"] = "&gt;", ["&"] = "&amp;", ['"'] = "&quot;" }

function CodeBlock(el)
  if el.classes:includes("mermaid") then
    local escaped = el.text:gsub("[<>&\"]", ESCAPE)
---@diagnostic disable-next-line: undefined-global
    return pandoc.RawBlock("html", '<pre class="mermaid">' .. escaped .. "</pre>")
  end
end
