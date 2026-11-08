# flua forum posts

A series promoting flua to the Fibaro forum — developing QuickApps on the
laptop, from the first QA to mocked integrations. One or two posts per day.

**Format:** simple HTML (h2/p/pre/ul), ready to paste into the forum editor.
**Discipline:** every code snippet in a post must be runnable as-is — run it
against the current flua before posting (the snippets are living fixtures).
Keep each post to one topic with a teaser for the next. Prefer the F5
workflow: scenario parameters (clock, mode, seed) live in the QA file as
`--%%` directives, with CLI flags shown as the one-off-experiment override.

## Index

| # | File | Title | Covers (features / examples) | Status |
|---|------|-------|------------------------------|--------|
| 01 | 01-hello-flua.html | Develop QuickApps on your laptop — meet flua | install, first QA, `--ui` viewer, `--tool setup`, F5 | posted 2026-10-08 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298188 |
| 02 | 02-build-the-ui.html | Design your QuickApp UI without the controller | `--%%u` (label/button/slider/switch/select/multi), viewer interactions, updateView, `json.array()` | posted 2026-10-08 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298189 |
| 03 | 03-time-travel.html | Time travel for your timers and scenes | virtual clock: `--%%time:`/`--%%speed`/`--%%instant`/`--%%maxhours` directives + `--start`/`--speed`/`--instant` flags, setTimeout scheduling | posted 2026-10-08 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298193 |
| 04 | 04-debug-with-vscode.html | Debug HC3 Lua in VS Code — breakpoints included | mobdebug launch configs, clock pauses while debugging, `--debugger`, `--check` | posted 2026-10-09 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298196 |
| 05 | 05-the-house-comes-alive.html | Run a whole house: many QAs, one flua | multi-QA runs, find-device-by-name, qa3/qa4, trigger.lua, `--seed` | posted 2026-10-09 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298200 |
| 06 | 06-qa-as-test.html | Let your QA test itself | self-asserting QAs (selfTest.lua), exit codes, quickapp-test skill for agents, `require()` test libs | posted 2026-10-09 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298203 |
| 07 | 07-deploy.html | From laptop to HC3 with one command | `.env`, downloadQA/updateQA/uploadQA/pack/uploadFQA, uploadFile single-file updates + VS Code task, online mode, proxy mode mention | posted 2026-10-10 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298209 |
| 08 | 08-mock-integrations.html | Mock your integrations: HTTP/TCP/UDP/WS servers in Lua | `net.*Server`, mockServer.lua, stateful handlers, require'd mocks | posted 2026-10-10 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298210 |
| 09 | 09-device-catalog.html | The device catalog: 41 device types, one command | `--tool newQA`, type templates + canonical actions, quickAppVariables | posted 2026-10-10 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298212 |
| 10 | 10-multi-file-qas.html | Multi-file QAs: grow your project, keep it organized | `--%%file` + EOH, load order, files API, `require` vs packaged files | posted 2026-10-11 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/#findComment-298213 |
| 11 | 11-refreshstate.html | Listen to the house: the refreshState event flow | RefreshStateSubscriber, event shape, predicates, `/refreshStates` | posted 2026-10-11 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298214 |
| 12 | 12-child-devices.html | Child devices, the HC3 way | QuickAppChild + createChildDevice (basic HC3 API — not QwikAppChild), parentId, removeChildDevice | posted 2026-10-11 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298216 |
| 13 | 13-develop-with-your-agent.html | Develop a QA together with your agent | agent verify loop (exit codes, PASS/FAIL), --tool setup skills + LuaLS types, virtual clock in the loop (--instant, --start), driving the sim over HTTP, net.*Server mocks, require'd test libs | posted 2026-10-12 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298219 |
| 14 | 14-secrets-and-config.html | Keep your secrets out of your QuickApp | `.flua.lua` config file, `.env` chain + `os.getenv`, `--%%var` expressions (tables, nil-unset, faulty-expr errors), package values (`--%%var`,...,"<placeholder>"/`--%%clobber`) vs uploadQA, quickAppVariables round-trip | posted 2026-10-12 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298226 |
| 15 | 15-real-integrations.html | Real integrations: HTTP and MQTT from your QuickApp | `net.HTTPClient` (GET/POST, success/error callbacks, timeout), `mqtt.Client` (events, QoS, echo demo, MQTT_URL override, TLS + `useSNI`), mock→real loop | posted 2026-10-12 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298228 |
| 16 | 16-mcp-for-agents.html | Meet flua-mcp: flua as a tool your agent can call | `flua-mcp` (stdio + Streamable HTTP transports, dual-era protocol), tools (`qa_check`/`qa_run` with summary+filter, `qa_ui`, sessions `qa_start`/`qa_probe`/`qa_action`/`qa_stop`), resources (`flua://docs/*`), prompts (`qa_debug`/`qa_skeleton`), host registration (Claude Desktop, Copilot, remote URL) | posted 2026-10-17 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298277 |
| 17 | 17-modbus-mockserver.html | Mock a Modbus device — develop your Modbus client on the laptop | `examples/Modbus Server/` (SolarEdge SunSpec mock + generic modbus_server.lua, buttons, dual wire-base serving), minimal SunSpec client QA, launch config with two QAs, `-D var:host` override, downloadQA+unpack for existing QAs | posted 2026-10-23 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298367 |
| 18 | 18-test-foreign-qas.html | Test foreign QAs without touching them | `.flua-directives` next to the main file (tester wins over the QA's header), `-D` on top, `os.getenv` expressions, the full precedence chain | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298399 |
| 19 | 19-vscode-extension.html | The flua VS Code extension | marketplace install (`GsonSoft-development.flua`), explorer tool menus, the `.fqa` viewer (metadata + Lua previews), check-on-save; pack/unpack naming (`<QA name>.fqa`, `<name>_main.lua`), identity properties traveling in packages | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298400 |
| 20 | 20-test-suite.html | A test suite for your QuickApps | `require("flua-test")` assertions, `flua test` discovery + per-file timeout, PASS/FAIL/TIME report, exit codes for CI | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298401 |
| 21 | 21-doctor.html | flua doctor — one command says why it doesn't work | nine checks: runtime, venv, HC3 credentials/reachability (secrets never echoed), LuaLS/.vscode setup, extension, flua-mcp; `--no-network`, `--json` | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298403 |
| 22 | 22-record-replay.html | Record & replay the real house | `flua record` (device snapshot + refreshStates feed), `--replay`/`--%%replay` on the virtual timeline, RefreshStateSubscriber reactions, `--speed`/`--instant`, recording doubles as `--seed` | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298404 |
| 23 | 23-audit.html | How much of the HC3 does flua cover? | `flua audit` (routes, device catalog, QA templates — pinned floors), the type hierarchy fallback for unknown device types (`devices/hierarchy.json`) | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298406 |
| 24 | 24-traces.html | Traces your agent can read | `--%%trace`/`--%%syslog` as directives (header/include/.flua-directives), the one-JSON-line-per-event stream, categories, truncation, `/flua/systemLog` + MCP system events | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/2/#findComment-298407 |
| 25 | 25-run-timeline.html | The run timeline: your QA's story, drawn | `/timeline` under `--ui`: one lane per QA (+ a separate timer lane), virtual time on the x-axis, colored marks with stacked-event tooltips, fixed time scale with horizontal scroll, clear-without-recompressing, `--speed`/`--instant` interplay | posted 2026-10-25 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/3/#findComment-298410 |
| 26 | 26-feedback-loop.html | Your feedback loop — now with an issue for it | the feedback issue template + labels, the copy-paste prompt so your coding agent files the report, what happens after (verify → fix with pinning tests → rainy-day parking → response) | posted 2026-10-31 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/4/#findComment-298565 |
| 27 | 27-ui-test-automation.html | Stop clicking — automate your UI tests | the self-asserting UI-interaction pattern (`examples/ui-interaction-test.lua`), the data-driven whole-UI suite (`examples/ui-interaction-suite.lua`), wait-for-async-callback polling, `--strict-tests` + `--result-json` for CI | posted 2026-10-31 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/4/#findComment-298567 |
| 28 | 28-sim-devices.html | Your house, simulated: 30 device types, one call each | `_FLUA.loadSimDevice` (bundled sim devices, pip install included), the uniform fibaro.call drivers (setValue/setUnit/breach/clearBreach/turnOn/…), viewer status panels, `_FLUA.keepAlive()`, the weather simulator QA | posted 2026-11-02 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/4/#findComment-298573 |
| 29 | 29-registered-endpoints.html | Give the simulated HC3 its own REST surface | `api.registerEndpoint` (additive + `override=true`), the mock-panels module/consumer pair, handler-on-the-pump semantics (setTimeout, postRefreshEvent), the alarm-logic override loop, the weather simulator as an endpoint QA | posted 2026-11-02 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/4/#findComment-298574 |
| 30 | 30-helper.html | The FluaHelper: the HC3's local-only API from your QA | `--tool installHelper`, `api.helper` (REST in the controller's local context), `api.helperFibaro` (fibaro.* on the real HC3), transparent variable routing, proxy state that survives restarts | posted 2026-11-04 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/4/#findComment-298599 |
| 31 | 31-proxy-mode.html | Proxy mode deep dive: the QA runs on your laptop, the device lives on the HC3 | `--%%mode:proxy`, the proxy id, state on the controller (restart persistence), actions/UI events routed back, children, the one-event property rule, callback port | posted 2026-11-04 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/4/#findComment-298600 |
| 32 | 32-vscode-extension-evolved.html | Your QA workflow inside VS Code — the extension grew up | the HC3 hub view (filter/sort, actions, hub-newer badge), the freshness-aware cache (View .fqa, offline), Download→edit→Run→Update loop, hub-aware completions (`--tool house`, HT table), switching controllers (`--tool hub` profiles), the CLI-first rule | posted 2026-11-08 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/5/#findComment-298662 |
| 33 | 33-lua-scenes.html | Scenes around your QAs — the glue, tested offline | `--%%scene:true` (COND declarations + marker + actions), device/global-variable/date triggers, the conditions evaluator (filters, anyValue, duration, cron grid, sunrise/sunset), sourceTrigger + manual execute, the three glue directions (scenes calling QAs, QA events triggering scenes, scenes as schedules), self-testing scenes (`examples/scenes.lua`) | post 2026-11-08 https://forum.fibaro.com/topic/80420-flua-the-qa-development-tool/page/5/#findComment-298665 |

Status: draft = written, not verified · ready = snippets run against flua ·
posted = published (fill in the forum link and date).

## Themes used so far (don't repeat as a headline topic)

- install + first run + `--tool setup`
- UI directives + the viewer + updateView
- virtual time (`--%%time`/`speed`/`instant`/`maxhours` directives, CLI flags as override)
- VS Code debugging (mobdebug, launch configs)
- multi-QA runs + find-by-name + refreshState triggers
- self-testing QAs + exit codes + agent skills
- HC3 deploy tools + online/proxy modes
- mock servers (`net.*Server`) + require'd test libs
- device catalog (`--tool newQA`, type templates, quickAppVariables)
- multi-file QAs (`--%%file` vs require, EOH, files API)
- refreshState + RefreshStateSubscriber (event shape, predicates)
- child devices (basic HC3 API: QuickAppChild, createChildDevice)
- agent-driven development (verify loop, --tool setup skills, LuaLS types, mocks for the agent)
- secrets & config (`.flua.lua`, `.env` chain, `--%%var` expressions, quickAppVariables round-trip)
- real integrations (`net.HTTPClient` + `mqtt.Client` against real services, TLS/SNI, mock→real loop)
- flua-mcp (the MCP server: typed tool calls, sessions, docs as resources, prompts; host registration)
- Modbus device mocks (SolarEdge SunSpec mock, generic Modbus server library, dual wire-base serving, multi-QA launch config)
- foreign-QA overrides (`.flua-directives`, `-D`, the precedence chain)
- the VS Code extension (explorer tools, `.fqa` viewer, check-on-save; pack/unpack naming)
- the test runner (`flua-test` + `flua test`)
- `flua doctor` (environment health check)
- record & replay of the real house
- coverage audit + the device type hierarchy fallback
- structured traces (`--%%trace`/`--%%syslog` directives)
- the run timeline (`/timeline` under `--ui`)
- UI test automation (self-asserting UI-interaction pattern, data-driven whole-UI suites, `--strict-tests`)
- simulated devices (`_FLUA.loadSimDevice`, the bundled device set, uniform fibaro.call drivers, `_FLUA.keepAlive()`)
- registered endpoints (`api.registerEndpoint`, additive + override routes, emulation modules and deployed endpoint QAs)
- the VS Code extension as the app layer (hub view + cache + staleness badge, hub-aware completions, `--tool hub` profiles)
- HC3 Lua scenes (`--%%scene:true`, the conditions evaluator, sourceTrigger, self-testing scenes)
- the what's-new summary (0.1.127–0.1.137, the human version of the changelog)

## Ideas for the next series (unclaimed)

- Endpoint packages as .fqa (distributing emulation like any QA) — teased in post 31
- ~~Registered sim endpoints (`api.registerEndpoint`, the weather simulator QA, endpoint packages)~~ → claimed by post 29
- ~~Building an offline house snapshot with `--tool createDB`~~ → claimed by post 22 (record & replay does it better)

## Standalone posts (other threads)

| File | Title | Covers | Status |
|------|-------|--------|--------|
| promotion.html | Developing QuickApps with AI agents — and a tool that makes it fast | the agent pitch: domain knowledge via skills/AGENTS.md + the code→verify loop with flua | ready |
| whats-new.html | What's new in flua — 0.1.127 through 0.1.137 | the human changelog: the VS Code app layer (hub view, cache, completions, hub profiles), proxy-mode UTF-8 and updateView fixes, small fixes, the CI lupa-cache saga | ready |
| compat-notes.html | flua compatibility notes — what changed to match the real HC3 | the QA api layer's 501s, updateProperty ownership, getProperty removal, status-code and name-rule corrections | ready |
| install-macos.html | Installing flua on macOS — Python, pip, VS Code, and the usual bumps | brew/python install, pip install + upgrade/downgrade (version pinning), `which flua`/shebang, launch.json interpreter story, troubleshooting (PATH, PEP 668, lupa wheel, multi-Python) | ready |
| troubleshooting.html | flua troubleshooting — when it doesn't work, start here | `flua doctor`, HC3_URL, HC3 auth lockout, broken upgrades (force-reinstall), proxy firewall (Windows Public profile + macOS), keep-alive, directive typos, the diagnostic loop | ready |

