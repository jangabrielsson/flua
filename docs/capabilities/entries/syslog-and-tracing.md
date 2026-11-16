---
id: syslog-and-tracing
topic: debugging
title: --syslog and --trace — the machine-readable run history for agents
pins:
  - tests/test_qa.py::test_syslog_file_records_system_events
  - tests/test_trace.py::test_trace_categories_filtered_into_syslog
verified: flua 0.1.166
---

# --syslog and --trace — the machine-readable run history for agents

Two channels that turn a run into data an agent can post-process:

- `--syslog run.json` (or `--%%syslog:run.json`) — one JSON line per
  system/crash event: the complete on-disk history, where
  `/flua/systemLog` is the bounded in-memory buffer.
- `--trace api,ui,net,timer` (or `all`) — structured run traces per
  category, delivered as `event: trace` entries into the syslog: every
  api.* call (URL, status, body — the arguments that usually go
  wrong), UI events, net traffic, timer activity.

Agents follow a failing run by replaying the syslog instead of
re-reading debug output; the trace categories are the same `--%%trace`
directive QAs can carry in their header.
