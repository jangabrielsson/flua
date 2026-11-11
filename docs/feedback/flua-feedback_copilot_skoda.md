# Feedback: building a Skoda QuickApp with flua

## Context

This feedback comes from building [skoda.lua](./skoda.lua), a separate
[mock service QA](./skoda_mock.lua), an
[offline integration test](./dev/skoda_test.lua), and an HC3 package.
The inputs were the local MySkoda OpenAPI YAML and HTML developer guide.
The implementation was written from scratch after the user explicitly
excluded the bundled Skoda example.

The installed version was flua 0.1.144. Verification finished with static
checks, 73 passing assertions through the flua MCP test tool, and a separate
strict virtual-time test run. No real HC3 or car was contacted.

These are observations from one session, not a comprehensive product review.
Some requests below may already be possible through interfaces I did not
discover. That discoverability is itself part of the feedback.

## What worked well

### Real client code against a local service

The strongest feature was the combination of isolated QAs, dynamic loading,
`net.HTTPServer`, and the ordinary `net.HTTPClient`.

The client could load a second QA at startup, discover its ephemeral
loopback port, and talk to it over actual HTTP. The mock kept vehicle state,
checked fake credentials, enforced quotas, and processed commands. That
exercised the client's real request construction and callbacks rather than
replacing its HTTP layer with test-only functions.

The `_FLUA` marker provided a clear boundary: automatic mock startup is
emulator-only; the HC3 path needs no server extension. Keeping the mock out
of `--%%file` declarations also kept it out of the deployment package.

### Offline HC3 simulation with real networking

`--api local` made the safety boundary explicit. HC3 REST calls stayed in
the simulator while HTTP traffic reached the local mock. The installed
network-testing guidance explains this distinction well; “offline” does
not mean networking is disabled.

### Useful test primitives

`require("flua-test")` supplied assertions and a terminating verdict without
adding a dependency or building a separate Python test suite.

The test could drive UI events and `fibaro.call`, inspect the rendered
view, verify state returned over HTTP, and exercise errors. `--strict-tests`
was valuable because a callback exception should not become a passing run
just because a later callback exits successfully.

Virtual time made timer-related verification practical. The warning in the
agent documentation about choosing `--step` rather than `--instant` for
`os.time()`-dependent scheduling was particularly useful.

### Checks and packaging

`flua --check` was quick and easy to use. The MCP UI tool exposed declared
elements and callback bindings without requiring a browser.

The `battery` interface guidance prevented inventing properties that would
appear to work locally but be ignored on an HC3. `typeinfo` was useful for
checking the declared property contract.

Packaging the client alone was straightforward. Empty credential variables
were preserved, and no mock or test file was included.

## Where the experience was harder

### 1. Finding the right information took too many routes

I used workspace instructions and skills, the MCP documentation list/read
tools, CLI help, bundled documentation, and eventually installed Lua runtime
source.

There was already enough capability to complete the task. The difficulty
was finding the exact contracts:

- Does dynamic QA loading return before `onInit` has completed?
- What can be accessed through `_FLUA.qa(id)`?
- How should the client know that a mock's server is ready?
- How should a sibling file be resolved independently of the working directory?
- Does `listen(0, handler)` expose its assigned port immediately?
- How do virtual timers interact with pending real HTTP?

The generic docs explained many pieces, but I still read runtime source to
confirm behavior and discovered `_FLUA.mainPath` there.

**Suggestion:** provide a compact, indexed “client QA + dynamically loaded
mock QA” recipe with explicit readiness, path, lifetime, and error contracts.
It should be generic, not tied to Skoda or another service.

### 2. Documentation responses were too large for targeted questions

The MCP `docs_list` response was about 51 KB and was offloaded to a temporary
file. Reading the patterns skill returned about 23 KB and was also
offloaded. I then had to search or read those files through other tools.

This weakens the advantage of having documentation available through MCP:
the agent ends up doing filesystem archaeology anyway.

**Suggestions:**

- Add filtering and pagination to `docs_list`.
- Add a local `docs_search` returning short excerpts and stable section IDs.
- Let `docs_read` select a heading or line range and impose an output limit.
- Return related sections for a symbol such as `_FLUA.mainPath` or
  `net.HTTPServer`, rather than the whole manual.
- Offer task-oriented entry points such as “mock an HTTP service” and
  “verify a packaged QA.”

No web search or remote knowledge service should be needed for this.

### 3. Installed skills and callable skills were not the same thing

Workspace skill files were present and readable. However, an attempt to
invoke `quickapp-api` through the skill-loading interface failed because
that name was not in that interface's available list.

This does not show that the skill content was missing; it shows that
installation, discovery, and invocation were not aligned in this setup.

**Suggestion:** expose a capability summary distinguishing:

- Skills available as local documents.
- Skills registered with the editor's skill loader.
- How an agent should load each category.

A setup/doctor check could flag the mismatch and offer the appropriate
local or MCP document path.

### 4. Tool discovery added avoidable friction

Searching for specific flua MCP tools sometimes returned other related
tools rather than the named tool. It took several searches before the
generic `flua_tool` interface was available.

I also initially passed two names to `typeinfo`, which only accepts one.
That was my incorrect assumption, not a flua failure.

**Suggestions:**

- Supply a short agent-facing tool map with exact names and example calls.
- Make the generic tool registry discoverable through one compact response.
- Include argument schemas or concise usage in registry results.
- When arguments are invalid, return a valid example alongside the error.

Search ranking and deferred-tool exposure also depend on the host. Those
problems are not necessarily fixable inside flua alone.

### 5. Real networking plus virtual time needs a clearer testing recipe

An early `--step` test reached its virtual watchdog before a raw HTTP
request completed. I changed the harness to use a bounded, short-timer
wait loop, which allowed the test to continue successfully.

That observation is not enough to diagnose a scheduler bug. The harness
was mixing real asynchronous I/O with virtual deadlines, and my initial
synchronization was insufficient.

**Suggestions:**

- Document how `--step` advances while socket I/O is pending.
- Clearly distinguish virtual-time deadlines from wall-clock I/O timeouts.
- Provide a test helper such as `eventually(predicate, timeout)` that
  cooperates with the pump and reports a useful timeout.
- Provide an awaitable request helper for test QAs without changing normal
  HC3 client code.
- Include one generic regression example combining a dynamic mock, real
  HTTP, virtual timers, and a watchdog.

I also hit a nil access after loading another QA because I assumed the
instance was already available. That was my test bug, but a documented
readiness pattern or loader helper would make this mistake less likely.

### 6. Passing tests still required parsing verbose logs

The MCP test runner returned a successful result, but the complete output
was large enough to be offloaded. Its per-file `failures` field was null
even though the assertion library printed a failure count. I counted
`PASS:` lines in Python to report the final assertion total.

**Suggestions:**

- Have `flua-test` publish structured assertion totals to the runner.
- Return `assertionsPassed`, `assertionsFailed`, and runtime errors directly.
- Default to a concise summary; include full logs on request or failure.
- Preserve diagnostics while clearly separating deliberately exercised
  HTTP errors from actual test failures.

Expected 401/422/429 cases generated error-level client logs. They were
correct behavior, but without test context they can look like failed tests.

## Why I went outside the workspace

| What I accessed | Why | How flua could improve it |
|---|---|---|
| Installed generic examples | To check the HTTP server API | Serve a small, runnable generic recipe through documentation tools |
| Bundled USAGE documentation | To verify dynamic loading and configuration behavior | Symbol/heading-level documentation lookup |
| Installed Lua runtime source | To confirm loader behavior, server semantics, and `_FLUA.mainPath` | Explicit public contracts with examples and readiness guarantees |
| Temporary MCP output files | Tool results were too large for direct reading | Bounded results, filters, and concise structured summaries |
| Bundled Skoda README | I discovered an existing example while searching installed docs | Task-scoped searches that do not automatically pull in matching application examples |

These were local reads, not contacts with a real service.

Reading the bundled Skoda README was an approach the user did not want.
After the user clarified that constraint, I did not use the bundled Skoda
implementation. I should have kept the investigation focused on generic
flua references instead of treating an application example as the next
source of guidance.

Avoiding these reads does not require copying all installed source into
every workspace. A good local documentation interface would be better.

## Why I started Python

I used Python for supporting inspection, not to implement the mock server
or the QuickApp:

1. **Extracting text from the supplied HTML.** A small standard-library HTML
   parser stripped markup, scripts, and styles so I could read the local
   developer guide.
2. **Inspecting the exported `.fqa`.** I checked the JSON structure, variables,
   interface declaration, included files, and packaged source.
3. **Comparing source with packaged source.** Exact equality initially failed
   because packing rewrites `--%%var` expressions as baked literals,
   including changing quote style. That was expected pack behavior, not a
   packaging defect.
4. **Summarizing the MCP test result.** I parsed the saved JSON and counted
   assertion log lines because the structured result did not expose that
   count.

Python was convenient because `.fqa` is JSON and Python was already
available. Its use is not inherently a problem. Nevertheless, these are
routine QA-development operations that flua could make easier without
ad hoc scripts.

**Suggested additions:**

- `flua --tool inspectFQA FILE --json`: metadata, file inventory, interfaces,
  initial variables, and validation findings.
- `flua --tool verifyPackage SOURCE PACKAGE`: compare executable source,
  account for documented directive rewriting, and verify packaged variables
  and included files.
- A packaging manifest with source hashes and a summary of intentional
  transformations.
- Structured test assertion totals, removing the need to parse log text.

Local HTML-to-text conversion is a lower priority and could remain an
editor/tooling responsibility rather than expanding flua itself.

## Information quality and safety

The workspace instructions supplied conflicting statements about whether
online or offline mode was the default. The installed CLI help established
offline as the default for this version; all verification commands used
explicit `--api local` anyway.

**Suggestion:** stamp generated agent docs and skills with their source
version and offer an offline freshness check. A compact capability response
should identify actual defaults, network behavior, available extensions,
and matching documentation. Avoid silently overwriting customized docs.

It would also help to document the limits of each verification layer:

- Static checks do not prove asynchronous runtime correctness.
- A local mock validates the client against the mock's contract, not a car.
- Removing `_FLUA` in a controlled test verifies the client's branch logic,
  not execution on genuine HC3 firmware.
- Package inspection proves contents, not deployment success.

The separation was useful in this task, but the tools could make those
boundaries more visible in their summaries.

## Highest-value improvements

| Priority | Improvement | Benefit in this task |
|---|---|---|
| 1 | Searchable, bounded local documentation and a compact tool map | Avoid most installed-source searches and oversized tool responses |
| 2 | Generic dynamic mock-QA recipe with readiness and path contracts | Make the central architecture easy to implement correctly |
| 3 | Structured assertion results and concise default test output | Eliminate log parsing and make pass/fail evidence clear |
| 4 | Documented real-I/O/virtual-time semantics plus eventual/await helpers | Reduce fragile asynchronous test boilerplate |
| 5 | Package inspection and source-aware verification | Replace custom Python package checks |
| 6 | Version-aware agent docs and skill-discovery diagnostics | Resolve conflicting defaults and loading confusion |

## Overall

flua's core functionality was a very good fit: the actual HC3-style client
could communicate with an actual local HTTP service hosted by another QA,
with no external mock framework and no live hardware.

The biggest opportunity is not adding another transport or device API.
It is making the existing capabilities easier to discover, compose, and
verify. A short path from “I need a mock service” to a documented readiness
pattern, a terminating test, and a verified package would have removed most
of the external searching and supporting Python in this session.
