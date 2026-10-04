# The flua tutorial — QuickApps for the rest of us

You bought a Fibaro HC3 to automate your home. You discovered that the really
good ideas need a *QuickApp* — a small program that lives on the controller.
And you have never programmed anything.

This tutorial is written for you. No programming background is assumed. You
only need to know how to use a computer and be willing to try things.

## What you will build

One project runs through the whole tutorial: **the Sunset Lamp** — a QuickApp
that turns a light on when the sun goes down. Along the way you will:

1. install the two tools you need (VS Code and flua),
2. run your first QuickApp on your own computer,
3. learn what a QuickApp *is* — and click its buttons in a browser,
4. teach the lamp when the sun sets,
5. and finally move it onto your real HC3.

Each chapter ends with a working result. If a chapter feels like it takes
forever, skip to the next one — you can always come back.

## The chapters

- **[01 · Install](01-install.md)** — Python, VS Code, flua, one command to check it all works.
- **[02 · Your first QuickApp](02-your-first-qa.md)** — write 7 lines, run them, see them tick.
- **[03 · QuickApp anatomy](03-qa-anatomy.md)** — onInit, actions, properties — and the Sunset Lamp gets its On/Off buttons.
- **04 · The house comes alive** — timers, sunrise and sunset, virtual time. *(coming next)*
- **05 · Make it yours** — your own UI, variables, rooms and icons. *(coming next)*
- **06 · On the real HC3** — connecting flua to your controller and uploading the lamp. *(coming next)*
- **07 · When things go wrong** — reading the log, debugging, asking the forum. *(coming next)*

## How to read this tutorial

- **Commands** look like this — type them into a terminal, then press Enter:

  ```bash
  flua --version
  ```

  In VS Code, open a terminal with **Terminal → New Terminal** in the menu.

- **Output** shown after a command is what you should actually see on your
  screen (we removed the colors to keep it readable). Don't worry if the
  version numbers differ slightly.

- **Checkpoints** mark the moments that matter:

  > ✅ **You should see** — your name in the log. If you don't, re-read the
  > previous steps; the answer is usually one line above.

- Words in `<angle brackets>` are placeholders — replace them with *your*
  values (your HC3's address, your password, …).

- The examples live in the `examples/` directory of the flua repository and
  are executed by flua's own test suite — the code in this tutorial is the
  same code that is tested with every release, so it always runs.
- The diagrams are drawn with Mermaid. VS Code renders them in the markdown
  preview once you accept the recommended **Markdown Preview Mermaid**
extension (it's in the `.vscode/extensions.json` that `--tool setup`
  installs); on GitHub they render on the page automatically.

One promise before we start: **you will not need to understand everything.**
QuickApps are small. The whole trick is a handful of ideas — this tutorial
introduces them one at a time, exactly when the lamp needs them.
