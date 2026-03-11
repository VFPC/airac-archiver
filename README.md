# airac-archiver

Packages prepared AIRAC cycle data files into a versioned zip archive and stages them in the [airac-data](https://github.com/VFPC/airac-data) repository for review before committing.

Run this tool after the SRD Parser has produced `out.json` and all seven required files are present in the cycle working directory.

---

## Related repositories

| Repository | Purpose |
|---|---|
| [airac-data-fetcher](https://github.com/VFPC/airac-data-fetcher) | Downloads source files for each AIRAC cycle |
| [airac-data](https://github.com/VFPC/airac-data) | Archive of all packaged cycle data |
| **airac-archiver** | This tool — packages and stages data into airac-data |

---

## Prerequisites

- Python 3.11 or newer
- A local clone of [airac-data](https://github.com/VFPC/airac-data)
- All seven required files present in the cycle working directory (see below)

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

`config.local.yaml` is gitignored — it is never committed to the repository.

| Key | Description |
|---|---|
| `workspace_base` | Directory containing per-cycle working directories (e.g. `vFPC 2603\`) |
| `archive_repo` | Path to your local clone of the `airac-data` repository |

---

## Required files

The archiver expects all seven files to be present in the cycle directory before running.  The cycle directory is `{workspace_base}\vFPC YYNN\` (e.g. `vFPC 2603\`).

| File | Source |
|---|---|
| `Routes.csv` | SRD Parser route input |
| `Notes.csv` | SRD Parser notes input |
| `EG-ENR-3.2-en-GB.html` | AIP Parser ENR 3.2 input |
| `EG-ENR-3.3-en-GB.html` | AIP Parser ENR 3.3 input |
| `UK_{YYYY}_{NN}.sct` | VATSIM UK sector file |
| `in.json` | SRD Parser config (copied forward by airac-data-fetcher) |
| `out.json` | SRD Parser output — only present after a successful parser run |

The first six files are placed in the working directory by `airac-data-fetcher`. `out.json` is written by the SRD Parser.

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

The `--cycle` argument is a four-digit AIRAC ident: two-digit year followed by two-digit cycle number (e.g. `2603` = cycle 3 of 2026).

---

## What happens when you run the archiver

1. **Validates** that all seven required files exist in `{workspace_base}\vFPC YYNN\`.
2. **Creates** `{archive_repo}\vFPC YYNN\vFPC YYNN.zip` containing all seven files in a flat layout.
3. **Writes** `{archive_repo}\vFPC YYNN\manifest.md` recording cycle dates, the timestamp, and your OS username.
4. **Stages** both files with `git add` in the `airac-data` repository.

After the tool completes, review the staged changes in the `airac-data` repository and commit when satisfied:

```
cd path\to\airac-data
git diff --staged
git commit -m "Add vFPC 2603 archive"
git push
```

---

## Typical workflow

1. Run `airac-data-fetcher` to download source files:
   ```
   python -m src fetch --cycle 2603
   ```
2. Run the SRD Parser — this writes `out.json` into the cycle working directory.
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
| `Cannot archive cycle YYNN — the following required files are missing` | One or more required files are absent | Check the cycle directory; ensure fetcher ran and SRD Parser produced `out.json` |
| `git add failed in ...` | `archive_repo` is not a git repository, or git is not on PATH | Ensure `archive_repo` points to your `airac-data` clone |

---

## Development

### Running tests

```
pytest
```

All tests use `pytest` and the standard library only — no live network calls.

### Project structure

```
src/
  airac.py       — AIRAC cycle date arithmetic
  archiver.py    — Core zip/manifest/git-stage logic
  cli.py         — Click command-line interface
  config.py      — YAML config loader
  __main__.py    — python -m src entry point
tests/
  test_airac.py
  test_archiver.py
  test_cli.py
  test_config.py
config.yaml        — Default config (safe to commit)
config.local.yaml  — Machine-specific overrides (gitignored)
```
