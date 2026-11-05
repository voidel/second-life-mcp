"""Reviewed language comparisons; never mechanically rewrite source code."""
from importlib.resources import files
import json

from .reference import Catalog


def migration_guidance(language, topic="all", symbol=None):
    if language not in ("lsl", "slua") or not topic.strip() or len(topic) > 64:
        raise ValueError("Invalid language or topic")
    if symbol is not None and (not symbol.strip() or len(symbol) > 128):
        raise ValueError("Invalid symbol")
    target = "slua" if language == "lsl" else "lsl"
    records = json.loads(files("second_life_mcp").joinpath("data/migration.json").read_text("utf-8"))
    catalogs = {name: Catalog(name) for name in ("lsl", "slua")}
    topics = sorted({row["topic"] for row in records})
    selected = []
    for row in records:
        if topic != "all" and row["topic"] != topic:
            continue
        if symbol and symbol not in row[language]:
            continue
        selected.append({**row, "source_symbols": [catalogs[language].lookup(name) for name in row[language]],
                         "target_symbols": [catalogs[target].lookup(name) for name in row[target]]})
    return {"source_language": language, "target_language": target, "topics": topics, "items": selected,
            "note": "Reviewed comparisons only. No source translation or simulator-availability guarantee. Unmapped symbols are not guessed."}
