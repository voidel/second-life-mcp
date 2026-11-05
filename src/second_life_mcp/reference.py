"""Validated, bundled reference data. No network or generated database required."""
from collections import Counter
from datetime import date
from difflib import get_close_matches
from importlib.resources import files
import json
import re
from typing import Literal, Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["function", "event", "constant", "type"]


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=4096)
    description: str = Field(default="", max_length=16384)
    optional: bool = False
    variadic: bool = False


class Symbol(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z_0-9]*(?:[.:][A-Za-z_][A-Za-z_0-9]*)*$")
    kind: Kind
    signature: str = Field(min_length=1, max_length=8192)
    summary: str = Field(min_length=1, max_length=16384)
    source_url: str
    reviewed_on: str | None = None
    imported_on: str | None = None
    source_revision: str | None = None
    source_sha256: str | None = None
    parameters: list[Parameter] = Field(default_factory=list)
    return_type: str | None = None
    value: str | None = None
    type: str | None = None
    type_parameters: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    overloads: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str]
    caveats: list[str]
    delay_seconds: float | None = Field(default=None, ge=0)

    @field_validator("source_url")
    @classmethod
    def official_source(cls, value):
        if not (urlparse(value).scheme == "https" and (urlparse(value).netloc in {"wiki.secondlife.com", "create.secondlife.com"} or re.fullmatch(r"https://github\.com/secondlife/(?:sl-vscode-plugin/blob/[0-9a-f]{40}/data/dev/sl-lua-defs\.json|lsl-definitions/blob/[0-9a-f]{40}/(?:generated/[A-Za-z_.]+|[A-Za-z_.]+))", value))):
            raise ValueError("Expected an official Second Life documentation URL")
        return value

    @field_validator("reviewed_on", "imported_on")
    @classmethod
    def review_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1, 2]
    coverage: Literal["partial", "official_snapshot"]
    language: Literal["lsl", "slua"]
    inventory_counts: dict[str, int] = Field(default_factory=dict)
    sources: list[dict[str, str]] = Field(default_factory=list)
    symbols: list[Symbol] = Field(min_length=1, max_length=10000)


class Catalog:
    def __init__(self, language="lsl", document=None):
        if language not in ("lsl", "slua"):
            raise ValueError("Unknown language")
        if document is None:
            document = json.loads(files("second_life_mcp").joinpath(f"data/{language}.json").read_text("utf-8"))
        self.snapshot = Snapshot.model_validate(document)
        if self.snapshot.language != language:
            raise ValueError("Snapshot language does not match requested catalog")
        names = [(s.kind, s.name) for s in self.snapshot.symbols]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate symbol names")
        self.records = self.snapshot.symbols
        priority = {"type": 0, "event": 1, "constant": 2, "function": 3}
        self.symbols = {s.name: s for s in sorted(self.records, key=lambda s: priority[s.kind])}

    def status(self):
        return {
            "schema_version": self.snapshot.schema_version,
            "language": self.snapshot.language,
            "runtime_availability": "Check target region support; SLua is evolving." if self.snapshot.language == "slua" else "Classic LSL; verify VM-specific constraints.",
            "coverage": self.snapshot.coverage,
            "counts": dict(Counter(s.kind for s in self.records)),
            "oldest_review": min((s.reviewed_on for s in self.records if s.reviewed_on), default=None),
            "newest_review": max((s.reviewed_on for s in self.records if s.reviewed_on), default=None),
            "inventory_counts": self.snapshot.inventory_counts,
            "sources": self.snapshot.sources,
            "network_at_runtime": False,
            "note": "Coverage is scoped to the pinned official public inventory plus supplemental methods. Imports are not manual reviews or simulator availability guarantees.",
        }

    def lookup(self, name: str):
        name = name.strip()
        if not name or len(name) > 128:
            raise ValueError("Name must contain 1..128 characters")
        if name in self.symbols:
            return {"found": True, "symbol": self.symbols[name].model_dump(),
                    "alternatives": [s.model_dump() for s in self.records if s.name == name and s is not self.symbols[name]],
                    "coverage": self.snapshot.coverage}
        suggestions = sorted(n for n in self.symbols if n.casefold() == name.casefold())
        suggestions += [n for n in get_close_matches(name, sorted(self.symbols), n=5, cutoff=0.5) if n not in suggestions]
        return {
            "found": False, "query": name, "suggestions": suggestions[:5],
            "coverage": self.snapshot.coverage, "note": "No exact match in the bundled snapshot; do not assume nonexistent.",
        }

    def search(self, query: str, kind: Kind | None = None, limit: int = 10, offset: int = 0):
        if not query.strip() or len(query) > 256:
            raise ValueError("Query must contain 1..256 characters")
        if type(limit) is not int or not 1 <= limit <= 25 or type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError("Limit must be 1..25; offset must be 0..10000")
        if kind not in (None, "function", "event", "constant", "type"):
            raise ValueError("Unknown symbol kind")
        terms = re.findall(r"\w+", query.casefold())
        if not terms:
            return {"results": [], "total": 0, "next_offset": None, "coverage": self.snapshot.coverage}
        ranked = []
        for symbol in self.records:
            if kind and symbol.kind != kind:
                continue
            name = symbol.name.casefold()
            text = " ".join([name, symbol.summary, *symbol.tags]).casefold()
            if all(term in text for term in terms):
                rank = (0 if query.casefold() == name else 1 if name.startswith(query.casefold()) else 2, name)
                ranked.append((rank, symbol))
        ranked.sort(key=lambda row: row[0])
        page = ranked[offset:offset + limit]
        return {
            "results": [s.model_dump() for _, s in page], "total": len(ranked),
            "next_offset": offset + limit if offset + limit < len(ranked) else None,
            "coverage": self.snapshot.coverage,
        }
