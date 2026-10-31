---
name: Feedback / experience report
about: Share a testing experience, verification results, or proposed improvements (not necessarily a bug)
title: "Feedback: "
labels: "feedback"
assignees: ""
---

<!-- This template is for experience reports, verification rounds, and
     improvement proposals — the kind of report that is not a single bug
     but "here is what I tried, what worked, what did not". For a concrete
     reproducible defect use the Bug report template instead. -->

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
     repro when possible, and the suggested change. Mark things you could
     NOT verify as such. -->

## What worked well

<!-- Strengths worth keeping. Optional but genuinely useful. -->

## Priorities

<!-- If several findings: which ones matter most to you, and why. -->
