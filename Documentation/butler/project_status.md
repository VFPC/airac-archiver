# AIRAC Archiver — Project Status

## Current Project State (2026-03-28)

### System Status: PRODUCTION-READY

**Branch:** `main`
**Dependencies:** pyyaml, click, pytest

### What Exists

- **`src/archiver.py`** — Core archiving logic
  - Allowlist-based file collection: `in.json`, `out.json`, `Routes.csv`, `Notes.csv`, `*.sct`
  - Versioned `out.json`: renames to `out.{cycle}.{n}.json` with monotonic numbering
  - Atomic temp-dir strategy (`shutil.move` + `tempfile.mkdtemp`) preserves existing versioned files across re-archives
  - SHA256 checksums in `manifest.md`
  - Flat-file copy (not zip) to `{archive_repo}/vFPC YYNN/`
  - `rmtree` before copy for clean re-archives; existing `out.{cycle}.*.json` preserved
  - Runs `git add` to stage; never auto-commits

- **`src/airac.py`** — AIRAC cycle date arithmetic
  - Copied from airac-data-fetcher; self-contained, stdlib-only
  - `AiracCycle` dataclass, `cycle_for_date`, `current_cycle`

- **`src/config.py`** — YAML config loader
  - `workspace_base` + `archive_repo` keys; `config.local.yaml` override support
  - `ConfigError` on missing/empty values

- **`src/cli.py`** — Click CLI
  - `archive [--cycle YYNN]` — validates, copies allowlisted files, versions out.json, writes manifest, stages
  - Run via `python -m src archive`

### History

- **v1 (Session 1, 2026-03-11):** Extracted from `airac-data-fetcher`. Zip-based archiving, 7 required files.
- **v2 (PR #2, 2026-03-20):** Flat files, denylist filtering, SHA256 checksums, warn-on-missing, nonexistent-dir guard, duplicate-basename guard, clean re-archive.
- **v3 (PR #4, 2026-03-28):** Allowlist replaces denylist (5 file types only). Versioned `out.json` (`out.{cycle}.{n}.json`). Atomic temp-dir preservation across re-archives. All issues closed.

### What Needs Work

- No open issues — all GitHub issues closed
- Optional: add `pyproject.toml` with `[project.scripts]` entry point

---

Last Updated: 2026-03-28
Status: Production-ready — all modules implemented, tested, and live on AIRAC 2603
