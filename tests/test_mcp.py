import asyncio
import json
from pathlib import Path
import sys

import pytest
from mcp import Client, StdioServerParameters

from second_life_mcp.guidance import guidance
from second_life_mcp.server import create_server


@pytest.mark.parametrize("language", ["lsl", "slua"])
def test_guidance_topics_are_language_specific(language):
    result = guidance(language)
    assert result["items"]
    assert all(language in row["languages"] for row in result["items"])
    assert guidance(language, "unknown")["items"] == []


def test_in_memory_schemas_bounds_and_recovery():
    async def run():
        async with Client(create_server(), read_timeout_seconds=10) as client:
            tools = (await client.list_tools()).tools
            assert len(tools) == 10
            assert all(t.annotations.read_only_hint for t in tools)
            invalid = await client.call_tool("lsl_search_reference", {"query": "memory", "limit": -1})
            assert invalid.is_error
            invalid = await client.call_tool("slua_check_code", {"code": "x" * 131073})
            assert invalid.is_error
            good = await client.call_tool("lsl_lookup_symbol", {"name": "llGetTime"})
            assert good.structured_content["found"]
            status = await client.read_resource("slua://status")
            assert json.loads(status.contents[0].text)["language"] == "slua"
    asyncio.run(run())


@pytest.mark.parametrize("module,languages", [
    ("second_life_mcp", ("lsl", "slua")),
    ("lsl_mcp", ("lsl",)),
    ("slua_mcp", ("slua",)),
])
@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_real_stdio_from_unrelated_directory(module, languages, mode, tmp_path):
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", module], cwd=tmp_path)
        async with Client(params, mode=mode, read_timeout_seconds=15) as client:
            tools = (await client.list_tools()).tools
            assert len(tools) == 5 * len(languages)
            assert {t.name.split("_")[0] for t in tools} == set(languages)
            for language in languages:
                result = await client.call_tool(f"{language}_reference_status")
                assert result.structured_content["language"] == language
                result = await client.call_tool(f"{language}_check_code", {"code": ""})
                assert result.structured_content["issues"] == []
    asyncio.run(run())


@pytest.mark.parametrize("command,count", [("second-life-mcp", 10), ("lsl-mcp", 5), ("slua-mcp", 5)])
def test_installed_console_entrypoints(command, count, tmp_path):
    import os
    async def run():
        executable = Path(sys.executable).parent / (command + (".exe" if os.name == "nt" else ""))
        assert executable.is_file()
        async with Client(StdioServerParameters(command=str(executable), cwd=tmp_path), read_timeout_seconds=15) as client:
            assert len((await client.list_tools()).tools) == count
    asyncio.run(run())
