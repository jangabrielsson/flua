# 01 · Install

In this chapter you install the two tools you will use from now on, and you
run one command that proves everything works. Ten to twenty minutes, no
programming.

## What you are installing

- **Python** — the engine flua runs on. Your computer may already have it.
- **Visual Studio Code (VS Code)** — a free editor where you write QuickApps.
- **flua** — the program that *runs* QuickApps on your computer, pretending
  to be your HC3 so you can try everything safely before touching the real
  thing.

> flua never changes anything on your HC3 until you explicitly tell it to
> (in a later chapter). Everything in the first chapters happens entirely on
> your own computer.

## Step 1 — Python

Open a terminal and check:

```bash
python3 --version
```

You want **3.11 or newer**. If you see an error or an older version, install
the latest Python from [python.org](https://www.python.org/downloads/)
(Windows: tick *"Add Python to PATH"* in the installer).

> ✅ **You should see** something like `Python 3.13.2`.

## Step 2 — VS Code

Download and install **Visual Studio Code** from
[code.visualstudio.com](https://code.visualstudio.com/).

## Step 3 — flua

In the terminal:

```bash
python3 -m pip install fibaro-flua
```

(On Windows this is usually `py -3 -m pip install fibaro-flua`.)

Check that it works:

```bash
flua --version
```

> ✅ **You should see** `flua 0.1.12` (or newer).

If the `flua` command is not found, it still works as a Python module —
every `flua` command in this tutorial can also be written `python3 -m flua`.

## Step 4 — the smoke test

One line, to prove the whole machine runs:

```bash
flua --api local -e 'print("Hello HC3!")'
```

```text
🚀 flua 0.1.12 (Lua 5.5, Python 3.14.3), mode offline
[04.10.2026][20:11:43][DEBUG  ][QA50005000]: Hello HC3!
```

Let's unpack the two lines, because you will type them a lot:

- `--api local` means *"run on my computer, not on my HC3"* — the safe mode
  for experiments.
- `-e 'print(...)'` is flua's one-liner: run this tiny program and exit.

`Hello HC3!` is your first QuickApp talking. That's the entire loop you will
use from now on: write, run, look, adjust.

> ✅ **You should see** `Hello HC3!` in your terminal.

## Step 5 — a project folder with everything set up

flua can prepare a project folder with all the VS Code settings you need
(run buttons, a debugger setup, language help):

```bash
flua --tool setup my-first-qa
```

```text
  wrote .vscode/launch.json
  wrote .vscode/extensions.json
  wrote .luarc.json
  wrote AGENTS.md
  wrote .github/skills
  wrote viewer/index.html
done — VS Code will suggest the Python and Lua MobDebug extensions on the next open; open viewer/index.html while `flua --ui` runs to see your QAs' UI
Read on:
  USAGE.md   https://github.com/jangabrielsson/flua/blob/main/USAGE.md
  Tutorial   https://github.com/jangabrielsson/flua/tree/main/docs/tutorial
```

Notice the last file: `viewer/index.html` — a small page that shows your
QuickApp's buttons and switches while it runs. You'll meet it in chapter 03
(where flua serves it for you — the copied file is for opening it by hand,
or from another computer).
The two links at the end open in the browser with a cmd/ctrl-click — the
`USAGE.md` manual for when you wonder "can flua do X", and this tutorial.

Now open the folder in VS Code — **File → Open Folder… → `my-first-qa`**.
A popup asks you to install the recommended extensions (**Python**,
**Lua MobDebug**, **Lua Language Server**) — accept. They give you syntax
coloring, error squiggles, and later a debugger.

## Step 6 (optional but smart) — your HC3's address

In a later chapter you will upload the lamp to your real HC3. flua finds it
through a small settings file, and setting it up now takes one minute.

In your project folder, create a file named `.env` (in VS Code:
**File → New File… → `.env`**):

```bash
HC3_URL=http://192.168.1.10/
HC3_USER=admin
HC3_PASSWORD=your-hc3-password
```

The address is the one you use to open your HC3 in a browser — the same
`admin` user and password. This file stays on your computer; flua reads it
and sends the credentials only to your own HC3.

(If you prefer not to, skip it — the next chapters run entirely on your
computer and don't need it.)

## You're set

Everything is installed. Next: your first QuickApp — seven lines that tick.
