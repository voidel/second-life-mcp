"""Validated, bundled reference data. No network or generated database required."""
from collections import Counter
from datetime import date
from difflib import get_close_matches
from importlib.resources import files
import json
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["function", "event", "constant"]


class Symbol(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z_0-9]*(?:[.:][A-Za-z_][A-Za-z_0-9]*)*$")
    kind: Kind
    signature: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=1000)
    source_url: str
    reviewed_on: str
    tags: list[str]
    caveats: list[str]
    delay_seconds: float | None = Field(default=None, ge=0)

    @field_validator("source_url")
    @classmethod
    def official_source(cls, value):
        if not (urlparse(value).scheme == "https" and (urlparse(value).netloc in {"wiki.secondlife.com", "create.secondlife.com"} or re.fullmatch(r"https://github\.com/secondlife/sl-vscode-plugin/blob/[0-9a-f]{40}/data/dev/sl-lua-defs\.json", value))):
            raise ValueError("Expected an official Second Life documentation URL")
        return value

    @field_validator("reviewed_on")
    @classmethod
    def review_date(cls, value):
        date.fromisoformat(value)
        return value


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    coverage: Literal["partial"]
    language: Literal["lsl", "slua"]
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
        names = [s.name for s in self.snapshot.symbols]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate symbol names")
        self.symbols = {s.name: s for s in self.snapshot.symbols}

    def status(self):
        return {
            "schema_version": 1,
            "language": self.snapshot.language,
            "runtime_availability": "Check target region support; SLua is evolving." if self.snapshot.language == "slua" else "Classic LSL; verify VM-specific constraints.",
            "coverage": "partial",
            "counts": dict(Counter(s.kind for s in self.symbols.values())),
            "oldest_review": min(s.reviewed_on for s in self.symbols.values()),
            "newest_review": max(s.reviewed_on for s in self.symbols.values()),
            "network_at_runtime": False,
            "note": "Absence from this starter snapshot does not prove a symbol is invalid. Review dates are manual, not live freshness guarantees.",
        }

    def lookup(self, name: str):
        name = name.strip()
        if not name or len(name) > 128:
            raise ValueError("Name must contain 1..128 characters")
        if name in self.symbols:
            return {"found": True, "symbol": self.symbols[name].model_dump(), "coverage": "partial"}
        suggestions = sorted(n for n in self.symbols if n.casefold() == name.casefold())
        suggestions += [n for n in get_close_matches(name, sorted(self.symbols), n=5, cutoff=0.5) if n not in suggestions]
        return {
            "found": False, "query": name, "suggestions": suggestions[:5],
            "coverage": "partial", "note": "No exact match in the bundled snapshot; do not assume nonexistent.",
        }

    def search(self, query: str, kind: Kind | None = None, limit: int = 10, offset: int = 0):
        if not query.strip() or len(query) > 256:
            raise ValueError("Query must contain 1..256 characters")
        if type(limit) is not int or not 1 <= limit <= 25 or type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError("Limit must be 1..25; offset must be 0..10000")
        if kind not in (None, "function", "event", "constant"):
            raise ValueError("Unknown symbol kind")
        terms = re.findall(r"\w+", query.casefold())
        if not terms:
            return {"results": [], "total": 0, "next_offset": None, "coverage": "partial"}
        ranked = []
        for symbol in self.symbols.values():
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
            "coverage": "partial",
        }
