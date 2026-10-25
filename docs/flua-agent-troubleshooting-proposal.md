# Proposal: make flua faster to troubleshoot for agents

- **Author context**: two real debugging sessions on flua 0.1.86 — the
  websocket handshake-segment bug (fixed 0.1.86) and the lupa
  "lost reference" aliasing bug (fixed 0.1.87, see
  `flua-bug-updateView-alias.md`).
- **Goal**: turn the hours of hand-built instrumentation those sessions
  required into first-class flags, tools, and docs.
- **Audience**: AI agents (and humans) debugging flua itself or QA behavior
  in the simulator.

Proposals are ordered by time saved, not by implementation cost. P1 and P2
are the big ones; P3–P5 are cheap and mostly docs.

---

## P1 — Bridge error telemetry: full traceback + automatic payload dump

**Why.** The aliasing bug surfaced as the single line
`Callback error: lost reference` in the QA log. The Python traceback
(lua54.pyx frames + the failing flua call site) was invisible without
patching `bindings.py`. Diagnosis required bisecting the payload by hand and
pickling it for offline replay — several hours of monkey-patching that a
flag would have collapsed into one run.

**Spec.**

- New flag: `--debug:bridge=true` (or `--trace-bridge`), usable via the
  `--%%debug:bridge=true` directive and `flua -D bridge` alike.
- When a lupa/Python exception crosses the Lua bridge inside an `api_call`
  (i.e. the `_PY.api` path) — or any `lua.table_from` conversion — flua
  must:
  1. Log the **full Python traceback** (all frames, not truncated) to the
     normal log and to the `--log json` stream as a structured field
     (`traceback_python`), so the JSON log is machine-parseable.
  2. **Dump the offending payload** to a deterministic file:
     `/tmp/flua-bridge-fail-<unix-ts>.json` (fallback to `.pkl` if the
     payload contains non-JSON types, with a log line stating why).
     The dump happens *before* the exception propagates into Lua.
  3. Print one summary line naming the file and the Lua-visible error:
     `bridge error: lost reference @ GET /devices?parentId=5000, payload dumped to /tmp/flua-bridge-fail-1729890000.json`.

**Where.** The `table_from` call sites in `src/flua/bindings.py`
(`api_call`, `api_hc3`, `device_for`, …). Wrap once behind a helper so all
sites share the behavior.

**Agent value.** Run once → load the dump → ddmin the structure → root
cause. No manual instrumentation, no backups.

**Acceptance criteria.**

- Reproducing the 0.1.86 aliasing bug with `--debug:bridge` produces a
  log containing the full lua54.pyx traceback and a dump file whose
  `table_from(recursive=True)` raises in a fresh `LuaRuntime`.

---

## P2 — Byte-level websocket client trace

**Why.** The handshake bug ("connects, no events") was invisible from
outside: flua's client buffered the `auth_required` frame that arrived in
the same TCP segment as the HTTP 101, then waited for a `recv` that never
came. The QA-side debug channel could not see the client's buffer or frame
boundaries; diagnosis required reading `websocket.py` and building a custom
test server.

**Spec.**

- New flag: `--debug:ws=true`.
- For every client websocket, log:
  - connect/handshake result, bytes received in the connect response;
  - **`buffered N bytes after connect`** when the response contains more
    than the HTTP headers (the exact signal that would have exposed the
    bug in one run);
  - per-frame trace at debug level: direction, opcode, payload length,
    first 32 bytes (hex/ascii) for text/binary; ping/pong pairs;
  - close events with code + reason, and reconnect attempts with backoff.
- Frame bodies over a size threshold get truncated; sensitive data note
  (tokens) — mask `auth`/`token` payload contents in the trace.

**Where.** `src/flua/websocket.py`, gated on the same debug-flag plumbing
as `--debug:http`.

**Acceptance criteria.**

- Running a QA against a server that sends an early frame (the
  `EchoWsServer(initial_frame=…)` fixture added for the 0.1.86 regression
  test) with `--debug:ws` logs the buffered-bytes line and the parsed
  frame without any QA-side code.

---

## P3 — Sim-state introspection tool (`flua --tool state`)

**Why.** "Where did this object get aliased into the store?" required
identity scans over `state.devices` and route replay via undocumented
Python imports (`flua.api.state.SimState`, `flua.api.request.ApiRequest`,
route functions). Agents will keep needing this entry point; it should be a
tool, not folklore.

**Spec.**

- `flua --tool state [--db file.json] [--aliases] [--verify-tree]`:
  - default: dump devices (id, name, type, parentId, key property values)
    and plugin variables as JSON;
  - `--aliases`: walk all state containers and report every object
    reachable from more than one path, printing all paths (the
    `STORE-DUP` output this session hand-rolled);
  - `--verify-tree`: exit non-zero if state contains shared references or
    cycles (see P7); prints the offending paths.
- Document in USAGE.md a short "replay a route in Python" recipe:
  `SimState` + `ApiRequest(segments=[...], query={}, body=...)` + the route
  function, with one worked example.

**Where.** New tool under `src/flua/tools/` (or extend an existing state
tool); docs in USAGE.md.

**Acceptance criteria.**

- Against the 0.1.86 sim state containing the aliased thermostat,
  `--aliases` prints both paths
  (`properties.uiView[1].components[0].options` and
  `view.presetSelector.options`) with no QA running.

---

## P4 — Bridge-error cheatsheet in USAGE.md + flua-troubleshooting skill

**Why.** "lost reference" is opaque: the installed lupa ships no `.pyx`
source, and the root cause required fetching lupa 2.6 from GitHub and
reading `py_to_lua_table`. A mapping from lupa error → likely cause → flua
invariant violated would have pointed at aliasing immediately.

**Spec.**

- New USAGE.md section "Bridge errors" (or a linked troubleshooting doc)
  with a table, minimum rows:

  | lupa error | cause | flua invariant |
  |---|---|---|
  | `lost reference` | payload contains a shared (aliased) or cyclic structure; or a freed/lapsed lupa object crossed the bridge | engine state and bridge data are JSON trees; no lupa proxies in engine data |
  | `cannot mix objects from different Lua runtimes` | object passed between runtimes | one runtime per QA |
  | `TypeError: cannot convert` … | non-plain type reached `table_from` | `lua_to_python` output is plain JSON types |

- Each row links to the relevant fix layer (`_plain_key`/`_plain_value`
  sanitization, `_fresh_copy`, `plugin_update_view` deepcopy).
- Extend the `flua-troubleshooting` skill (`.github/skills/`) with the
  agent loop this session converged on:
  1. enable `--debug:bridge` (P1) and rerun → get traceback + dump;
  2. load the dump in a fresh `LuaRuntime`, minimize (`ddmin`-style) to
     the smallest failing structure;
  3. compare against the cheatsheet table → identify the invariant
     violated;
  4. locate the violating route/state write and fix it; add a regression
     test.
- Add the hygiene note: after instrumenting site-packages, reset with
  `pip install --force-reinstall flua==<version>`; discover the live path
  with `pip show flua`.

**Acceptance criteria.**

- A fresh agent given only "Callback error: lost reference" and the
  troubleshooting skill reaches the P1 dump step without external lupa
  source archaeology.

---

## P5 — Machine-readable bridge errors in `--log json`

**Why.** `--log json` already exists and is the agent-friendliest
interface, but bridge errors arrive as a one-line message with no
structured fields.

**Spec.**

- In JSON log mode, `Callback error` / `Error in bootstrap` lines carry:
  `error_type` (the Python exception class), `error_path`
  (`api_call@/devices?...` or similar), `traceback_python` (full string,
  when available — free if P1 lands), and `dump_file` (when P1 produced
  one).

**Where.** Logging layer for Lua callback errors; ties into P1.

---

## P6 — Runtime tree-invariant check (`--verify-tree`)

**Why.** The aliasing bug would have been self-reporting at write time:
`plugin_update_view` stored one list object into two state paths, and
nothing noticed until `table_from` failed ~20 minutes later in QA terms.
The fix (0.1.87) adds a `copy.deepcopy` at one site, but the class of bug
is "state stopped being a JSON tree" — worth an invariant.

**Spec.**

- Cheap optional check: with a debug flag (or always in offline mode at
  QA end), walk `state.devices`/variables; report objects reachable from
  two paths or cycles with both paths. Identity-scan cost is O(state) and
  sim state is small.
- Wording should point at the write site when possible ("object stored at
  view.presetSelector.options also reachable at
  properties.uiView[1].components[0].options").
- If always-on is too heavy, expose as `flua --tool state --verify-tree`
  (P3) plus a manual `_FLUA.verifyTree()` for in-QA calls.

---

## Suggested rollout

1. **P1** — one helper in `bindings.py`, one flag; highest value per line.
2. **P4** — docs/skill only; makes P1 discoverable and self-serve.
3. **P2** — websocket trace; completes the "network bugs are visible"
   story next to the existing `--debug:http`.
4. **P3/P6** — the state tool and invariant; small, developer-facing.
5. **P5** — rides on P1; do together if touching the logging layer
   anyway.

## Non-goals

- No changes to lupa itself (upstream third-party; the flua invariants are
  the right layer).
- No new public HC3 API surface; everything here is flua-local flags,
  tools, and docs.
- No default-on behavior changes: all tracing/invariants are opt-in
  behind flags or tools, so normal runs stay quiet.
