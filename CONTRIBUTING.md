# Contributing

Thanks for helping! whystale is small on purpose: standard library only, read-only, no network.

```sh
git clone https://github.com/mrzroot/whystale && cd whystale
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
python -m whystale --demo
```

Ground rules

- **No new runtime dependencies**, and Python 3.9 must keep working (CI runs 3.9 to 3.13).
- **No false claims.** A new detection needs a test for the stale case, a test for the fresh case, and
  a test for the equal-timestamp edge. Prefer a content check that can clear a finding over a
  heavier heuristic that can only add findings.
- **Knowledge lives in tables** (`src/whystale/knowledge.py`): file classes, runners that auto-reload,
  conventional output directories. If you add a runner to the auto-reload table, link its documentation
  in the PR and mark it "probable".
- Add your change to `CHANGELOG.md`.
- Found a tool that already does this? Open an issue; it will be linked in the README.

Reporting a false positive: run `whystale --json -v` and attach the finding plus how the files were
created or edited.
