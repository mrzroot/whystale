"""Declarative knowledge tables. Data, not logic: edit these to extend whystale.

Anything listed as "auto" below is marked *probable*, never certain: whystale
only suppresses a restart recommendation to a lower-confidence ``maybe`` and
says why. Entries come from tool documentation; verify against your versions.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Dict, List, Optional, Set

from .model import MAYBE, STALE

# ---------------------------------------------------------------------------
# File classes: files a *running process* reads once, at startup.
# class -> (level when changed after process start, human label, basename globs)
# ---------------------------------------------------------------------------
FILE_CLASSES: Dict[str, Dict[str, object]] = {
    "env": {
        "level": STALE,
        "label": "env file",
        "globs": [".env", ".env.*", ".flaskenv"],
    },
    "lockfile": {
        "level": STALE,
        "label": "lockfile",
        "globs": [
            "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
            "bun.lock", "bun.lockb", "poetry.lock", "uv.lock", "Pipfile.lock",
            "Cargo.lock", "Gemfile.lock", "composer.lock",
        ],
    },
    "config": {
        "level": STALE,
        "label": "framework config",
        "globs": [
            "next.config.*", "vite.config.*", "nuxt.config.*", "astro.config.*",
            "webpack.config.*", "tailwind.config.*", "postcss.config.*",
            "svelte.config.*", "rollup.config.*", "nodemon.json",
        ],
    },
    "pysettings": {
        "level": STALE,
        "label": "Python settings module",
        "globs": ["settings.py", "local_settings.py"],
    },
    "manifest": {
        "level": MAYBE,
        "label": "project manifest",
        "globs": [
            "package.json", "pyproject.toml", "requirements*.txt", "Pipfile",
            "Cargo.toml", "go.mod", "Gemfile", "composer.json",
        ],
    },
    "docker": {
        "level": STALE,
        "label": "container definition",
        "globs": ["docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml", "Dockerfile", "Dockerfile.*"],
    },
}

# Names that look like env files but are templates, never read at runtime.
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".tpl")

# Classes that only make sense for some runners.
CLASS_ONLY_FOR_RUNNER = {"docker": "docker compose"}


def classify_file(name: str, runner: Optional[str] = None) -> Optional[str]:
    """Return the file class of a basename, or None."""
    for cls, spec in FILE_CLASSES.items():
        for g in spec["globs"]:  # type: ignore[union-attr]
            if fnmatch.fnmatchcase(name, g):
                if cls == "env" and name.endswith(ENV_TEMPLATE_SUFFIXES):
                    return None
                need = CLASS_ONLY_FOR_RUNNER.get(cls)
                if need and runner != need:
                    return None
                return cls
    return None


# ---------------------------------------------------------------------------
# Runner knowledge: matched against the command line.
#   auto = file classes the runner probably handles without a restart
# ---------------------------------------------------------------------------
RUNNERS: List[Dict[str, object]] = [
    {
        "name": "Vite dev server",
        "match": r"(?:^|[\s/])vite(?:\.js|\.mjs)?(?:\s|$)",
        "auto": {"config", "env"},
        "why": "Vite restarts its dev server in-process when vite.config.* or .env files change",
    },
    {
        "name": "Next.js dev server",
        "match": r"next-server|(?:^|[\s/])next(?:\.js)?\s+dev(?:\s|$)|next/dist/bin/next\s+dev",
        "auto": {"config", "env"},
        "why": "`next dev` usually reloads next.config.* and .env files, but not reliably (see vercel/next.js discussion 59558)",
    },
    {
        "name": "Nuxt dev server",
        "match": r"(?:^|[\s/])(?:nuxi|nuxt)(?:\.mjs)?\s+dev(?:\s|$)",
        "auto": {"config", "env"},
        "why": "Nuxt dev restarts itself when nuxt.config.* or .env change",
    },
    {
        "name": "Astro dev server",
        "match": r"(?:^|[\s/])astro(?:\.js|\.mjs)?\s+dev(?:\s|$)",
        "auto": {"config"},
        "why": "Astro dev restarts when astro.config.* changes",
    },
    {
        "name": "Django runserver",
        "match": r"manage\.py\s+runserver(?!.*--noreload)",
        "auto": {"pysettings"},
        "why": "runserver's autoreloader re-imports changed Python modules (settings.py included) but does not re-read .env or lockfiles",
    },
    {
        "name": "Python server with --reload/--debug",
        "match": r"(?:uvicorn|gunicorn|hypercorn|flask|granian)\b.*--(?:reload|debug)\b",
        "auto": {"pysettings"},
        "why": "the reloader restarts on changed Python files, not on .env or lockfile changes",
    },
    {
        "name": "docker compose",
        "match": r"docker[- ]compose|docker\s+compose",
        "auto": set(),
        "why": "",
    },
]


def match_runner(cmdline: str) -> Optional[Dict[str, object]]:
    for r in RUNNERS:
        if re.search(str(r["match"]), cmdline):
            return r
    return None


# ---------------------------------------------------------------------------
# Which processes count as "something that serves or runs your project"
# ---------------------------------------------------------------------------
RUNTIME_COMMS = {
    "node", "nodejs", "deno", "bun", "npm", "npx", "yarn", "pnpm", "tsx", "ts-node",
    "nodemon", "vite", "next", "next-server", "nuxt", "nuxi", "astro", "webpack",
    "webpack-dev-server", "esbuild", "parcel", "remix", "gatsby", "rails", "puma",
    "ruby", "bundle", "php", "artisan", "java", "gradle", "mvn", "dotnet", "cargo",
    "uvicorn", "gunicorn", "hypercorn", "flask", "django-admin", "celery", "air",
    "hugo", "jekyll", "mkdocs", "docker-compose", "docker", "uwsgi", "daphne",
    "uv", "poetry", "pipenv", "streamlit", "jupyter", "jupyter-lab", "jupyter-notebook", "granian",
}
RUNTIME_PREFIXES = ("python", "node", "ruby", "php", "java", "pypy")

# Interactive / tooling processes that happen to sit in the project directory.
IGNORED_COMMS = {
    "bash", "zsh", "sh", "dash", "fish", "ksh", "tcsh", "csh", "nu", "pwsh",
    "tmux", "screen", "sudo", "su", "login", "ssh", "sshd", "vim", "nvim", "vi",
    "nano", "emacs", "less", "more", "man", "git", "ps", "lsof", "whystale",
    "watch", "tail", "top", "htop", "code", "cursor", "pager", "fzf", "make",
}
SHELL_COMMS = {"bash", "zsh", "sh", "dash", "fish", "ksh", "tcsh", "csh", "nu", "pwsh"}


def is_runtime(comm: str) -> bool:
    c = comm.lower()
    return c in RUNTIME_COMMS or c.startswith(RUNTIME_PREFIXES)


# ---------------------------------------------------------------------------
# Build output / sources
# ---------------------------------------------------------------------------
NODE_OUTPUT_DIRS = ["dist", "build", "out", ".next", ".nuxt", ".output", ".svelte-kit"]
SOURCE_EXTS = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte",
    ".astro", ".css", ".scss", ".sass", ".less", ".html", ".htm",
}
DATA_EXT_DIRS = {".json": ("src", "app", "pages", "public", "content", "locales")}
ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".json", ".txt"}
ASSET_DIRS = ("public", "static")
TEST_DIR_NAMES = {"__tests__", "tests", "test", "e2e", "cypress", "playwright", "__mocks__", ".storybook"}
TEST_NAME_RE = re.compile(r"\.(test|spec|stories|story|e2e)\.[a-z]+$")

PROTO_GENERATED = [
    "{stem}_pb2.py", "{stem}_pb2.pyi", "{stem}_pb2_grpc.py", "{stem}_pb.js", "{stem}_pb.d.ts",
    "{stem}_pb.ts", "{stem}_grpc_pb.js", "{stem}.pb.go", "{stem}_grpc.pb.go", "{stem}_connect.ts",
    "{stem}_connect.js",
]

OPENAPI_SPEC_NAMES = ("openapi", "swagger")
OPENAPI_SPEC_EXTS = (".json", ".yaml", ".yml")
OPENAPI_SPEC_DIRS = ("", "docs", "api", "spec", "specs", "openapi")
OPENAPI_GEN_DIRS = [
    "src/generated", "generated", "src/api/generated", "src/gen", "gen",
    "src/__generated__", "client/generated", "src/client/generated",
]
OPENAPI_MARKERS = ("openapi", "swagger")

LOCKFILE_PM = {
    "package-lock.json": "npm", "npm-shrinkwrap.json": "npm", "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm", "bun.lock": "bun", "bun.lockb": "bun",
}


def pm_run(pm: str, script: str) -> str:
    return {"npm": "npm run %s", "yarn": "yarn %s", "pnpm": "pnpm run %s", "bun": "bun run %s"}.get(pm, "npm run %s") % script


def pm_exec(pm: str, tool: str) -> str:
    return {"npm": "npx %s", "yarn": "yarn %s", "pnpm": "pnpm exec %s", "bun": "bunx %s"}.get(pm, "npx %s") % tool


def pm_install(pm: str, frozen: bool = True) -> str:
    return {
        "npm": "npm ci" if frozen else "npm install",
        "yarn": "yarn install --frozen-lockfile" if frozen else "yarn install",
        "pnpm": "pnpm install --frozen-lockfile" if frozen else "pnpm install",
        "bun": "bun install --frozen-lockfile" if frozen else "bun install",
    }.get(pm, "npm ci")
