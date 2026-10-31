<!--
MIT License
Copyright (c) 2026 Joachim Brørs Sommerfeld

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-->

# Experience using flua to test and debug Fibaro QuickApps

Prepared 31.10.26 for upstream feedback, from an AI coding agent's perspective.

**My assessment:** flua made useful, repeatable testing of substantial QuickApps possible without deploying them to an HC3. It helped expose a real application defect, exercise UI callbacks and asynchronous cleanup, and test hours of scheduled behavior quickly. The main cost was preparing a trustworthy harness and deciding whether a failure belonged to the QA, the emulator, or the test's timing assumptions.

This report reconstructs the work from saved tests, logs and results, primarily for `000.Plua Template`, with supporting examples from KNX QuickApps. It distinguishes those historical runs from checks made while writing this report. The complete QA suites were **not rerun** for this report. No HC3 access or deployment was performed to prepare it.

The environment was Windows/PowerShell, a separate `.venv-flua`, Python 3.13.6, lupa 2.6 and an engine reporting Lua 5.4. We also used separate Lua 5.3 unit tests for HC3 compatibility. Those unit tests are not flua assertions.

| Evidence | Version and result | Qualification |
|---|---|---|
| Original template pilot, 25.10.26 | flua 0.1.84; adapted controls 100/100, long timers 13/13 | Raw controls were 98/100; backup validation found three failures; full-template restart failed. |
| Template corrections, 28–29.10.26 | Logs still identify 0.1.84; final regression set: 139 flua assertions and 73 separate Lua 5.3 tests passed | Controls retained a response adapter; full restart was not retested. |
| KNX scenarios, 28.10.26 | 0.1.84 baselines: ISE health 104, ISE reads 59, gateway reads 52, logger 30 passing assertions | Synthetic KNX responses and blocked external calls. |
| Upgrade verification, 29.10.26 | 0.1.104 MCP handshake, documentation access and 17/17 async assertions passed | A targeted check, not a repeat of all earlier suites. |
| Initial report checks, 31.10.26 | `.venv-flua` CLI reports 0.1.104 / Lua 5.4 / Python 3.13.6; property-route behavior checked directly | Package/docs inspection and an in-process Python route probe; no full QA run. |
| Credential follow-up, 31.10.26 | A second installation in `.venv` reports flua 0.1.111 / Lua 5.4 / Python 3.14.2 and supports `svar` | Parser and packaging-helper checks with dummy values; VS Code's configured `flua.executable` still points to `.venv-flua` 0.1.104. |

Sources: [template pilot and follow-up report](tests/flua_template/README.md), [template regression results](.validation/template-async-20261029/results.json), [ISE](tests/flua_ise/README.md), [gateway](tests/flua_gateway/README.md), [logger](tests/flua_knx_log/README.md), [upgrade verification](.validation/flua-update-20261029/mcp-verification.json). These are local evidence links; the descriptions and figures here are intended to remain understandable when this document is shared alone.

**1. The best result was finding an actual QA defect.**

The original backup tests showed that the template accepted a backup belonging to another UUID, accepted an unsupported schema, and restored keys outside its configured allowlist. The scenario returned six passes and three failures. Repeating the negative cases with a normal clock reproduced them, which helped separate application behavior from accelerated-time artifacts.

After the template was corrected locally, the same scenario passed all nine assertions. A separate set of 26 Lua 5.3 unit tests covered additional failure paths, including unavailable reads, local-value precedence and rollback. This is the strongest evidence of flua's value: it supported a failing-test → targeted fix → regression-test workflow for code that stores user settings.

Upstream should retain and promote this style of example: a realistic negative test against an existing multi-file QA, with a clear before/after result. A small self-testing lamp is useful for learning, but a persistence failure example demonstrates why the tool matters.

**2. Testing UI behavior and event handling was practical.**

We exercised real QA callbacks, short/cancelled/completed holds, enable/disable transitions, Show Details output, backup switching, managed timer cleanup and 40-to-1 render coalescing. MCP action/probe tools made it possible to inspect simulated properties, updated view data and logs without using a browser for every assertion.

The passive KNX logger was another good example. Its 30-assertion scenario included a burst of events and 10,000 events while paused. It verified that collection remained bounded, the displayed log stayed frozen during pause, and resuming showed the collected data. This gave much better evidence than simply observing that `onInit` completed.

These checks verified simulated state and rendered text. They did not establish physical HC3/mobile layout, physical KNX telegram exchange or notification delivery.

**3. Virtual time and machine-readable results substantially improved the workflow.**

At speed 1800, the template's long-timer scenario covered details auto-hide, daily backup and 24-hour debug expiry without waiting a day. ISE scenarios similarly exercised heartbeat cycles, missed responses, recovery and duplicate-alert suppression.

The combination of `flua-test`, process exit codes, JSON logs and MCP summaries was well suited to an agent. Filtered logs reduced noise while summary counts still described the complete run. Bundled documentation available through `docs_list` / `docs_read` also helped: the agent could consult the installed tool's documentation directly.

These are existing strengths worth keeping. The remaining improvement is making the appropriate clock and the meaning of the final verdict equally easy to discover.

**4. Existing PLua projects needed more preparation than a simple run command suggested.**

All 16 companion includes in the original template failed static checking because its `--%%file` paths were workspace-relative, while flua resolved them relative to the main file. The resulting path effectively repeated the QA directory. Other project checks also needed to account for PLua library aliases and unsupported directives such as `project` and `desktop`.

We generated wrappers that resolved includes explicitly, selected offline mode, installed test hooks and recorded source hashes. Production files stayed unchanged during the pilot. That was workable, but it required project-specific Python/Lua glue before behavioral debugging could begin.

**Suggested improvement:** make a failed include diagnostic show the declared path, the base directory, the resolved path and a likely migration remedy. Document a first-class “test an existing PLua project without rewriting it” recipe, including aliases, companion load order and unsupported-but-harmless directives. The installed package already has migration tooling; this request is for a clear non-destructive testing workflow and better diagnostics, not a claim that migration support is absent.

Evidence: [wrapper builder](tests/flua_template/build.py) and [cross-QA smoke harness](.validation/m10-f2-20261029/run_flua.py).

**5. A property-response mismatch caused misleading application failures.**

In the original pilot, `GET /devices/5000/properties/useUiView` returned bare `false` with status 200. The template expected an object containing `value`, consistent with the HC3 contract recorded in this workspace. It therefore left its detected view as `unknown`. Two control assertions failed.

A narrowly scoped test adapter wrapped successful scalar property responses as `{value=...}`. The controls then passed 100/100. That result is conditional on the adapter; it is not proof of unmodified flua compatibility. The adapter remained in the later template runs.

While preparing this report, I directly invoked the installed 0.1.104 Python `device_property_get` route with a synthetic device. It still returned the supplied property itself, rather than an envelope:

| Supplied property | Returned data | HTTP status |
|---|---|---|
| `false` | `false` | 200 |
| `true` | `true` | 200 |
| `0` | `0` | 200 |
| `""` | `""` | 200 |
| `{"nested":false}` | `{"nested":false}` | 200 |

This was an in-process route check, not an end-to-end Lua/API or fresh physical HC3 comparison. The implementation is `flua/api/routes/devices.py`, function `device_property_get`.

**Suggested improvement:** verify and pin this endpoint against an HC3 capture, including `false`, zero, empty strings, object values and missing properties. If different calling surfaces intentionally have different response shapes, document them explicitly. Do not make users weaken valid QA-side response validation to accommodate a simulator mismatch.

**6. Clock selection sometimes looked like an application bug.**

Instant mode produced bunched callbacks and ordering failures in the template tests. Normal-speed controls passed, and paced long-timer runs passed with suitable observation margins. UI-event injection is asynchronous: asserting immediately after dispatch can observe the old state.

In an ISE run at 60× speed, only 14 of 18 startup reads had completed at a 25-second virtual checkpoint. The recorded diagnosis was Windows timer granularity. Widening the test checkpoint to 60 virtual seconds resolved it, and an independent normal-speed run confirmed completion at 19 seconds. We preserved production's one-second pacing.

The installed package now documents `--step` and exposes `step` through MCP `qa_run`. Its `quickapp-test` skill already explains why instant mode is unsuitable for some clock-dependent logic. We did not validate step mode against these historical scenarios.

**Suggested improvement:** put the same clock-selection guidance in every quick-start and agent entry point. Show when to use normal time, paced acceleration, step mode and instant mode; include one asynchronous UI example and a bounded “wait until condition” example. Existing timer traces should be the next diagnostic step when timing assumptions fail.

**7. Full-template restart exposed a difficult historical failure.**

On 0.1.84, restarting the full template failed before its second `onInit`, with `Error in bootstrap: lost reference` and `init.lua:1240` in the traceback. It also reproduced through MCP session/action/probe calls on a smoke wrapper without test assertions. A minimal restart QA passed and retained storage.

An EventLib reload message appeared nearby, but that does not identify EventLib as the cause. The full restart was not retested in the later template corrections. Factory Reset's seven passing assertions stopped at an intercepted restart request, so they do not prove post-reset startup.

The installed documentation includes a separate `updateView` aliasing / `lost reference` report and describes a fix in 0.1.87. That is a useful investigation lead, not evidence that our template failure had the same cause or is fixed in 0.1.104.

**Suggested next step:** rerun a preserved full-template reproduction on the current engine, then reduce companion libraries and state only if it still fails. Use the bridge diagnostics already shipped. A regression should verify actual second startup and retained storage, rather than replacing restart with a mock or invoking `onInit` on the same object.

Historical evidence: [original results](tests/flua_template/results.json), key `lifecycle_full`, and the minimal-restart result described in the [pilot report](tests/flua_template/README.md).

**8. Assertion counts alone were not a sufficient run verdict.**

The historical lifecycle failure had exit code 1, but its assertion summary had zero failed assertions: startup failed before the suite could finish. The bootstrap error appeared at INFO level. An agent filtering only ERROR logs, or checking only `summary.failures == 0`, could reach the wrong conclusion.

We learned to read exit status, bootstrap/runtime messages, assertion totals, completion and any time limit together. A successful `qa_start` response means that a session was created; it does not establish that initialization or the intended scenario succeeded.

**Suggested improvement:** expose a normalized outcome such as `passed`, `assertion_failed`, `runtime_error`, `timeout` or `incomplete`, alongside an explicit suite-completed marker. Preserve assertion totals as separate data. Include runtime errors in the default failure-focused output regardless of the original log level. A regression for “bootstrap failure before `finish()`” would protect this behavior.

**9. Documentation and skill consistency need attention.**

Several useful capabilities already exist, including step mode, structured traces, bridge diagnostics, `doctor --no-network`, migration tooling, record/replay, mock servers and `flua test`. We should use and improve discovery of these before asking upstream to build duplicates. Their presence in the installed package is not a claim that we exercised all of them.

However, the installed 0.1.104 setup templates and the corresponding workspace copies contain conflicting instructions. File hashes matched for the setup, troubleshooting and test skills and the QuickApp instruction sheet, so the following examples are not solely an old local-copy problem:

| Document | Problem | Requested correction |
|---|---|---|
| `flua-setup/SKILL.md` | Says ONLINE is the default in one section, then correctly says offline in another | State the same default throughout, and use explicit local mode in offline examples. |
| `quickapp-dev.instructions.md` | Its mode example says `online (default)` | Correct it to match the current engine. |
| `flua-setup/SKILL.md` | Describes generated LuaLS configuration as Lua 5.5, while this installation reports Lua 5.4 | Align editor guidance with the intended runtime; tell the agent to record `--version --machine` and distinguish the emulator from the target HC3 language baseline. |
| Quick reference versus `quickapp-test` | The short reference leads with instant mode without the longer skill's caveat | Put a brief clock-selection rule beside the first accelerated-time command. |
| `flua-troubleshooting/SKILL.md` | Recommends the retired `.directives` file | Explain the current `--%%include` and `.flua-directives` mechanisms and their different purposes. |
| `flua-troubleshooting/SKILL.md` | Uses `pip show flua` when the installed distribution is `fibaro-flua` | Use the selected interpreter with `python -m pip show fibaro-flua`; apply the correct distribution name to reinstall instructions too. |

Automated consistency checks between canonical docs, generated skills and quick references would help prevent these contradictions from being copied into new projects.

There is also **local documentation debt**: our flua guide and root routing text still describe an uninstalled pilot, and some guide paths moved under `A.Main/`. Those are our workspace's maintenance issues, not flua runtime bugs.

The initial Windows MCP setup hit a Unicode decoding error in the verification subprocess. Running the venv interpreter with `-X utf8` resolved that setup issue. Windows examples should demonstrate interpreter selection, UTF-8 handling and checking CLI/MCP versions. This does not establish a current flua server encoding defect.

**10. The missing skill is an integrated debugging workflow for an existing QA.**

We had individual recipes for tests, migration and troubleshooting, but still had to assemble the practical sequence ourselves. The most helpful addition would be a vendor-neutral skill or worked example that guides an agent through:

- Recording engine, Python and Lua versions and resolving the complete companion-file graph.
- Running existing production source through an isolated test wrapper, with every adaptation disclosed.
- Seeding devices and controlling external events without accidentally exercising real integrations.
- Choosing a clock, waiting for asynchronous effects and checking explicit suite completion.
- Separating an application defect, a simulator contract mismatch and an invalid test assumption.
- Testing restart as a distinct boundary, then producing a small reproduction and a shareable evidence bundle.

For request and lifecycle testing, examples should include lost, late and duplicate callbacks, callbacks delivered after cancellation, and replacement of an in-flight operation. We used custom doubles to exercise those cases. An unreachable port or simple echo server does not cover all of them.

The installed tools already supply much of the machinery. The request is to connect them into a reliable path an agent can follow without discovering each piece independently.

**11. Offline mode and a network-isolated test are different guarantees.**

We explicitly selected the local simulator and separately replaced outgoing HTTP calls. Other harnesses intercepted KNX/device actions and blocked UDP. One async scenario deliberately attempted an HTTP request and verified that the wrapper blocked it.

Those guards were important because selecting a simulated HC3 is not, by itself, evidence that every `net.*` path is contained. Our HTTP wrapper also was not a universal network sandbox.

**Suggested improvement:** make the effective HC3 mode and outbound-network policy visible together in the test workflow. Provide a documented strict test configuration, or a reusable guard, that denies unexpected traffic and reports attempted destinations without exposing credentials. Make unexpected requests fail tests unless they are explicitly part of the scenario.

This would reduce custom harness code and make the meaning of “offline test passed” more precise.

**12. Evidence packaging and small local changes would make the next run easier.**

Source hashes helped us distinguish the original 17-file template pilot from the later 18-file version with its Requests companion. Preserved logs also prevented us from incorrectly assigning all tests dated 29.10.26 to the newer flua version installed that day.

An upstream report/export recipe should collect versions, source hashes, command/MCP arguments, clock settings, fixtures, adapters, exit status, suite completion and trace locations. It should redact credentials and make omitted integration coverage explicit. This could build on existing diagnostics rather than introducing another independent framework.

For this workspace, I suggest two small additions; neither was applied while writing this report:

- **Root `AGENTS.md`, Working style, immediately after local PLUA validation:** “For flua validation, record the installed runtime version, use explicit local mode, and isolate external network calls. Keep test wrappers and response adapters separate from production source. Choose clock mode from the installed `quickapp-test` guidance. A pass requires a successful process outcome and completed assertions; list adapters and unverified hardware behavior.” Also replace the flua routing bullet's “not installed yet” wording and point it to `A.Main/Flua/agents_flua.md`.
- **`000.Plua Template/README.md`, beside its testing guidance:** add: “For offline regression testing, follow `tests/flua_template/README.md` and generate wrappers with `tests/flua_template/build.py` into a new evidence directory after intentional source changes. Preserve earlier manifests. Record mocks and adapters, require an explicit completed-suite verdict, and test actual restart separately from same-object `onInit` re-entry. Reuse the template's managed-timer and request-guard helpers when adding asynchronous behavior.”

**13. Adopt `--%%svar` for credential variables where the toolchain supports it.**

Following the user's requested convention, use secret-variable declarations for passwords, tokens, API keys and credentials such as these:

```lua
--%%svar:hc3_user=""
--%%svar:hc3_password=""
```

This is an existing feature in the separately installed flua 0.1.111, not a missing feature request. It creates QuickApp-variable entries with `type="password"`; the bundled documentation describes masking in the HC3 web variable editor. QA code still reads the value through `self:getVariable(...)`, and API access can still expose it. The directive does not encrypt credentials or automatically remove them from logs, backups or packages.

Keep source defaults empty and supply actual credentials through private local configuration. If a local `.flua-directives` file overrides a secret variable, it must also use `svar`: a same-named `svar` takes precedence over `var`, so leaving the existing plain-`var` override can cause the blank secret default to win. For this workspace's existing configuration pattern, the matching declarations would be:

```lua
--%%svar:hc3_user=config.hc3_177 and config.hc3_177.user or "",""
--%%svar:hc3_password=config.hc3_177 and config.hc3_177.password or "",""
```

The final `,""` explicitly requests a blank distribution value. `svar` alone is not a promise that a shared FQA contains no credentials: without a package value, the evaluated value can be exported. Verify both `initialProperties.quickAppVariables` and the embedded source in generated packages. Personal uploads use the evaluated value, so distribution blanks are not a substitute for deployment authorization.

**Compatibility matters here.** Source inspection found support in `.venv` flua 0.1.111, but not in `.venv-flua` flua 0.1.104 or the inspected PLua 1.3.14/1.3.16 parsers. Those PLua versions ignore the unknown directive. Replacing `var` with `svar` in a PLua-packaged QA could therefore omit its variables. The current VS Code setting and PLua deploy tasks have not been switched, and production QA declarations and local credential overrides were not migrated for this report. Avoid adding duplicate `var`/`svar` declarations to hide that incompatibility.

A local check of 0.1.111's parser accepted the exact two empty declarations above. A separate call to its packaging helper with dummy credentials and blank package values produced two `password`-typed entries with blank values and removed the dummy literals from embedded source. This was a parser/helper check without the QA engine or network, not fresh HC3 editor verification.

**Suggested upstream improvement:** make this feature prominent in credential examples and migration checks, including its minimum supported release, matching override directives, package-value behavior and UI-masking limits. A capability/version check should identify which executable the CLI, editor and MCP actually use; this workspace's two flua installations demonstrate why checking only one can be misleading.

**Suggested root `AGENTS.md` addition**, under Working style beside the credential-handling rules, not applied:

> Use `--%%svar` for password, token, API-key and credential QuickApp variables when the selected run/package tool supports it. Keep source defaults blank, use matching `svar` local overrides, and explicitly blank distribution values. Verify the generated variable type and absence of secrets in exported properties and embedded source. `svar` masks the editor; it does not encrypt values or make logging safe. Check PLua/flua compatibility before converting an existing QA.

If upstream can address only a few items first, my priorities are:

| Priority | Work | Observable success |
|---|---|---|
| High | Property-endpoint contract, finding 5 | A captured HC3 contract and regression cases remove the need for the template's scalar-response adapter. |
| High | Complete versus failed/incomplete run outcomes, finding 8 | A bootstrap failure cannot look successful when assertion failures are zero or logs are filtered. |
| High | Consistent generated instructions, findings 6 and 9 | Freshly installed guidance agrees on mode defaults, runtime discovery and clock choice. |
| Next | Existing-project harness and fault-injection recipe, findings 4 and 10 | An agent can test a multi-file PLua QA and reproduce asynchronous failures without building substantial scaffolding first. |
| Next | Credential examples and toolchain capability checks, finding 13 | Secret variables retain their type and intended values through local overrides and packaging, without exposing credentials in distribution artifacts. |
| Investigate | Historical restart case, finding 7 | A current-version rerun either closes the old finding or produces a reduced, attributable regression. |

The tests give me confidence in using flua as an everyday tool for QA logic and regression work. The remaining improvement is reducing the effort required to explain exactly what a passing or failing run proves.
