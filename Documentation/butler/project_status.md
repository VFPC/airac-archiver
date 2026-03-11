# AIRAC Archiver — Project Status

## Current Project State (2026-03-11, Session 1)

### System Status: FEATURE-COMPLETE

**Branch:** `main`
**Tests:** 108 (all passing)
**Dependencies:** pyyaml, click, pytest

### What Exists

- Project directory structure (`src/`, `tests/`, `Documentation/butler/`)
- `config.yaml` template with empty path placeholders
- `requirements.txt`
- `.gitignore` for Python projects
- Butler documentation (this file, next_session_prompt, session_status_summary)
- README.md — full user and developer documentation

- **`src/airac.py`** — AIRAC cycle date arithmetic (29 tests)
  - Copied from airac-data-fetcher; self-contained, stdlib-only
  - `AiracCycle` dataclass, `cycle_for_date`, `current_cycle`

- **`src/archiver.py`** — Core archiving logic (45 tests)
  - Collects all 7 required files: Routes.csv, Notes.csv, EG-ENR-3.2-en-GB.html, EG-ENR-3.3-en-GB.html, UK_YYYY_NN.sct, in.json, out.json
  - Creates `{archive_repo}/vFPC YYNN/vFPC YYNN.zip` (flat layout, ZIP_DEFLATED)
  - Writes `manifest.md` with cycle dates, UTC timestamp, OS username
  - Runs `git add` to stage both files; never auto-commits

- **`src/config.py`** — YAML config loader (14 tests)
  - Loads `config.yaml` + optional `config.local.yaml` (deep-merge)
  - `ConfigError` for missing/empty required keys
  - Keys: `workspace_base`, `archive_repo`

- **`src/cli.py`** — Click command-line interface (17 tests)
  - `archive [--cycle YYNN]` — validates files, creates zip, stages in airac-data
  - `_resolve_cycle` parses YYNN ident or defaults to current cycle
  - All domain errors caught cleanly; non-zero exit on failure
  - Run via `python -m src archive`

### Origin

Extracted from `airac-data-fetcher` (Session 10) where it lived as
`src/archive/archiver.py`. Moved to a dedicated repository so it is
independently discoverable, versioned, and deployed.

### What Needs Work

- Live end-to-end test against real cycle data
- Optional: add `pyproject.toml` with `[project.scripts]` entry point

---

Last Updated: 2026-03-11
Status: Feature-complete — all modules implemented and tested; live end-to-end test pending
