# AIRAC Archiver — Next Session Prompt

## Quick start

Read this file first, then `project_status.md`, then `session_status_summary.md`.

## Current state (as of 2026-03-11, Session 1)

This repository was created in Session 1 by extracting the archiver from the
`airac-data-fetcher` repository, where it had been buried in `src/archive/`.
All code, tests, and documentation have been set up from scratch.

**Branch:** `main`
**Tests:** 110 (all passing — airac 29, archiver 45, config 14, cli 17, rules_db 2, plus helpers)
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

## Rules database

The vFPC ecosystem uses `[RULE:...]` tags to link code to aviation rule sources. The archiver currently uses **no** `[RULE:...]` tags — it packages files without interpreting aviation policy, so there are no rules to cite.

- Convention: `C:\Users\jkino\Documents\GitHub\vFPC-Rules-Database\Documentation\convention.md`
- Index: `C:\Users\jkino\Documents\GitHub\vFPC-Rules-Database\Documentation\rules_reference.md`
- The rules_reference.md table has an **airac-archiver Files** column (all `—` for now)
- `tests/test_rules_db.py` validates the convention; skips gracefully if the rules DB is not found

If you need to add a rule tag in the future: propose the tag name first, wait for user approval, then add it to both source and `rules_reference.md`.

## Data dictionary

The archiver packages the output of the SRD Parser. The relevant data shapes are:

| File | Source | Description |
|---|---|---|
| `in.json` | Manually created / copied forward | Input configuration for the SRD Parser |
| `out.json` | SRD Parser output | The fully processed constraint tree (see `data_shapes.md` in New-SRDParser) |
| `Routes.csv` | SRD Excel | Route constraints; feeds the SRD Parser (Stage 1 DTO input) |
| `Notes.csv` | SRD Excel | Manual reference notes |
| `EG-ENR-3.2-en-GB.html` | NATS AIP | ENR 3.2 airway table; read by AIP Parser |
| `EG-ENR-3.3-en-GB.html` | NATS AIP | ENR 3.3 airway table; read by AIP Parser |
| `UK_{YYYY}_{NN}.sct` | VATSIM-UK | UK sector file; read by vFPC plugin |

The data dictionary for the internal data flow (CSV → SrdConstraint → ParsedConstraint → OutConstraint → JSON) is in:
`C:\Users\jkino\Documents\GitHub\New-SRDParser\Documentation\diagrams\data_shapes.md`

The archiver treats all files as opaque blobs — it does not validate their content.

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
