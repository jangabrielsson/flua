# Feedback: how it lands, how it is triaged

User feedback (forum posts, agent experience reports, verification
rounds) follows one loop. This file documents it so agents and the
maintainer run the same process.

## Landing

- **Preferred: a GitHub issue** — use the *Feedback / experience report*
  template (`.github/ISSUE_TEMPLATE/feedback.md`). It prompts for the
  version trail, the environment, results, findings and priorities — the
  fields that make a report actionable.
- Forum posts and pasted messages are fine too: file them as
  `docs/feedback/<author>_<topic>.md` (this directory) so the context
  survives, and treat them exactly like an issue.
- Every report, however it lands, gets one thing first: **check the flua
  version against the current tree** — a large share of historical
  findings hit already-fixed behavior.

## Triage

1. **Verify each claim** against the current tree — reproduce it, or mark
   it not-reproducible and say so.
2. Sort into three buckets:
   - **Fix now** — confirmed defects and small verified inconsistencies.
     Each fix rides with a pinning test.
   - **Park** — non-urgent improvements: file in `docs/rainy_day_todos.md`
     with the rationale (and the overlap notes when a proposal duplicates
     existing machinery). Promote when someone asks twice.
   - **Needs evidence** — claims we cannot verify offline (live-HC3
     contracts): capture against the real controller before changing
     anything.
3. **Reply** — one `docs/feedback/reponse_*.md` per round, covering: what
   was already fixed (with releases), what changed in response, what was
   parked, and what remains theirs to re-verify.

Conventions that make this work:

- Live-HC3 captures are read-only and recorded (`docs/feedback/*_capture*.md`)
  before any route changes.
- Status changes to the compatibility table (`--capabilities-json`) ride the
  same commit as the change that causes them.
- Packaged copies of everything under `docs/` and `.github/skills/` are
  sync-guarded by tests — run `scripts/sync-skills.sh` after edits.

## Polling (for agents)

```bash
gh issue list --repo jangabrielsson/flua --label feedback --state open
gh issue view <number>          # read one
gh issue list --label bug --state open
```

Labels in use: `bug`, `feedback`, `enhancement`, `needs-repro`,
`verified-fixed`, `rainy-day`.
