"""Data model shared by all checks and renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Levels
STALE = "stale"  # solid evidence: act on it, makes the exit code non-zero
MAYBE = "maybe"  # plausible but heuristic: printed, exit code 0 unless --strict

# Kinds
PROCESS = "process"
DEPS = "deps"
ARTIFACT = "artifact"
GENERATED = "generated"

KIND_LABEL = {
    PROCESS: "process",
    DEPS: "deps",
    ARTIFACT: "build",
    GENERATED: "generated",
}


@dataclass
class Finding:
    kind: str
    level: str
    key: str  # stable identity (used by --watch to diff runs)
    subject: str  # one-line human title
    reason: str  # why it is stale
    evidence: str  # "mtime" | "content" | "process-start"
    fix: List[str] = field(default_factory=list)  # exact commands
    older_than: List[Dict[str, Any]] = field(default_factory=list)  # newer inputs
    notes: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "level": self.level,
            "key": self.key,
            "subject": self.subject,
            "reason": self.reason,
            "evidence": self.evidence,
            "fix": list(self.fix),
            "older_than": list(self.older_than),
            "notes": list(self.notes),
            "details": dict(self.details),
        }


@dataclass
class Report:
    root: str
    findings: List[Finding] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)  # tool-level caveats
    ignored: List[Dict[str, Any]] = field(default_factory=list)  # suppressed, shown with -v
    scanned: Dict[str, Any] = field(default_factory=dict)

    @property
    def stale(self) -> List[Finding]:
        return [f for f in self.findings if f.level == STALE]

    @property
    def maybe(self) -> List[Finding]:
        return [f for f in self.findings if f.level == MAYBE]
