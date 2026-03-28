# AIRAC Archiver — Session Status Summary

---

## Session 1 — 2026-03-11

**Repository created** by extracting the archiver from `airac-data-fetcher`.

- `src/archiver.py` — zip-based archiving of 7 required files
- `src/config.py` — YAML config loader
- `src/cli.py` — Click CLI with `archive` command
- `src/airac.py` — AIRAC cycle date arithmetic (from fetcher)
- 110 tests, all passing
- Butler documentation created

---

## Session 10 — 2026-03-20 (v2, PR #2)

**Major refactor: flat files, denylist, checksums.**

- Replaced zip archiving with flat-file copy
- Added denylist-based file filtering (exclude known non-canonical files)
- Added SHA256 checksums in `manifest.md`
- Added warn-on-missing (yellow CLI), nonexistent-dir guard, duplicate-basename guard
- Clean re-archive (`rmtree` before copy) — stale files removed automatically
- Ari review incorporated: rollback guarantee, error visibility improvements
- PR #2 merged to `main`

---

## Session 28 — 2026-03-28 (v3, PR #4)

**Allowlist + versioned out.json (issue #3).**

- Switched from denylist to explicit allowlist: `in.json`, `out.json`, `Routes.csv`, `Notes.csv`, `*.sct`
- `out.json` renamed to `out.{cycle}.{n}.json` with monotonic version numbering
- Existing versioned files preserved across re-archives using atomic temp-dir strategy (`shutil.move` + `tempfile.mkdtemp`)
- Ari review incorporated: temp-dir robustness (replaced in-memory `read_bytes`), gap-in-versions test, preserve-without-out test, Windows backslash path traversal edge case (Go side)
- Documentation and CLI docstrings updated to reflect flat-file + allowlist reality
- `airac-data` re-archived for AIRAC 2603: 14 non-allowlisted files cleaned, `out.json` versioned to `out.2603.1.json`
- UKVFPCAPI filename validation regex updated to accept versioned filenames (PR #93 merged)
- PR #4 merged, issue #3 closed
- All GitHub issues now closed
