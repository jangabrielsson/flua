# Skoda — control QA + API mock

Control a Skoda car (charging and air conditioning) from a QuickApp
through the **MyŠkoda Public API** — with a bundled mock server so the
pair runs and tests fully offline.

Files:

- `myskoda.lua` — the control QA (`com.fibaro.genericDevice` + the
  `battery` interface). The declared `batteryLevel` property and the
  colored UI labels mirror the car; the rest of the dynamic state
  (charging state, climate, target) lives in QuickApp variables. The
  actions (`startCharging`/`stopCharging`, `setChargingLimit`,
  `startAC`/`stopAC`, `refresh`, plus `turnOn`/`turnOff` aliases) drive
  the car. The property set is fixed by the type — the real HC3
  silently ignores updates to undeclared properties, so the QA never
  invents any.
- `myskoda_mock.lua` — a `net.HTTPServer` mock of the API subset the
  control QA uses (vehicle state, charging start/stop/limit,
  air-conditioning start/stop). Prints every request as
  `MOCK <METHOD> <path>`; any `X-API-Key` is accepted. It emulates the
  real constraints: the 20 requests/hour/VIN rate limit (headers and
  429s included), and the battery charging to the target while CHARGING.
- `myskoda-public-api.yaml` — the official OpenAPI spec (subset
  implemented by the mock, noted in its header).
- `MyŠkoda Public API - Developer Documentation.html` — the official
  HTML documentation page.

## Run offline against the mock

One file is enough — with no `url` configured and running under flua,
the control QA loads the bundled mock QA (`_FLUA.loadQAfromFile`) and
tests against it:

```bash
flua --api local examples/Skoda/myskoda.lua
```

The two-QA style also works — the mock serves a fixed port (18290,
unlikely to collide) and the control QA defaults to the same one:

```bash
flua --api local examples/Skoda/myskoda_mock.lua examples/Skoda/myskoda.lua
```

The control QA polls the mock, printing `SKODA <battery> <state>` on
every refresh. Drive it from the viewer (`--ui`) or with actions:

```bash
# in another terminal (the sim API is on the --ui port):
curl -X POST http://127.0.0.1:8090/devices/5001/action/startCharging -d '{"args":[]}'
```

`once="true"` refreshes once, prints, and exits — the smoke-test mode.
The mock stands down with a warning when its port is taken.

## The simulated charging

While CHARGING, the mock raises the battery at `chargeRate` percent per
**virtual** hour (default 10) until the target, then flips back to
READY_FOR_CHARGING on its own. Speed the simulation up with the mock's
`chargeRate` variable and/or the run's `--speed`/`--%%speed` (the file
ships with `--%%speed:60`) — the mock's `os.time()` is flua's virtual
clock.

## Rate limits (the real thing)

The real API allows **20 requests/hour per VIN** and answers `429` +
`Retry-After` beyond that. The QA polls every 5 minutes (12/hour, with
headroom for the two-request action round-trips) and warns on 429s with
the retry guidance; the mock enforces the same limit with the
`RateLimit-*` headers.

## Run against the real API

Set the QuickApp variables `url`, `vin`, and `key` (the `X-API-Key`
from the MyŠkoda app). The mock `vin`/`key` defaults apply **only** to
the embedded-mock case — a configured `url` is the real API, and
missing credentials warn instead of silently calling it with mock
values. The embedded mock's port is overridable via the `mockPort`
variable.

## Pinned

`tests/test_skoda.py` pins five shapes: the two-QA pair (refresh reads
the mock, the action round-trips drive it), the control QA standalone
with the embedded mock (the pip-user shape), the rate limit (20 pass,
the 21st is a 429), and the charging simulation (the battery reaches
the target and the state settles itself on the virtual clock).
