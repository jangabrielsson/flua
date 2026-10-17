# flua decisions

ADR-lite: the *why* behind deliberate, hard-to-reverse choices. One file
per decision, newest last. Update this instead of the code comments when a
decision changes.

| # | Decision | Status |
|---|---|---|
| [0001](0001-default-mode-is-offline.md) | offline is the default mode; online is opt-in | active |
| [0002](0002-id-namespaces.md) | three id namespaces: HC3 < 5000, engine QAs ≥ 5000, runtime devices ≥ 900000 | active |
| [0003](0003-proxy-devices-never-emit-local-events.md) | proxy devices never emit local refresh events | active |
| [0004](0004-device-lifecycle-events.md) | device create/remove emit DeviceCreated/DeviceRemoved events | active |
| [0005](0005-pump-polls-get_nowait.md) | the pump polls the outbound queue with get_nowait, never wait_for | active |
| [0006](0006-in-flight-api-calls-are-pending-work.md) | suspended QAs' remote calls count as pending work | active |
| [0007](0007-tests-parallel-by-default.md) | tests run parallel by default with a serial hatch and a slow-marker gate | active |
| [0008](0008-fqa-files-runnable-as-scripts.md) | `.fqa` files are directly runnable as scripts | active |
| [0009](0009-real-logs-over-rest.md) | the sim serves real logs over REST (debugMessages + systemLog) | active |
| [0010](0010-mcp-ships-in-the-wheel.md) | the MCP server ships in the fibaro-flua wheel as a second entry point | active |
