"""Original concise guidance, kept separate from deterministic code diagnostics."""
from importlib.resources import files
import json


def guidance(language, topic="all"):
    if language not in ("lsl", "slua") or not topic.strip() or len(topic) > 64:
        raise ValueError("Invalid language or topic")
    records = json.loads(files("second_life_mcp").joinpath("data/guidance.json").read_text("utf-8"))
    selected = [r for r in records if language in r["languages"]]
    topics = sorted({r["topic"] for r in selected})
    return {
        "language": language, "topics": topics,
        "items": [r for r in selected if topic == "all" or r["topic"] == topic],
        "note": "Guidance is advisory and manually reviewed; the checker does not prove these properties.",
    }
