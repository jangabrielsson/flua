# Skoda — control QA + API mock

Control a Skoda car (charging and air conditioning) from a QuickApp
through the **MyŠkoda Public API** — with a bundled mock server so the
pair runs and tests fully offline.

Files:

- `myskoda.lua` — the control QA: the declared properties `value`
  (charging on/off) and `batteryLevel` (from the `battery` interface)
  mirror the car; the remaining state (charging state, climate, target)
  lives in QuickApp variables and the UI labels. The actions
  (`turnOn`/`turnOff` = start/stop charging, `setChargingLimit`,
  `startAC`, `stopAC`, `refresh`) drive the car. The property set is
  fixed by the type — the real HC3 silently ignores updates to
  undeclared properties, so the QA never invents any.
- `myskoda_mock.lua` — a `net.HTTPServer` mock of the API subset the
  control QA uses (vehicle state, charging start/stop/limit,
  air-conditioning start/stop). Prints every request as
  `MOCK <METHOD> <path>`; any `X-API-Key` is accepted.
- `myskoda-public-api.yaml` — the official OpenAPI spec (subset
  implemented by the mock, noted in its header).
- `MyŠkoda Public API - Developer Documentation.html` — the official
  HTML documentation page.

## Run offline against the mock

One file is enough — with no `url` configured, the control QA loads the
bundled mock QA (`examples/Skoda/myskoda_mock.lua`, via
`_FLUA.loadQAfromFile`) and tests against it:

```bash
flua --api local examples/Skoda/myskoda.lua
```

The two-QA style also works (the standalone mock is a thin wrapper):

```bash
flua --api local examples/Skoda/myskoda_mock.lua examples/Skoda/myskoda.lua
```

The mock prints its port (`SKODA_MOCK listening on <port>`); the control
QA polls it, printing `SKODA <battery> <state>` on every refresh, and its
device properties track the car state. Drive it from the viewer (`--ui`)
or with actions:

```bash
# in another terminal (the sim API is on the --ui port):
curl -X POST http://127.0.0.1:8090/devices/5001/action/startCharging -d '{"args":[]}'
```

## Run against the real API

Set the QuickApp variables (`url`, `vin`, `key` — the `X-API-Key` from
the MyŠkoda app) or the environment (`MYSKODA_URL`, `MYSKODA_VIN`,
`MYSKODA_KEY`). `once="true"` refreshes once, prints, and exits — the
smoke-test mode.

## Pinned

`tests/test_skoda.py` pins three shapes: the two-QA pair in one engine
(refresh reads the mock, the action round-trips drive it), and the
control QA standalone — it loads the mock QA itself and tests against
it (the pip-user shape).
