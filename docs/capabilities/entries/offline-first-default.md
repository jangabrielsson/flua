---
id: offline-first-default
topic: modes
title: Offline is the default; online is opt-in
pins:
  - docs/decisions/0001-default-mode-is-offline.md
verified: flua 0.1.169
---

# Offline is the default; online is opt-in

flua runs against the simulated HC3 unless you explicitly opt into the
real one — the safety posture every other mode builds on:

- No HC3 credentials → everything is the sim; network access is real
  (QAs reach the internet) but the *controller* is synthetic.
- `--%%mode:online` (or the engine's remote API mode) opts a run into
  the hybrid routing against a real HC3; per-QA `--%%mode:offline`
  pins a QA to the sim even in an online run.
- `--%%mode:readonly[+call]` layers the write guard on top of online;
  `--%%mode:proxy` mirrors a QA onto the controller.
- The mode family is a per-QA directive; the legacy
  `--%%offline:true/false` and `--%%proxy:true` spellings still map
  onto it (an explicit `--%%mode` wins).

See ADR 0001 for the reasoning: offline-first keeps development
deterministic, credential-free, and safe.
