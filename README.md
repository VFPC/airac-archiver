# airac-archiver

Copies prepared AIRAC cycle files into the [airac-data](https://github.com/VFPC/airac-data) archive repo as flat files and stages them for review before commit.

This tool does **not** build zip archives. It copies an allowlisted set of files into `airac-data`, writes `manifest.md`, renames `out.json` to a versioned archive filename, and runs `git add`.

Run this tool after `New-SRDParser` has produced `out.json` in the cycle working directory.

---

## Related repositories

| Repository | Purpose |
|---|---|
| [airac-data-fetcher](https://github.com/VFPC/airac-data-fetcher) | Prepares the cycle working directory and fetches source files |
| [New-SRDParser](https://github.com/VFPC/New-SRDParser) | Produces `out.json` from `Routes.csv`, `.sct`, and `in.json` |
| [airac-data](https://github.com/VFPC/airac-data) | Long-term archive of packaged cycle files |
| **airac-archiver** | This tool — copies flat files into `airac-data` and stages them |

---

## Prerequisites

- Python 3.11 or newer
- A local clone of [airac-data](https://github.com/VFPC/airac-data)
- A prepared cycle working directory containing the files to archive

Install dependencies:

```
pip install -r requirements.txt
```

---

## Configuration

Copy the template and fill in your paths:

```
cp config.yaml config.local.yaml
```

Edit `config.local.yaml`:

```yaml
workspace_base: C:\Users\you\Desktop\vFPC files\Historical Files
archive_repo:   C:\Users\you\Documents\GitHub\airac-data
```

`config.local.yaml` is gitignored.

| Key | Description |
|---|---|
| `workspace_base` | Directory containing per-cycle working directories such as `vFPC 2603\` |
| `archive_repo` | Path to your local clone of the `airac-data` repository |

---

## Allowlisted archive files

The archiver copies only these cycle files into `airac-data`:

| File | Notes |
|---|---|
| `Routes.csv` | SRD route data |
| `Notes.csv` | SRD notes data |
| `UK_{YYYY}_{NN}.sct` | VATSIM UK sector file for the cycle |
| `in.json` | Supplementary parser input |
| `out.json` | Parser output, archived as `out.{ident}.{n}.json` |
| `curation_notes.md` | Optional manual curation note for cycle-specific row removals or other interventions |

Everything else in the working directory is ignored. `curation_notes.md` is optional: it is archived when present and ignored when absent.

Expected files that are missing are recorded as warnings in `manifest.md`, but the archiver can still proceed as long as the directory looks like the correct cycle directory.

---

## Usage

### Archive the current cycle

```
python -m src archive
```

### Archive a specific cycle

```
python -m src archive --cycle 2603
```

The `--cycle` argument is a four-digit AIRAC ident: two-digit year followed by two-digit cycle number.

---

## What happens when you run the archiver

1. Validates that the target cycle directory exists.
2. Collects only the allowlisted files for that cycle.
3. Copies them as flat files into `{archive_repo}\vFPC YYNN\`.
4. Renames `out.json` to `out.{ident}.{n}.json`.
5. Writes `manifest.md` with cycle metadata, warnings, and SHA256 checksums.
6. Runs `git add` in the `airac-data` repo so the archive is staged for review.

After the tool completes, review the staged changes in the `airac-data` repository and commit when satisfied:

```
cd path\to\airac-data
git diff --staged
git commit -m "Add vFPC 2603 archive"
git push
```

---

## Dot releases for out.json

The archive keeps multiple versions of `out.json` for the **same cycle** when that cycle is re-archived.

Examples:

- `out.2603.1.json` = first archived parser output for AIRAC 2603
- `out.2603.2.json` = later re-archive of AIRAC 2603 after a parser rerun or correction
- `out.2603.3.json` = another later archive of the same cycle

These are not separate AIRAC cycles and not semantic-version releases. They are archive revisions of the same cycle output.

When the same cycle is archived again:

- existing `out.2603.N.json` files are preserved
- the new `out.json` becomes the next numbered version
- the manifest lists every archived version currently present for that cycle

---

## Typical workflow

1. Run `airac-data-fetcher` to prepare the cycle working directory:
   ```
   python -m src fetch --cycle 2603
   ```
2. Run `New-SRDParser` so the cycle working directory contains `out.json`.
3. Run the archiver:
   ```
   python -m src archive --cycle 2603
   ```
4. Review and commit in `airac-data`.

---

## Error messages

| Message | Cause | Fix |
|---|---|---|
| `Required config key 'workspace_base' is missing or empty` | `config.local.yaml` does not set `workspace_base` | Add `workspace_base` to `config.local.yaml` |
| `Required config key 'archive_repo' is missing or empty` | `config.local.yaml` does not set `archive_repo` | Add `archive_repo` to `config.local.yaml` |
| `Only X of Y expected files found` | The working directory is likely wrong or nearly empty | Check `workspace_base` and the cycle ident |
| `git add failed in ...` | `archive_repo` is not a git repository, or git is not on PATH | Ensure `archive_repo` points to your `airac-data` clone |

---

## Development

### Running tests

```
pytest
```

All tests use `pytest` and the standard library only. No live network calls are made.

### Project structure

```
src/
  airac.py       AIRAC cycle date arithmetic
  archiver.py    Core flat-file archive, manifest, and git-stage logic
  cli.py         Click command-line interface
  config.py      YAML config loader
  __main__.py    `python -m src` entry point
tests/
  test_airac.py
  test_archiver.py
  test_cli.py
  test_config.py
config.yaml        Default config (safe to commit)
config.local.yaml  Machine-specific overrides (gitignored)
```
