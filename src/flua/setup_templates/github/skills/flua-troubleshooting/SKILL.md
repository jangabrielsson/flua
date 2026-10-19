---
name: flua-troubleshooting
description: Common flua runtime errors and how to fix them: "online mode requires HC3_URL", HC3 authentication lockout, proxy callbacks not reaching the emulator, busy ports, unknown --%% directive warnings, unknown device types (and the catalog), virtual-time and keep-alive surprises, debugger notes, and the machine-readable log surface (--log json, --syslog, /flua/systemLog, /debugMessages, flua-mcp). USE FOR: diagnosing flua startup errors, HC3 connection failures, proxy mode issues, Lua runtime errors, cross-platform remedies for macOS and Windows.
---

# flua Troubleshooting

---

## "online mode requires HC3_URL"

**Error:**

```
flua: error: online mode requires HC3_URL (or HC3_HOST) in the environment — run with --api local or --%%mode:offline for the simulated HC3
```

**Cause:** the QA (or run) is forced ONLINE — `--api remote`, or
`--%%mode:online`/`--%%mode:proxy` in the QA header — but the environment
chain (local `.env` > `~/.env` > shell) has no `HC3_URL`/`HC3_HOST`.

**Fix:**
- Add the credentials to your `.env` (see flua-setup), or
- run offline explicitly: `--api local`, `--%%mode:offline` in the QA
  header, or a `--%%mode:offline` default in a `.directives` file.

Offline is always the default; online is opt-in (`--api remote`, or
`--%%mode:online|proxy` on the main QA).

## HC3 authentication lockout

flua never retries a 401/403: the HC3 locks itself after 4 failed
credential attempts, so a wrong password aborts the run immediately with
`HC3 authentication failed ... flua exits immediately`. Fix the
`HC3_USER`/`HC3_PASSWORD` in the environment and re-run — you spent exactly
one attempt.

## Proxy callbacks never reach the emulator

Symptom: the QA runs in proxy mode (`--%%mode:proxy`) and the proxy device
exists on the HC3, but tapping the UI does nothing.

**Cause:** the HC3 cannot reach the emulator's callback server. The proxy
posts actions/UI events to `http://<your-ip>:<port>/api/...`.

**Fix:**
- The machine and the HC3 must be on the same network.
- Your firewall must allow the HC3 to reach the port (default 8080;
  override with `FLUA_PROXY_PORT` in the `.env` chain).
- A busy port silently falls back to the next free one — the startup log
  announces the effective ip:port.
- Restarting the emulator re-CONNECTs the proxy to the current ip:port.

## "--%%mode:proxy needs online mode — proxy disabled"

Running a proxy QA without HC3 credentials: flua logs the warning and runs
the QA offline as usual. Set `HC3_URL`/credentials, or drop the directive.

## Busy ports

The `--ui` server and the proxy callback server both fall back to the next
free port (up to 10 attempts) instead of failing — the startup log
announces the effective port.

## unknown --%% directive warnings

```
WARNING flua.config: unknown --%% directive: --%%instnat:true
```

A typo'd directive is parsed anyway (usually with the wrong type) and
warned about at runtime; `flua --check` reports it with the file context.
Fix the spelling.

## "unknown device type" — and where the catalog lives

```
flua: error: unknown device type: 'com.fibaro.light' — did you mean
'com.fibaro.lightSensor', ... (all supported types: flua --tool catalog)
```

A wrong `--%%type` fails QA startup. The error names close matches
(typos) and points at `flua --tool catalog`, which lists every type the
sim supports (`--json` for a JSON array). The full catalog is
`src/flua/devices/devices.json` (176 captures).

## The machine-readable surface (agents and debugging)

- `--log json` — one JSON object per QA log line
  (`{time, level, tag, qaid, msg}`); `--logfile FILE` — a copy of the log
  (ANSI stripped); `--syslog FILE` — structured system events
  (run_start, qa_load, qa_error, crash, ...) as JSON lines.
- `GET /flua/systemLog?last=N` — the same system events over REST
  (flua-only); `GET /debugMessages?last=N` — the QA console buffer.
- `flua --check --json` — static findings as one JSON document.
- The `flua-mcp` server wraps all of this as typed tools (`qa_check`,
  `qa_run` with `summary`/`filter`, `qa_probe` with cursor deltas,
  `docs_read` for the docs) — `docs/mcp.md` is the reference.

## A faulty --%%var is a startup error

`--%%var:name=expr` values are evaluated as Lua expressions — a syntax
error or indexing a nil key fails the QA startup and names the variable:

```
error in --%%var:name: <expr> — <reason>
```

An expression that merely evaluates to nil leaves the variable unset.

## The run exits immediately (online)

Online runs exit when no timers, messages, or connections are pending — a
QA that must keep waiting for HC3 events opts in with `--%%keep-alive:true`
(proxy QAs imply it). A drained offline run also exits; use `--run-for 0`
or `--ui` to stay alive.

## Virtual time surprises

`--speed`/`--instant` accelerate the VIRTUAL clock (`os.time()`, timers).
`--run-for` counts virtual seconds. Real-world waits (HTTP, debugger) still
take wall time.

## The debugger freezes time

While mobdebug is paused at a breakpoint, its blocking socket receive
freezes the event loop — virtual time stands still until you resume. This
is by design.

**Attached runs stay fast:** flua's mobdebug uses line hooks only while
stepping or when breakpoints exist — a plain attached run (F5 without
breakpoints, or ^F5) tracks call events only, so hot numeric loops run at
full speed. A set breakpoint re-enables line hooks everywhere, which is
what makes hot loops slow while actively debugging.

**What does VS Code pass flua?** Add `-v` to the launch config's `args`:
flua then logs its full argv and `MOBDEBUG_PORT` — the quickest way to see
whether F5/^F5 attach a debugger, inject a mobdebug bootstrap, or run
plain.

## Windows/macOS notes

- macOS may prompt for firewall permission when the proxy callback server
  (0.0.0.0) starts — allow it for proxy mode to work.
- `.env` files use plain `KEY=value` lines and are re-read when changed.

## Still stuck?

`--%%debug:refreshState=true,api=true,http=true` (with `--%%loglength`)
logs events and calls in a short form — usually the fastest way to see
what the emulator sees. Then: `flua --check` (or `--check --json`) for
static issues, the QA's own `self:debug(...)` lines, `--log json` for a
structured log, and `/flua/systemLog` + `/debugMessages` for the engine's
side of the story.
