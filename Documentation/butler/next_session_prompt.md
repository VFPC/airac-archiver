# AIRAC Archiver — Next Session Prompt

## Quick start

Read this file first, then `project_status.md`, then `session_status_summary.md`.

## Current state (as of 2026-03-11, Session 1)

This repository was created in Session 1 by extracting the archiver from the
`airac-data-fetcher` repository, where it had been buried in `src/archive/`.
All code, tests, and documentation have been set up from scratch.

**Branch:** `main`
**Tests:** 108 (all passing — airac 29, archiver 45, config 14, cli 17, plus helpers)
**Status:** Feature-complete; live test pending

## What was done in Session 1

- Created the repository with the correct directory structure
- Extracted and adapted `archiver.py` from `airac-data-fetcher/src/archive/archiver.py`
- Copied `airac.py` from `airac-data-fetcher` (self-contained stdlib date math)
- Wrote `config.py` (workspace_base + archive_repo, local override support)
- Wrote `cli.py` (single `archive` command, `_resolve_cycle`, error handling)
- Ported and updated all tests (82 total, all green)
- Wrote `README.md` with full user and developer documentation
- Removed archiver from `airac-data-fetcher` (clean separation)

## Next steps

1. **Live test** — run `python -m src archive --cycle YYNN` with real data files after SRD Parser run
2. Push to GitHub and create the remote repository
3. Update `airac-data-fetcher` README to reference `airac-archiver` for the archive step

## Key files

| File | Purpose |
|---|---|
| `src/archiver.py` | Core zip/manifest/git logic |
| `src/config.py` | YAML config loader |
| `src/cli.py` | Click CLI (`archive` command) |
| `src/airac.py` | AIRAC cycle date arithmetic |
| `config.yaml` | Default config (commit this) |
| `config.local.yaml` | Machine-specific paths (gitignored) |

## How to run

```
python -m src archive --cycle 2603
```

Requires `config.local.yaml` with `workspace_base` and `archive_repo` set.
