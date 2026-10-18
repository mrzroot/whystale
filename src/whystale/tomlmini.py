"""A tiny TOML reader used only when ``tomllib`` (Python 3.11+) is missing.

It supports the subset needed for ``.whystale.toml`` and for reading
``poetry.lock`` / ``uv.lock`` package tables: ``[table]``, ``[[array]]``,
dotted table names, basic and literal strings, integers, floats, booleans and
(multi-line) arrays and inline tables of those. It is NOT a general TOML parser.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


class TomlError(ValueError):
    pass


def loads(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    cur = root
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[["):
            name = line[2 : line.index("]]")].strip()
            cur = _array_table(root, _split_key(name))
            continue
        if line.startswith("["):
            name = line[1 : line.index("]")].strip()
            cur = _table(root, _split_key(name))
            continue
        if "=" not in line:
            raise TomlError("cannot parse line: %r" % raw)
        key, _, rest = line.partition("=")
        keys = _split_key(key.strip())
        rest = rest.strip()
        # multi-line arrays / strings: keep reading until balanced
        while _unbalanced(rest) and i < len(lines):
            rest += "\n" + _strip_comment(lines[i])
            i += 1
        rest = rest.strip()
        value, end = _parse_value(rest, 0)
        if rest[end:].strip():
            raise TomlError("unexpected text after value: %r" % raw)
        target = cur
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        target[keys[-1]] = value
    return root


def _strip_comment(line: str) -> str:
    out: List[str] = []
    quote = ""
    esc = False
    for ch in line:
        if quote:
            out.append(ch)
            if quote == '"' and ch == "\\" and not esc:
                esc = True
                continue
            if ch == quote and not esc:
                quote = ""
            esc = False
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _unbalanced(s: str) -> bool:
    if s.startswith('"""') or s.startswith("'''"):
        q = s[:3]
        return s.count(q) < 2
    depth = 0
    quote = ""
    esc = False
    for ch in s:
        if quote:
            if quote == '"' and ch == "\\" and not esc:
                esc = True
                continue
            if ch == quote and not esc:
                quote = ""
            esc = False
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth > 0


_KEY_RE = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|\'([^\']*)\'|([A-Za-z0-9_-]+))\s*')


def _split_key(s: str) -> List[str]:
    parts: List[str] = []
    pos = 0
    while True:
        m = _KEY_RE.match(s, pos)
        if not m:
            raise TomlError("bad key: %r" % s)
        parts.append(m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3)))
        pos = m.end()
        if pos >= len(s):
            return parts
        if s[pos] != ".":
            raise TomlError("bad key: %r" % s)
        pos += 1


def _table(root: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    cur = root
    for k in keys:
        nxt = cur.setdefault(k, {})
        if isinstance(nxt, list):
            nxt = nxt[-1]
        cur = nxt
    return cur


def _array_table(root: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    cur = root
    for k in keys[:-1]:
        nxt = cur.setdefault(k, {})
        if isinstance(nxt, list):
            nxt = nxt[-1]
        cur = nxt
    arr = cur.setdefault(keys[-1], [])
    item: Dict[str, Any] = {}
    arr.append(item)
    return item


_ESC = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def _parse_value(s: str, pos: int) -> Tuple[Any, int]:
    while pos < len(s) and s[pos] in " \t\n":
        pos += 1
    if s.startswith('"""', pos):
        end = s.index('"""', pos + 3)
        body = s[pos + 3 : end]
        if body.startswith("\n"):
            body = body[1:]
        return body, end + 3
    if s.startswith("'''", pos):
        end = s.index("'''", pos + 3)
        body = s[pos + 3 : end]
        if body.startswith("\n"):
            body = body[1:]
        return body, end + 3
    ch = s[pos]
    if ch == '"':
        out = []
        pos += 1
        while pos < len(s):
            c = s[pos]
            if c == "\\":
                n = s[pos + 1]
                if n == "u":
                    out.append(chr(int(s[pos + 2 : pos + 6], 16)))
                    pos += 6
                    continue
                if n == "U":
                    out.append(chr(int(s[pos + 2 : pos + 10], 16)))
                    pos += 10
                    continue
                out.append(_ESC.get(n, n))
                pos += 2
                continue
            if c == '"':
                return "".join(out), pos + 1
            out.append(c)
            pos += 1
        raise TomlError("unterminated string")
    if ch == "'":
        end = s.index("'", pos + 1)
        return s[pos + 1 : end], end + 1
    if ch == "[":
        arr: List[Any] = []
        pos += 1
        while True:
            while pos < len(s) and s[pos] in " \t\n,":
                pos += 1
            if pos >= len(s):
                raise TomlError("unterminated array")
            if s[pos] == "]":
                return arr, pos + 1
            v, pos = _parse_value(s, pos)
            arr.append(v)
    if ch == "{":
        tbl: Dict[str, Any] = {}
        pos += 1
        while True:
            while pos < len(s) and s[pos] in " \t\n,":
                pos += 1
            if pos >= len(s):
                raise TomlError("unterminated inline table")
            if s[pos] == "}":
                return tbl, pos + 1
            m = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|\'([^\']*)\'|([A-Za-z0-9_-]+))\s*=').match(s, pos)
            if not m:
                raise TomlError("bad inline table")
            k = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3))
            v, pos = _parse_value(s, m.end())
            tbl[k] = v
    m = re.compile(r"[^\s,\]}]+").match(s, pos)
    if not m:
        raise TomlError("bad value at %r" % s[pos : pos + 20])
    tok = m.group(0)
    end = m.end()
    if tok == "true":
        return True, end
    if tok == "false":
        return False, end
    t = tok.replace("_", "")
    try:
        return int(t), end
    except ValueError:
        pass
    try:
        return float(t), end
    except ValueError:
        # dates etc.: keep the raw token
        return tok, end
