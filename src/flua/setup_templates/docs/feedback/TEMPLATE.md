# <topic> — agent experience report with flua

Date: <yyyy-mm-dd> · flua <version> · <platform, python>

Status: open   <!-- open | triaged:<pointer> | reject:<reason> -->

<!-- The same sections as the GitHub Feedback issue template
     (.github/ISSUE_TEMPLATE/feedback.md), so this file can become an
     issue unchanged. For a concrete reproducible defect, the Bug report
     template is the better fit. -->

## What I was doing

<!-- One paragraph: the QA/workflow under test, the goal. -->

## Environment

<!-- Paste `flua --version --machine` (and `flua --capabilities-json` if
     relevant). Version matters: reports against older releases often hit
     already-fixed behavior. -->

- flua version:
- OS:
- Python version:
- Mode: offline / online / proxy

## Results

<!-- What passed, what failed, with the commands run. -->

```text
```

## Findings

<!-- One finding per heading, each with: expected vs observed, a minimal
     repro when possible, and the suggested change (a capabilities entry
     id/topic/title/pins sketch when it is a knowledge gap). Mark things
     you could NOT verify as such. -->

## What worked well

<!-- Strengths worth keeping. Optional but genuinely useful. -->

## Priorities

<!-- If several findings: which ones matter most to you, and why. -->

## How to get this back

- **Preferred: file it as a GitHub issue** — `flua --tool feedback
  publish <this-file>` runs `gh issue create --label feedback --body-file`
  (needs `gh` authenticated against the flua repo).
- Or: attach to the forum thread, or open a PR adding the file to
  `docs/feedback/<slug>_flua_<yy_mm_dd>.md`.
- Closing a file sets the Status line to a pointer: the capabilities
  entry / test / tool it became, or the reason it was rejected. The
  triage loop is documented in docs/feedback/README.md.
