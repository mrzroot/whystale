<!-- Paste into AGENTS.md, CLAUDE.md, .cursorrules or your agent's rules file. Requires `pipx install whystale` (or `uvx whystale`). -->

## Before you say "it still fails" or "done"

Stale state is the most common reason a correct change "does not work". Before debugging further, and
before declaring a task done, run:

```sh
whystale --markdown --no-fail
```

- If it lists a **stale** item, run the printed `fix:` command (restart the server, `npm ci`, rebuild,
  regenerate the client) and re-test **before** changing any code.
- **maybe** items are heuristics: mention them, but do not treat them as proof.
- `whystale` is read-only. It never edits files. Do not "fix" a stale finding by editing source.
- In CI or a pre-finish hook, use `whystale` without `--no-fail`: it exits `3` while anything is stale.
