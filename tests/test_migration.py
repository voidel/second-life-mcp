import asyncio
import json
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters

from second_life_mcp.migration import migration_guidance


def test_reviewed_mappings_only_reference_existing_symbols():
    for language in ("lsl", "slua"):
        report = migration_guidance(language)
        assert len(report["items"]) == 7
        for row in report["items"]:
            assert all(symbol["found"] for symbol in row["source_symbols"] + row["target_symbols"]), row["topic"]


def test_nonmechanical_migration_and_unknown_symbols():
    report = migration_guidance("lsl", symbol="llSetTimerEvent")
    assert [row["topic"] for row in report["items"]] == ["timers"]
    names = {symbol["symbol"]["name"] for symbol in report["items"][0]["target_symbols"]}
    assert "LLTimers:every" in names and "ll.SetTimerEvent" not in names
    assert migration_guidance("lsl", symbol="llUnreviewedMapping")["items"] == []


def test_client_examples_establish_real_mcp_connections(tmp_path):
    root = Path(__file__).resolve().parents[1]
    async def run():
        for file, key in (("claude-code.json", "mcpServers"), ("vscode.json", "servers")):
            config = json.loads((root / "examples/clients" / file).read_text("utf-8"))[key]["second-life"]
            assert config["type"] == "stdio"
            assert config["command"] == "<ABSOLUTE_PYTHON>"
            params = StdioServerParameters(command=sys.executable, args=config["args"], cwd=tmp_path)
            async with Client(params, read_timeout_seconds=15) as client:
                result = await client.call_tool("lsl_migration_guidance", {"symbol": "llSetTimerEvent"})
                assert not result.is_error and result.structured_content["items"][0]["topic"] == "timers"
    asyncio.run(run())
