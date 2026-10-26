"""Stale generated code: Prisma, protobuf, OpenAPI, GraphQL codegen and custom rules."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from . import knowledge as K
from .config import Config
from .fsutil import Project, expand_globs, fmt_delta, fmt_time, iso, newest_in_dir, read_text
from .model import ARTIFACT, GENERATED, MAYBE, STALE, Finding
from .pkgutil import detect_pm, infer_make_target, infer_script


def _dir_of(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _cd(d: str, cmd: str) -> str:
    return cmd if not d else "cd %s && %s" % (d, cmd)


def _gen_finding(kind: str, key: str, subject: str, src_rel: str, src_m: float, out_rel: str, out_m: float,
                 fix: List[str], evidence: str = "mtime", level: str = STALE, notes: Optional[List[str]] = None,
                 extra_reason: str = "", details: Optional[dict] = None) -> Finding:
    reason = "%s changed %s after %s was generated (%s)" % (src_rel, fmt_delta(src_m - out_m), out_rel, fmt_time(out_m))
    if extra_reason:
        reason += "; " + extra_reason
    d = {"source": src_rel, "output": out_rel}
    d.update(details or {})
    return Finding(
        kind=kind, level=level, key=key, subject=subject, reason=reason, evidence=evidence, fix=fix,
        older_than=[{"path": src_rel, "what": "schema/source", "changed": iso(src_m), "seconds_after_generation": round(src_m - out_m, 1)}],
        notes=notes or [], details=d,
    )


# ---------------------------------------------------------------------------
# Prisma
# ---------------------------------------------------------------------------
def prisma_output_dir(schema_text: str) -> Optional[str]:
    """Custom `output` of the client generator, if any (relative to the schema)."""
    for m in re.finditer(r"generator\s+\w+\s*\{(.*?)\}", schema_text, re.S):
        body = m.group(1)
        if re.search(r'provider\s*=\s*"prisma-client(?:-js)?"', body):
            o = re.search(r'output\s*=\s*"([^"]+)"', body)
            return o.group(1) if o else None
    return None


def _norm(t: str) -> str:
    # Prisma re-formats the schema it stores next to the client (blank lines), so ignore all whitespace.
    return " ".join(t.split())


def check_prisma(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    ignored: List[dict] = []
    schemas = [f for f in project.files if f.endswith(".prisma")]
    by_dir: Dict[str, List[str]] = {}
    for f in schemas:
        by_dir.setdefault(_dir_of(f), []).append(f)
    for sdir, files in sorted(by_dir.items()):
        newest_rel = max(files, key=lambda f: project.mtime(f) or 0)
        src_m = project.mtime(newest_rel)
        if src_m is None:
            continue
        # package dir: nearest ancestor with node_modules
        cur = sdir
        pkg = None
        while True:
            if os.path.isdir(project.abs((cur + "/" if cur else "") + "node_modules")):
                pkg = cur
                break
            if not cur:
                break
            cur = _dir_of(cur)
        if pkg is None:
            continue
        nm = project.abs((pkg + "/" if pkg else "") + "node_modules")
        main_schema = next((f for f in files if f.endswith("schema.prisma")), files[0])
        text = read_text(project.abs(main_schema)) or ""
        custom = prisma_output_dir(text)
        out_dirs: List[str] = []
        copy_path: Optional[str] = None
        if custom:
            out_dirs.append(os.path.normpath(os.path.join(project.abs(sdir), custom)))
        else:
            out_dirs.append(os.path.join(nm, ".prisma", "client"))
            real = os.path.realpath(os.path.join(nm, "@prisma", "client"))
            alt = os.path.join(os.path.dirname(os.path.dirname(real)), ".prisma", "client")
            if alt not in out_dirs:
                out_dirs.append(alt)
        out_dir = next((o for o in out_dirs if os.path.isdir(o)), None)
        if out_dir is None:
            continue
        out_m, _, _ = newest_in_dir(out_dir, cap=2000)
        if out_m is None:
            continue
        if src_m <= out_m + cfg.fs_grace_seconds:
            continue
        out_rel = project.rel(out_dir) if out_dir.startswith(project.root) else out_dir
        copy_path = os.path.join(out_dir, "schema.prisma")
        evidence, level, extra = "mtime", STALE, ""
        if len(files) == 1 and os.path.isfile(copy_path):
            old = read_text(copy_path)
            if old is not None and _norm(old) == _norm(text):
                ignored.append({"kind": GENERATED, "subject": out_rel, "why": "%s is newer but identical to the schema the client was generated from" % main_schema})
                continue
            evidence, extra = "content", "the schema stored with the generated client differs from the current one"
        pm = detect_pm(project, pkg)
        script = infer_script(project, pkg, ["prisma generate"])
        if script:
            cmd = {"npm": "npm run %s", "yarn": "yarn %s", "pnpm": "pnpm run %s", "bun": "bun run %s"}[pm] % script
        else:
            cmd = K.pm_exec(pm, "prisma generate")
            default_locs = ((pkg + "/" if pkg else "") + "prisma/schema.prisma", (pkg + "/" if pkg else "") + "schema.prisma")
            if main_schema not in default_locs:
                cmd += " --schema " + main_schema[len(pkg) + 1 if pkg else 0:]
        findings.append(_gen_finding(GENERATED, "generated:prisma:" + sdir, "Prisma client is older than its schema",
                                     newest_rel, src_m, out_rel, out_m, [_cd(pkg, cmd)], evidence=evidence,
                                     level=level, extra_reason=extra))
    return findings, ignored


# ---------------------------------------------------------------------------
# protobuf
# ---------------------------------------------------------------------------
def check_protobuf(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    protos = [f for f in project.files if f.endswith(".proto")]
    if not protos:
        return findings, []
    # generated files are often git-ignored, so look at the real tree for them
    names: Dict[str, List[str]] = {}
    for dirpath, dirnames, filenames in os.walk(project.root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", ".venv", "venv", "__pycache__", "target")]
        for fn in filenames:
            if "_pb" in fn or ".pb." in fn or "_connect." in fn:
                names.setdefault(fn, []).append(project.rel(os.path.join(dirpath, fn)))
    stem_count: Dict[str, int] = {}
    for p in protos:
        stem_count[os.path.basename(p)[:-6]] = stem_count.get(os.path.basename(p)[:-6], 0) + 1
    for p in sorted(protos):
        stem = os.path.basename(p)[:-6]
        src_m = project.mtime(p)
        if src_m is None:
            continue
        cands: List[str] = []
        for pattern in K.PROTO_GENERATED:
            cands.extend(names.get(pattern.format(stem=stem), []))
        if not cands:
            continue
        stale_c, fresh_c = [], []
        for c in cands:
            m = project.mtime(c)
            if m is None:
                continue
            (stale_c if src_m > m + cfg.fs_grace_seconds else fresh_c).append((c, m))
        if not stale_c:
            continue
        d = _dir_of(p)
        if os.path.isfile(project.abs("buf.gen.yaml")):
            cmd = "buf generate"
        else:
            sc = infer_script(project, "", ["protoc", "buf generate", "grpc_tools"])
            if sc:
                cmd = {"npm": "npm run %s", "yarn": "yarn %s", "pnpm": "pnpm run %s", "bun": "bun run %s"}[detect_pm(project, "")] % sc
            else:
                tgt = infer_make_target(project, "", ["proto"])
                cmd = ("make " + tgt) if tgt else "# re-run your protoc/buf command (whystale cannot guess it; set it in .whystale.toml)"
        notes = []
        level = STALE
        if fresh_c or stem_count[stem] > 1:
            level = MAYBE
            if fresh_c:
                notes.append("other generated outputs for this proto are up to date: you may deliberately generate only some languages")
            if stem_count[stem] > 1:
                notes.append("several .proto files share the name %r; matching generated files by name is ambiguous" % stem)
        oldest = min(stale_c, key=lambda x: x[1])
        f = _gen_finding(GENERATED, "generated:proto:" + p, "protobuf output for %s is older than the .proto" % p, p, src_m,
                         oldest[0], oldest[1], [cmd], level=level, notes=notes,
                         details={"stale_outputs": [c for c, _ in stale_c]})
        findings.append(f)
    return findings, []


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------
def _marker_in_dir(path: str, markers: Tuple[str, ...]) -> bool:
    seen = 0
    for dp, dns, fns in os.walk(path):
        for fn in fns:
            seen += 1
            if seen > 200:
                return False
            try:
                with open(os.path.join(dp, fn), "rb") as fh:
                    head = fh.read(3000).lower()
            except OSError:
                continue
            if any(m.encode() in head for m in markers):
                return True
    return False


def check_openapi(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    specs = []
    for d in K.OPENAPI_SPEC_DIRS:
        for n in K.OPENAPI_SPEC_NAMES:
            for e in K.OPENAPI_SPEC_EXTS:
                rel = (d + "/" if d else "") + n + e
                if project.mtime(rel) is not None:
                    specs.append(rel)
    if not specs:
        return findings, []
    src_m, src_rel = max((project.mtime(s), s) for s in specs)  # type: ignore[type-var]
    for g in K.OPENAPI_GEN_DIRS:
        if not os.path.isdir(project.abs(g)) or project.is_ignored(g):
            continue
        if not _marker_in_dir(project.abs(g), K.OPENAPI_MARKERS):
            continue  # directory is not recognisably generated from an OpenAPI spec
        out_m, _, _ = newest_in_dir(project.abs(g), cap=5000)
        if out_m is None or src_m <= out_m + cfg.fs_grace_seconds:  # type: ignore[operator]
            continue
        sc = infer_script(project, "", ["openapi", "swagger", "orval"])
        if sc:
            cmd = {"npm": "npm run %s", "yarn": "yarn %s", "pnpm": "pnpm run %s", "bun": "bun run %s"}[detect_pm(project, "")] % sc
        else:
            tgt = infer_make_target(project, "", ["openapi", "client", "api"])
            cmd = ("make " + tgt) if tgt else "# re-run your OpenAPI client generator (set `command` via [[generated]] in .whystale.toml)"
        findings.append(_gen_finding(GENERATED, "generated:openapi:" + g, "OpenAPI client in %s is older than %s" % (g, src_rel),
                                     src_rel, src_m, g, out_m, [cmd],  # type: ignore[arg-type]
                                     notes=["directory matched by convention and by an openapi/swagger marker in its files"]))
    return findings, []


# ---------------------------------------------------------------------------
# GraphQL codegen (codegen.yml / .yaml / .yml only; codegen.ts is not parsed)
# ---------------------------------------------------------------------------
def parse_codegen_yaml(text: str) -> Dict[str, List[str]]:
    """Very small, regex-based reader for the keys whystale needs."""
    res: Dict[str, List[str]] = {"schema": [], "documents": [], "generates": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        m = re.match(r"^(schema|documents|generates)\s*:\s*(.*)$", line)
        i += 1
        if not m:
            continue
        key, rest = m.group(1), m.group(2).strip()
        if rest and not rest.startswith("#"):
            rest = re.split(r"\s+#", rest)[0].strip()
            if key != "generates":
                if rest.startswith("["):
                    res[key].extend(x.strip().strip("'\"") for x in rest.strip("[]").split(",") if x.strip())
                else:
                    res[key].append(rest.strip("'\""))
            continue
        base_indent: Optional[int] = None
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                i += 1
                continue
            indent = len(nxt) - len(nxt.lstrip())
            if indent == 0:
                break
            if key == "generates":
                km = re.match(r"^(\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s:#][^:#]*?))\s*:", nxt)
                if km:
                    if base_indent is None:
                        base_indent = len(km.group(1))
                    if len(km.group(1)) == base_indent:
                        res["generates"].append((km.group(2) or km.group(3) or km.group(4)).strip())
            else:
                im = re.match(r"^\s+-\s*(.+?)\s*(?:#.*)?$", nxt)
                if im:
                    v = im.group(1).strip().strip("'\"")
                    if not v.endswith(":") and ": " not in v:
                        res[key].append(v)
            i += 1
    return res


def check_graphql(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    for rel in project.files:
        base = rel.rsplit("/", 1)[-1]
        if base not in ("codegen.yml", "codegen.yaml"):
            continue
        d = _dir_of(rel)
        txt = read_text(project.abs(rel))
        if not txt:
            continue
        spec = parse_codegen_yaml(txt)
        inputs = [rel]
        patterns = [x for x in spec["schema"] + spec["documents"] if "://" not in x and not x.startswith("!")]
        for p in expand_globs(project.root, [(d + "/" if d else "") + x for x in patterns]):
            if os.path.isfile(project.abs(p)):
                inputs.append(p)
        in_m, in_rel = max((project.mtime(x) or 0.0, x) for x in inputs)
        for g in spec["generates"]:
            out_rel = (d + "/" if d else "") + g
            out_abs = project.abs(out_rel)
            if os.path.isdir(out_abs):
                out_m, _, _ = newest_in_dir(out_abs, cap=2000)
            elif os.path.isfile(out_abs):
                out_m = project.mtime(out_rel)
            else:
                continue
            if out_m is None or in_m <= out_m + cfg.fs_grace_seconds:
                continue
            sc = infer_script(project, d, ["graphql-codegen", "codegen"])
            pm = detect_pm(project, d)
            cmd = ({"npm": "npm run %s", "yarn": "yarn %s", "pnpm": "pnpm run %s", "bun": "bun run %s"}[pm] % sc) if sc else K.pm_exec(pm, "graphql-codegen")
            findings.append(_gen_finding(GENERATED, "generated:graphql:" + out_rel, "GraphQL codegen output %s is older than its inputs" % out_rel,
                                         in_rel, in_m, out_rel, out_m, [_cd(d, cmd)]))
    return findings, []


# ---------------------------------------------------------------------------
# user-defined rules ([[generated]] and [[artifact]] in .whystale.toml)
# ---------------------------------------------------------------------------
def check_rules(project: Project, cfg: Config, now: float) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    for rule in cfg.rules:
        srcs = [s for s in expand_globs(project.root, rule.sources) if os.path.isfile(project.abs(s))]
        outs = expand_globs(project.root, rule.outputs)
        out_files: List[str] = []
        for o in outs:
            a = project.abs(o)
            if os.path.isdir(a):
                for dp, dns, fns in os.walk(a):
                    for fn in fns:
                        out_files.append(project.rel(os.path.join(dp, fn)))
            elif os.path.isfile(a):
                out_files.append(o)
        if not srcs or not out_files:
            continue
        s_m, s_rel = max((project.mtime(s) or 0.0, s) for s in srcs)
        o_m, o_rel = max((project.mtime(o) or 0.0, o) for o in out_files)
        if s_m <= o_m + cfg.fs_grace_seconds:
            continue
        kind = GENERATED if rule.kind == "generated" else ARTIFACT
        fix = [rule.command] if rule.command else ["# no `command` set for this rule in .whystale.toml"]
        findings.append(_gen_finding(kind, "rule:%s:%s" % (rule.kind, rule.name), "%s: outputs are older than sources" % rule.name,
                                     s_rel, s_m, o_rel, o_m, fix, notes=["user-defined rule from .whystale.toml"]))
    return findings, []


def check_generated(project: Project, cfg: Config, now: float) -> Tuple[List[Finding], List[dict]]:
    out_f: List[Finding] = []
    out_i: List[dict] = []
    for fn in (check_prisma, check_protobuf, check_openapi, check_graphql):
        f, i = fn(project, cfg)
        out_f += f
        out_i += i
    f, i = check_rules(project, cfg, now)
    return out_f + f, out_i + i
