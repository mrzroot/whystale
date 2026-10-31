<p align="center"><img src=".github/assets/banner.svg" alt="whystale: Changed the code but it still acts old? Find what is stale." width="100%"></p>

<p align="center">
  <a href="https://github.com/mrzroot/whystale/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/mrzroot/whystale?style=flat-square"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/mrzroot/whystale?style=flat-square"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen?style=flat-square">
  <a href="https://github.com/mrzroot/whystale/commits"><img alt="Last commit" src="https://img.shields.io/github/last-commit/mrzroot/whystale?style=flat-square"></a>
</p>

<p align="center"><a href="https://mrzroot.github.io/whystale/">Website</a> · <a href="README.fa.md">فارسی</a> · <a href="CHANGELOG.md">Changelog</a> · <a href="CONTRIBUTING.md">Contributing</a></p>

# whystale

**Changed the code but it still behaves the old way?** `whystale` finds the stale thing: a dev server
that started before `.env` or the lockfile changed, a build older than its sources, installed
dependencies older than the lockfile, generated code older than its schema. It tells you *why* it
thinks so and prints the **exact command** to refresh it.


![python](https://img.shields.io/badge/python-3.9%E2%80%933.13-blue)
![deps](https://img.shields.io/badge/dependencies-none-brightgreen)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

English | [فارسی](README.fa.md)

```text
$ whystale
whystale 0.1.0 · /home/me/shop-web
checked 214 files (git) · 3 process(es) in project (proc)

STALE (3)

✗ process · Next.js dev server — `next-server (v14.2.3)` (pid 41872 :3000)
    why:    started 17:02:11, but 1 file(s) it reads at startup changed afterwards (latest 3m 29s later)
    newer:  .env.local (env file) changed 3m 29s after start
    ...
    fix:    kill 41872
            cd /home/me/shop-web && npm run dev

✗ deps · node_modules installed state (.package-lock.json) is older than package-lock.json
    why:    package-lock.json was modified 2h 00m after the last install; 1 package(s) differ, e.g. express locked 4.19.2 / installed 4.18.2
    fix:    npm ci

✗ generated · Prisma client is older than its schema
    fix:    npx prisma generate
```

(Illustrative layout. The real, unedited output of the offline demo is in [docs/demo.txt](docs/demo.txt).)

## Why

The fix is correct, but "it didn't work". The usual causes are boring: the server was never restarted
after `.env` or config changed, `dist/` was not rebuilt, `node_modules` was not reinstalled after a
`git pull`, a generated client (Prisma, GraphQL, protobuf, OpenAPI) was not regenerated. Frameworks
differ in what they hot-reload, so people (and AI coding agents) guess, and then "fix" correct code
again and again. `whystale` replaces the guess with a read-only, cross-ecosystem report of *what is older
than what it was built from*.

## Install

Python 3.9+, no dependencies. Linux and macOS (Windows is not supported).

```sh
pipx install whystale          # once published to PyPI
# until then, straight from GitHub:
pipx install git+https://github.com/mrzroot/whystale
# or run without installing:
uvx --from git+https://github.com/mrzroot/whystale whystale --demo
# or from a clone:
pip install -e .
```

## Usage

```sh
whystale                  # scan the current directory
whystale ~/code/shop      # scan another project
whystale --json           # machine-readable (schema below)
whystale --markdown       # paste-ready report for an AI agent
whystale --watch          # re-scan every 2 s and print transitions (also: --watch 5)
whystale --only deps,generated
whystale --strict         # "maybe" findings also fail the exit code
whystale --no-fail        # always exit 0
whystale -v               # also list items that looked stale by time but were cleared by content
whystale --demo           # offline scenario: real files + a real spawned server
```

**Exit codes:** `0` nothing stale · `3` something is stale · `2` usage or config error.
Findings come in two levels: `stale` (solid evidence) and `maybe` (heuristic; for example a process that
its framework probably reloads on its own). Only `stale` fails the exit code unless you pass `--strict`.

Try it in ten seconds, no project needed: `whystale --demo` builds a temp project, starts a real server that
reads `.env` once, edits `.env` and the lockfile, shows the server still serving the old value, and runs the
scan.

### Use it as a hook for agents and CI

```sh
# CI step or pre-"done" check: fails (exit 3) while anything is stale
whystale --only deps,artifacts,generated

# give an agent the report as context
whystale --markdown --no-fail > /tmp/stale.md
```

A ready-to-paste instruction for `AGENTS.md` / `CLAUDE.md` / Cursor rules is in
[docs/AGENTS.snippet.md](docs/AGENTS.snippet.md).

## What it detects

| Check | Evidence used | Fix it prints |
|---|---|---|
| **Process started before a file it reads changed.** Only processes whose working directory is inside the project and that look like runtimes/servers (node, python, ruby, php, java, bun, deno, cargo, uvicorn, `docker compose`, anything listening on a TCP port, plus `process.include` in config). Looks at `.env*` (not `.env.example`/`.sample`/`.template`), lockfiles, framework configs (`next/vite/nuxt/astro/webpack/tailwind/postcss/svelte/rollup.config.*`, `nodemon.json`), `settings.py`, manifests (`package.json`, `pyproject.toml`, `requirements*.txt`, ... as `maybe`), `docker-compose*.yml`/`Dockerfile` (only for `docker compose`). | process start time vs file mtimes; `.env` values already in the process environment clear the finding (Linux) | `kill PID` and the original command line, run from its cwd |
| **Build output older than sources.** `dist build out .next .nuxt .output .svelte-kit` for Node packages (nested packages handled), `target/` for Rust. Tests, stories, lint/test configs, `.d.ts`, docs and git-ignored files do not count as sources. | newest output mtime vs newest source mtimes | `npm/pnpm/yarn/bun run build` (from `package.json` + lockfile), `cargo build [--release]` |
| **Installed deps older than the lockfile.** `node_modules` vs `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`; virtualenvs (`.venv`, `venv`, `env`, `.env/`, `$VIRTUAL_ENV`) vs `requirements*.txt`, `poetry.lock`, `uv.lock`, `Pipfile.lock`. | mtimes, then **versions**: npm lock vs npm's hidden lockfile; pnpm lock vs pnpm's stored copy; pins/locked versions vs installed `*.dist-info` | `npm ci`, `pnpm install --frozen-lockfile`, `yarn install --frozen-lockfile`, `uv sync`, `poetry install`, `pipenv sync`, `pip install -r ...` |
| **Generated code older than its schema.** Prisma (`*.prisma` vs the generated client, custom `output` honoured), protobuf (`x.proto` vs `x_pb2.py`, `x.pb.go`, `x_pb.ts`, ...), OpenAPI (`openapi|swagger.*` vs conventional client dirs that contain an openapi/swagger marker), GraphQL Code Generator (`codegen.yml` `generates:` vs schema/documents), plus your own rules. | mtimes; Prisma also compares the schema stored inside the client | `npx prisma generate`, `buf generate`, your `package.json` script / Makefile target when one is recognisable, otherwise an honest "set `command` in `.whystale.toml`" |

### How it avoids false positives

A file must be **newer than the thing built from it by a grace period** (2 s for processes, 5 s for
files) before anything is reported. After that, cheap content checks can only *clear* a finding:

- `.env` touched but every value is already in the process's startup environment: cleared (Linux).
- Lockfile touched (`touch`, branch switch) but installed versions match it: cleared.
- Prisma schema touched but identical to the schema the client was generated from: cleared.
- `requirements.txt` edited but installed versions satisfy it: cleared.
- Processes that auto-reload (Vite, Next.js, Nuxt, Astro, Django `runserver`, `--reload` servers) are
  downgraded to `maybe`, with the reason.
- Git is used when available (`git ls-files --cached --others --exclude-standard`) so ignored files never
  count; without git a built-in `.gitignore` approximation is used.
- A clean project (outputs fresher than inputs) must produce zero findings. This is tested over random
  mtimes.

Use `whystale -v` to see what was cleared and why.

## Configuration

Optional `.whystale.toml` in the project root (or `--config FILE`):

```toml
[settings]
grace_seconds = 2        # process start vs file mtime
fs_grace_seconds = 5     # file vs file (builds, deps, codegen)

[ignore]
paths = ["legacy/**", "*.generated.ts"]   # globs relative to the project; ignored everywhere
processes = ["tailscaled", "my-editor-helper"]   # substrings of the command line

[process]
include = ["mydaemon"]   # treat these commands as servers even if they are not a known runtime

[checks]                 # switch whole checks off
deps = false

# your own source -> output pairs
[[generated]]
name = "API client"
sources = ["api/spec.yaml"]
outputs = ["src/client/**"]
command = "make client"

[[artifact]]
name = "docs site"
sources = ["docs/**/*.md", "mkdocs.yml"]
outputs = ["site/**"]
command = "mkdocs build"
```

A custom rule reports when the newest source is newer than the newest output (a single fresh output
clears it, so tools that skip unchanged files do not cause false alarms).

## JSON output

`whystale --json` prints one object:

```json
{
  "tool": "whystale", "version": "0.1.0", "project": "/abs/path", "generated_at": "...",
  "stale": true,
  "summary": {"stale": 2, "maybe": 1, "ignored": 0},
  "exit_code_if_stale": 3,
  "findings": [{
    "kind": "process|deps|artifact|generated", "level": "stale|maybe",
    "key": "stable id", "subject": "...", "reason": "...",
    "evidence": "mtime|content|process-start",
    "fix": ["exact command", "..."],
    "older_than": [{"path": "...", "what": "...", "changed": "ISO time"}],
    "notes": [], "details": {}
  }],
  "ignored": [], "notes": [], "scanned": {}
}
```

## How it works

1. **List files** with git if available, otherwise walk the tree with a `.gitignore` approximation.
2. **Processes**: `/proc` on Linux (`stat` start time = boot time + ticks, `cwd`, `cmdline`, listening sockets
   via `/proc/net/tcp` + `fd` inodes); `ps -axo pid=,ppid=,lstart=,command=` plus `lsof -d cwd` elsewhere.
   Processes in the project are grouped with their wrappers (`npm run dev` -> `sh` -> `node vite`) into one
   finding, judged by the newest member (so a `nodemon` child restarted after the edit is fine). The key of a
   finding includes the start time, so a recycled PID is a different process.
3. **Pairs** are plain data in `src/whystale/knowledge.py` (file classes, runners that reload themselves,
   output directories) and small functions per ecosystem. Everything is read-only: no network, no daemons,
   nothing is written.

Source layout: `checks_process.py`, `checks_deps.py`, `checks_artifacts.py`, `checks_generated.py`,
`procs.py`, `knowledge.py`, `render.py`, `demo.py`.

## Limits (please read)

whystale reports **evidence, not proof**. Known limits of v0.1:

- **Timestamps.** Everything starts from modification times. Editors, formatters, `touch`, `git checkout`
  or restoring from a cache can move an mtime without changing content; the content checks above clear the
  common cases but not all (build output and generated code other than Prisma have no content check).
  Process start times on Linux come from `/proc` with roughly one second of precision, hence the grace
  period. Large clock changes (NTP jumps, VM suspend) can skew them.
- **Processes.** Only processes whose *current working directory* is inside the project are seen. A server
  started elsewhere, a process inside a Docker container, or one that changed its cwd is invisible.
  Interactive shells, editors and common tools are skipped; a Node-based tool running in the project
  (an agent CLI, for example) can look like a server: add it to `ignore.processes`.
  Edits to *source code* are not compared with process start in v0.1 (a plain `node server.js` that
  needs a restart after a `src/` edit is not reported), because many processes legitimately re-read
  source on every request.
- **Auto-reload table.** "Probably reloads on its own" entries come from tool documentation and are
  deliberately conservative (`maybe`, never silent). Versions differ; Next.js is known to be unreliable here
  ([vercel/next.js discussion 59558](https://github.com/vercel/next.js/discussions/59558)).
- **Environment check** reads `/proc/PID/environ`, so it is Linux-only and can only *prove* freshness,
  never staleness (frameworks that load `.env` in-process leave no trace).
- **Builds.** Node (`dist build out .next .nuxt .output .svelte-kit`) and Rust (`target/`, newest profile
  only; `cargo check` does not count as a build) only. Python wheels, Go, Java/Gradle/Maven etc. are not
  built in: add a `[[artifact]]` rule.
- **Deps.** `yarn.lock` is judged by mtime only (`maybe`). `bun`, `composer`, `bundler`, Cargo and Go module
  caches are not checked. Python environments are only found when they live in the project (`.venv`,
  `venv`, `env`, `.env/`) or `$VIRTUAL_ENV` points inside it; only `==` pins and locked versions are
  compared, markers are not evaluated, and "missing package" alone is only `maybe` (it may be an optional
  group). npm workspaces / `--omit=dev` installs are handled for dev/optional packages, but unusual
  layouts may differ.
- **Generated code.** Prisma output is found at `node_modules/.prisma/client`, next to the resolved
  `@prisma/client` (pnpm), or at a custom `output`. Protobuf outputs are matched by file name
  (ambiguous names become `maybe`). OpenAPI needs a conventional directory containing an
  `openapi`/`swagger` marker. GraphQL codegen is read from `codegen.yml|yaml` only (not `codegen.ts`).
  File-based database migrations (for example SQLite) are **not** checked.
- **Platforms.** Linux is the primary target. The macOS `ps`/`lsof` path is unit-tested against recorded
  output and the same code path is exercised on Linux (`WHYSTALE_BACKEND=ps`); CI includes a macOS job
  but the author has not run it on a real Mac yet. Windows is unsupported.
- Trees larger than 200 000 files are truncated (and the report says so).

Validated by hand against real tools while developing: npm 11 (`node_modules/.package-lock.json`, including `npm ci --omit=dev`),
Prisma 5.22 (`prisma generate` output), Vite 8 (it really does restart itself on `.env` changes, which is
why it is `maybe`), and a `uv`-created virtualenv.

## How it compares

As of October 2026 I could not find another open-source tool that does this combination (a read-only,
cross-ecosystem "what is older than what it was built from" report tied to running processes). If you know
one, please open an issue and I will link it here. Closest things I know of:

| Tool | What it does | How whystale differs |
|---|---|---|
| [`devpilot`](https://github.com/benseverndev-oss/devpilot) | Supervises dev servers (reload, health, file changes). | Does not judge staleness from `.env`/lockfile/config/artifact timestamps; whystale is a read-only report, not a supervisor. |
| Framework watchers: [`nodemon`](https://github.com/remy/nodemon), [Vite](https://vite.dev/), Next.js ([discussion](https://github.com/vercel/next.js/discussions/59558)) | Each reloads on its own set of files. | None tells you what did *not* reload; whystale does, across stacks. |
| [`needrestart`](https://github.com/liske/needrestart) (Debian) | Finds system services still using outdated shared libraries. | System libraries only; whystale looks at your project's env, lockfiles, builds and codegen. |
| `npm ci` / `uv sync --locked` / `pnpm install --frozen-lockfile` ([docs](https://docs.npmjs.com/cli/commands/npm-ci)) | Enforce lockfile sync when you run them. | They do not reveal that a running process, a build or a generated client is behind; whystale tells you when to run them. |

## Development

```sh
pip install -e ".[test]"
python -m pytest            # unit tests, real-process tests (Linux), demo end to end
python -m whystale --demo
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Mohammadreza Zare ([@mrzroot](https://github.com/mrzroot)).
