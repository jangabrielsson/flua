# 07 · When things go wrong

Something will go wrong. That's not bad luck — it's the normal state of
programming. The difference between people who give up and people with
working smart homes is mostly *how they read the situation*. This chapter
is that skill: the log, the checker, the debugger, and where to ask.

## Read the log

Every QuickApp writes a log, and flua shows it in the terminal. The lamp
already logs with `print(...)` — and every line has a shape worth reading:

```text
[04.10.2026][18:30:00][DEBUG  ][SunsetLamp5000]: Lamp on
```

- `04.10.2026 18:30:00` — *when* it happened (virtual time — remember
  `--start` from chapter 04).
- `DEBUG` — the log **level**, how loud the line is.
- `SunsetLamp5000` — *which* QuickApp said it (name + id).
- `Lamp on` — the message.

There are five levels, in order of loudness:

```text
[TRACE  ]   quiet details, mostly for your future self
[DEBUG  ]   the normal level — print(...) writes here
[WARNING]   "this is odd, but I'll keep going"
[ERROR  ]   "something failed"
```

`print("Lamp on")` is shorthand for `fibaro.debug` with the QA's own tag —
and you can pick a level explicitly: `fibaro.trace`, `fibaro.debug`,
`fibaro.warning`, `fibaro.error`. Most QuickApps live on `debug` and reach
for `warning`/`error` when something genuinely failed. When in doubt, log
*more* — you can delete lines later; you can't read a log you never wrote.

## Read the error

Errors come in two flavors. You've met both:

**At startup** (the file never really ran):

```text
Error:	hello.lua:4: attempt to perform arithmetic on a nil value (global 'nn')
```

flua names the **file**, the **line**, and the problem — here, arithmetic on
`nn`, which doesn't exist. The fix lives on exactly that line. (When the
message says `bootstrap`, it means "while starting your QuickApp".)

**At runtime** (the QuickApp started, then something broke while it was
doing its job). Same shape — file, line, reason — but the QuickApp may keep
running. Watch for the last `[DEBUG]` line before the error: that's the
last thing that *worked*, and usually the best clue.

A minute of disciplined reading beats an hour of guessing: read the line
number, look at that line, read the reason, and only then change something.

## Check before you run: `--check`

flua can check your work **without running it** — syntax, `--%%` typos, and
APIs the HC3 no longer wants:

```bash
flua --check sunset_lamp_ui.lua
```

```text
ok
```

Three useful outcomes:

- `ok` — nothing wrong that a static check can see. Good, but it doesn't
  *run* the code; runtime surprises are still possible.
- A syntax error (try deleting one `end`) — named file and line, exit code
  1. Exactly what a missing `end` looks like, before you waste a run:

  ```text
  lamp.lua: error: syntax: lamp.lua:12: 'end' expected (to close 'function' at line 8) near <eof>
  ```

- A warning, like a misspelled directive (`--%%instnat:true`):

  ```text
  lamp.lua: warning: unknown directive --%%instnat
  ```

  Warnings don't stop anything — a misspelled directive is silently ignored
  at runtime, which is precisely why `--check` exists.

Make `flua --check` a habit before long runs; it catches the cheap mistakes
for free.

## Debug like a grown-up: mobdebug

Logging gets you far. When you need to *watch the code run line by line*,
flua has a debugger, and chapter 01's setup already installed the pieces:
the **Lua MobDebug** extension and the launch configuration
**Flua: Debug Current File (mobdebug)**. Like all the F5 configurations it
runs your QA in the offline playground (`--api local`) — the same code you
were already running.

The flow:

1. Open your QuickApp in VS Code and press `F5` (choose the **mobdebug**
   configuration the first time — it starts flua and waits).
2. Click once in the left margin of a line, next to the line number — a red
   dot appears. That's a **breakpoint**: "pause here".
3. The QuickApp starts and **stops at your dot**. The panel on the left
   shows every variable and its value.
4. Step through the code with the small toolbar (or `F10`), line by line,
   watching `n` count up, `sunsetMin` appear, the `if` decide.

The same launch configuration has a sibling, **Flua: Debug Current File
(UI+mobdebug)** — same debugger, plus the viewer on port 8090, so you can
debug *while clicking* the UI.

If no debugger answers, flua shrugs and runs the QA anyway:

```text
Could not connect to localhost:8172: Connection refused
```

so a stray `--debugger` never hangs you.

## Shrink the problem

The one trick that beats everything else: when something misbehaves, **make
it smaller** until it works, then add pieces back.

- Two hundred lines misbehave? Copy the suspect twenty into a new file.
- A timer never fires? Replace the inside with `print("fired")`.
- A `fibaro.getValue` returns the wrong thing? Print it, and everything
  around it:

  ```lua
  self:debug("sunset hour is", fibaro.getValue(1, "sunsetHour"))
  self:debug("auto is", tostring(self.properties.auto))
  ```

Programmers call this "the smallest case that fails" — and half the time,
the act of shrinking finds the bug before the bug finds you.

## Ask the forum

When you've read the log, checked the file, and shrunk the problem — and
it's still wrong — ask. The Fibaro forum has a flua thread, and the
community of HC3 owners there has seen most of it before.

A question that gets answered includes three things:

1. **What you expected** — "the lamp should turn on after 18:13".
2. **What happened** — the exact log lines or error, copied as text.
3. **The smallest version of the code** — the file (or the suspect part),
   with your real password and address removed.

That's it. You now have the whole loop: write, run, read, fix — and a lamp
that has been on your real HC3 since last chapter. The rest is practice.
