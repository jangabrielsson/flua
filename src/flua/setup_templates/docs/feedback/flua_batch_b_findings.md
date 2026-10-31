# Flua 0.1.112: Batch B verification

Tested 31 October 2026 on Windows, Python 3.12.10, Lupa 2.6, Lua 5.4.
Only synthetic/local fixtures were used; no controller or physical device access.

## Results

The existing 32-check regression suite passed unchanged.
Of nine additional strict/result acceptance cases, seven passed and two failed.

| Case | Result |
| --- | --- |
| Timer error, followed by a successful callback and exit 0 | Pass: exit 1, failed result, timer error recorded |
| HTTP success-callback error, followed by exit 0 | Pass: exit 1, failed result, net error recorded |
| Error caught by application pcall | Pass: exit 0, passed result, no failures |
| Legacy timer-error behaviour without strict mode | Pass: legacy exit 0 retained |
| Declarative `-D strict-tests:true` | Pass: sticky timer failure |
| Pending work cut short by positive `--run-for` | Pass: timeout result and exit 1 |
| Error thrown directly by a custom UIHandler | Pass: exit 1, ui error recorded |
| Mapped button callback invoked through UIAction | FAIL: error logged, exit 0, passed result, empty failures |
| Mapped button callback invoked through _FLUA.uiEvent | FAIL: error logged, exit 0, passed result, empty failures |

JSON result checks include schemaVersion, agreement with process exit code,
runtime version, realtime clock mode, timing fields and cleanupComplete=true.
The cleanup flag is reported by Flua; it is not an independent resource-leak audit.
The timeout case does not test a blocked Lua/native stack or an independent outer
supervisor. We retain an external wall-clock guard and independent log checking.

## Minimal remaining UI reproduction

Save as `ui_callback_error.lua`:

```lua
--%%mode:offline
--%%u:{button="btnFailure",text="Test",onReleased="failUi"}
function QuickApp:failUi()
  error("EXPECTED_UI_CALLBACK_FAILURE")
end
function QuickApp:onInit()
  setTimeout(function()
    _FLUA.uiEvent("btnFailure", "onReleased")
  end, 10)
  setTimeout(function()
    print("LATER OK")
    _FLUA.exit(0)
  end, 500)
end
```

```text
flua --api local --strict-tests --result-json ui-result.json --run-for -2 ui_callback_error.lua
```

Observed in the equivalent guarded fixture: the UI error is logged, `LATER OK`
prints, process exit is 0, and the result says `status="passed"`, `exitCode=0`,
`failures=[]`. Replacing `_FLUA.uiEvent(...)` with
`self:UIAction("onReleased", "btnFailure")` reproduces the same gap.

Expected: the mapped callback error should be recorded and remain a strict-mode
failure despite the later exit 0, just as timer and HTTP callback errors do.

## Likely cause and suggested correction

In the installed `quickapp.lua`, `onUIEvent` schedules `callAction` for a mapped
callback. `callAction` catches the action exception using `xpcall` and logs it,
without recording a strict failure. Therefore the outer coroutine dispatch sees
no exception. This is simulator framework error handling, not an application
deliberately catching an expected error.

Suggested upstream change: record the original exception at this framework catch
boundary, retaining the UI/action origin and avoiding duplicate failure entries.
Keep legacy logging/continuation and application-owned pcall behaviour unchanged.
Add tests for mapped callbacks, direct UIHandler, child UI dispatch and ordinary
actions; the last two are suggested coverage, not claimed verified here.

No changes were made to the installed Flua implementation to hide this finding.
