# 02 · Your first QuickApp

In this chapter you write a real QuickApp — a dozen lines — and run it.
It will count to three, tell you it's done, and stop. You don't need to
understand every line yet; chapter 03 explains them. Right now the goal is
simpler: **write, press F5, see it live.**

## Step 1 — create the file

In VS Code, open your project folder (`my-first-qa` from chapter 01) and
create a new file: **File → New File…**, name it `hello.lua`, and type:

```lua
--%%name:hello
print("Hello from my first QuickApp")

local n = 0
setInterval(function()
  n = n + 1
  print("tick", n)
  if n >= 3 then
    print("done")
    os.exit()
  end
end, 400)
```

A few first impressions, without the theory:

- Lines starting with `--` are *comments* — notes for humans. The two
  `--%%` lines at the top are the exception: those are notes for **flua**
  (`--%%name:hello` gives the QuickApp a name).
- `print(...)` writes a line to the log.
- `setInterval(function() … end, 400)` means: *run this little block every
  400 milliseconds.* That's a **timer** — the heart of every QuickApp.
- The `if` counts to three: after the third tick the QuickApp says `done`
  and `os.exit()` ends it — and stops its timer with it.

> `os.exit()` ends the QuickApp that called it. That's the same name real
> HC3 QuickApps use (there, every QuickApp is its own program — ending it
> is as simple as leaving a room). In these first experiments it's also
> what lets flua finish and hand you back the terminal — a QuickApp that
> never exits just keeps running.

## Step 2 — run it with F5

Make sure `hello.lua` is the tab you're looking at, and press **F5** (the
first time, choose **Flua: Run Current File (Terminal)** from the menu —
chapter 01's setup installed it). VS Code runs the file and shows the log
in its terminal panel:

```text
🚀 flua 0.1.12 (Lua 5.5, Python 3.14.3), mode offline
[04.10.2026][20:50:10][DEBUG  ][hello5000]: Hello from my first QuickApp
[04.10.2026][20:50:10][DEBUG  ][hello5000]: tick 1
[04.10.2026][20:50:11][DEBUG  ][hello5000]: tick 2
[04.10.2026][20:50:11][DEBUG  ][hello5000]: tick 3
[04.10.2026][20:50:11][DEBUG  ][hello5000]: done
```

> ✅ **You should see** your QuickApp say hello, tick three times, and stop.

That's a complete QuickApp, running. The `hello5000` at the start of each
line is the QuickApp's *tag* — its name and its id. The `5000` is the id
flua assigned it; on your real HC3 it would get the controller's next free
id.

**What did F5 do?** The launch configuration ran `flua --api local
hello.lua` for you — the same command you used for the smoke test in
chapter 01. `--api local` is the important part: it tells flua to pretend
to be an HC3 **on your computer**. It gave your QuickApp a home, started
it, kept time for it, and stopped when the program ended. Your real HC3
was never involved — that's the whole point: experiment safely, then go
live later.

> If F5 complains that `flua` was not found: VS Code on some systems
> doesn't inherit the shell's PATH when started from the dock. Restart it
> from the terminal once — on macOS run `open -a "Visual Studio Code"` in a
> terminal, on Windows/Linux start `code` from one — and F5 will find flua.
> If it says *No module named 'flua'* instead, VS Code is using a Python
> that doesn't have flua: open the Command Palette (Ctrl/Cmd+Shift+P),
> choose **Python: Select Interpreter**, and pick the one you installed
> flua into (chapter 01). You can always run the command by hand instead:
> open a terminal with **Terminal → New Terminal** and type
> `flua --api local hello.lua` — every F5 run in this tutorial is exactly
> that command.

## Step 3 — break it, on purpose

Programmers don't get code right the first time. They get it *wrong fast*
and let the computer tell them where. Try it: change `local n = 0` to
`local n = 0 + nn` (a name that doesn't exist), save, and press **F5**
again:

```text
Error:	hello.lua:4: attempt to perform arithmetic on a nil value (global 'nn')
```

flua tells you the file, the line (4), and the problem: it tried to do
arithmetic on `nn`, which is nothing. ("Bootstrap" is flua-speak for
"while starting your QuickApp" — mistakes at startup show up like this,
mistakes later show up while the QuickApp is running.)

Change `0 + nn` back to `0`, save, F5. **The loop from now on is exactly
this: change one thing, save, F5, read the log.**

> QuickApp files run again every time from scratch — there is no hidden
> state between runs. That makes experiments safe: nothing you break
> survives the next run.

## Step 4 — faster tinkering: watch mode

For a really fast loop, flua can watch your file and restart it on every
save — no F5 needed. This one is a terminal command (it has extra flags):

```bash
flua --api local --watch hello.lua
```

Now edit something — change `"Hello from my first QuickApp"` to
`"Good evening, HC3"` — and save. The log shows the QuickApp starting over
with the new text. Press `Ctrl-C` in the terminal to stop watching.

## The two-line takeaway

- A QuickApp is a small program that **runs on its own**, wakes up on
  **timers**, and writes to a **log**.
- You develop it **on your computer** (`--api local` — the F5 configs do
  this for you) and only later move it to the HC3.

Next chapter: what a QuickApp *is* — and the Sunset Lamp gets its switch.
