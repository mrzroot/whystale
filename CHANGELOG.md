# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-18

First release.

### Added
- Stale **processes**: processes whose working directory is inside the project, started before an
  `.env*`, lockfile, framework config, Python settings module or manifest changed
  (`/proc` on Linux, `ps` + `lsof` elsewhere). Wrapper chains such as `npm run dev` are reported once.
  A small, documented table of runners that reload themselves (Vite, Next.js, Nuxt, Astro, Django
  `runserver`, `--reload` servers) downgrades those findings to `maybe`.
- Stale **build output**: `dist/ build/ out/ .next/ .nuxt/ .output/ .svelte-kit/` (Node projects, nested
  packages included) and Rust `target/` older than their sources.
- Stale **installed dependencies**: `node_modules` vs `package-lock.json` (version comparison against
  npm's hidden lockfile), `pnpm-lock.yaml` (compared with pnpm's stored copy), `yarn.lock` (mtime only);
  Python virtualenvs vs `requirements*.txt`, `poetry.lock`, `uv.lock`, `Pipfile.lock`.
- Stale **generated code**: Prisma, protobuf, OpenAPI client directories, GraphQL Code Generator
  (`codegen.yml`) and user-defined `[[generated]]` / `[[artifact]]` rules in `.whystale.toml`.
- Output: text, `--json`, `--markdown`; `--watch`; `--demo`; `--only`; `--strict`; `--no-fail`.
- Exit code `3` when something is stale, for CI and agent hooks.
- Content checks that clear false positives: `.env` values already in the process environment,
  lockfile touched but installed versions equal, Prisma schema identical to the generated copy,
  requirement pins already satisfied.
