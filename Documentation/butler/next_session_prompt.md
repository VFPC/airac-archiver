# AIRAC Archiver — Next Session Prompt

_Stable operational reference. For project status and outstanding work see the Hub._
_Hub: `C:\Users\jkino\Documents\GitHub\vFPC-Hub\Documentation\butler\`_

## Current state (as of 2026-03-28)

**Branch:** `main`
**Status:** Production-ready — all GitHub issues closed

All archiver work is tracked at the Hub level. This repo has no open issues.

## Key files

| File | Purpose |
|---|---|
| `src/archiver.py` | Core archive logic — allowlist collection, versioned out.json, manifest |
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

## What it does

1. Collects allowlisted files from the cycle working directory (`in.json`, `out.json`, `Routes.csv`, `Notes.csv`, `*.sct`)
2. If `out.json` is present, renames it to `out.{cycle}.{n}.json` (monotonic version numbering)
3. Preserves existing versioned `out.{cycle}.*.json` files from prior runs using atomic temp-dir strategy
4. Copies flat files to `{archive_repo}/vFPC YYNN/`
5. Writes `manifest.md` with cycle dates, SHA256 checksums, and UTC timestamp
6. Runs `git add` to stage; never auto-commits

## Rules database

The archiver uses **no** `[RULE:...]` tags — it packages files without interpreting aviation policy.

## Data dictionary

The archiver treats all files as opaque blobs — it does not validate their content.
See `New-SRDParser/Documentation/diagrams/data_shapes.md` for the internal data flow.
