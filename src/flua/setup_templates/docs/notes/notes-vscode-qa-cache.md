# Note: the hub resource cache in the VS Code extension (design)

Status: implemented (2026-11-08) — `vscode/src/cache.ts`, the View (.fqa)
and Download flows, `modified` in `--tool hubList`, the hub-newer staleness
badge on tree nodes, and the 30-day pruning sweep on activation.

## Goal

Browsing a hub QA should not mean re-downloading it every time. Two flows
share one cache:

1. **View (.fqa)** — open a hub QA in the existing `.fqa` custom editor
   without unpacking it into the workspace.
2. **Download (edit)** — the unpack-into-workspace flow reuses the cached
   package instead of re-exporting from the HC3.

## The key insight: freshness for free

The hub tree already fetches `/devices` on every refresh. `hubList` carries
each QA's `modified` timestamp (one more field from the data it already
pulls), so staleness decisions cost **zero extra HC3 calls**. The
expensive export (`POST /quickApp/export/{id}`) runs only when the cached
copy is missing or stale — and once cached, viewing works offline.

## Cache layout

- Root: `context.globalStorageUri / hc3-cache / <hub-serial> /` — outside
  the workspace, invisible to git, machine-local. Keyed by hub serial
  (`/settings/info`'s `hcName`), so several hubs cannot collide.
- Per QA: `<id>.fqa` (the package, from `flua --tool downloadFQA -o`) and
  `<id>.json` meta: `{modified, fetchedAt, name}`.
- Lifecycle: overwrite on update. A prune-older-than-N-days sweep on
  activation is a later nicety, not v1.

## Flows

**View (.fqa)** (new tree action `Flua: View (.fqa)`):

1. Cache hit and fresh (`meta.modified` equals the `hubList` entry's
   `modified`) → open the cached `.fqa` in the custom editor
   (`vscode.openWith`, viewType `flua.fqaViewer`).
2. Missing or stale → `flua --tool downloadFQA <id> -o <cache> -f` →
   write meta → open.

**Download (edit)** (the existing tree action, re-routed):

1. `cache.ensure(qa)` — same hit-or-fetch as above, one HC3 call at most.
2. `flua --tool unpack <cached.fqa> -d <workspace>/<name>-<id>` — local,
   deterministic, and the cache now feeds every repeat download of the
   same QA.

## Enabling the staleness badge (follow-up)

`modified` in `hubList` is also the data a tree-node badge needs ("hub
newer than the local project"): record the `modified` the project was
unpacked from (a small meta file in the project dir, or the
`hub.dirs` workspaceState entry extended with it) and compare on refresh.
Follow-up, not v1 — the cache note pins the data shape it depends on.

## Secrets and safety

The cache stores exactly what `downloadFQA` writes into the workspace
today — the same package, same variable contents. No new secret surface;
the viewer masks secret variables as before. The cache is display
material only: nothing in these flows writes to the hub.

## Related

- `docs/notes/notes-vscode-hub-browser.md` — the tree this extends
- `src/flua/tools/download_fqa.py` — `-o`/`-f` (the cache's fetch step)
- `src/flua/tools/hub_list.py` — gains `modified` per QA
- `vscode/src/hub.ts`, `vscode/src/fqaEditor.ts` — the consumer and the
  viewer
