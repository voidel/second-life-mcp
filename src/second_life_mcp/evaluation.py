"""Deterministic MCP task evaluation; measures tool contracts, not generated code."""
import argparse
import asyncio
from importlib.resources import files
import json
from pathlib import Path
import sys
import tempfile
import time

from mcp import Client, StdioServerParameters

from .server import create_server
from .update import atomic_write


def check_expectation(document, check):
    value = document
    try:
        for part in check["path"]:
            value = value[part]
        if check["operator"] == "equals":
            return value == check["value"] and type(value) is type(check["value"])
        if check["operator"] == "contains":
            return check["value"] in value
        raise ValueError("Unknown evaluation operator")
    except (KeyError, IndexError, TypeError):
        return False


async def evaluate(client, scenarios):
    cases = []
    for case in scenarios:
        start = time.perf_counter()
        try:
            result = await client.call_tool(case["tool"], case["arguments"])
            passed = not result.is_error and result.structured_content is not None
            failures = []
            if passed:
                failures = [check["path"] for check in case["checks"] if not check_expectation(result.structured_content, check)]
                passed = not failures
            cases.append({"id": case["id"], "tool": case["tool"], "passed": passed,
                          "failed_paths": failures, "tool_error": bool(result.is_error),
                          "duration_ms": round((time.perf_counter() - start) * 1000, 2)})
        except Exception as error:
            cases.append({"id": case["id"], "tool": case["tool"], "passed": False,
                          "error_type": type(error).__name__})
    return {"passed": sum(row["passed"] for row in cases), "total": len(cases),
            "success": all(row["passed"] for row in cases), "cases": cases,
            "scope": "Deterministic tool behavior over MCP; not an LLM benchmark, compilation or in-world validation."}


async def run_evaluation(transport="stdio"):
    scenarios = json.loads(files("second_life_mcp").joinpath("data/scenarios.json").read_text("utf-8"))
    if transport == "in-process":
        async with Client(create_server(), read_timeout_seconds=15) as client:
            return await evaluate(client, scenarios)
    with tempfile.TemporaryDirectory(prefix="second-life-evaluation-") as directory:
        params = StdioServerParameters(command=sys.executable, args=["-m", "second_life_mcp"], cwd=directory)
        async with Client(params, read_timeout_seconds=15) as client:
            return await evaluate(client, scenarios)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "in-process"], default="stdio")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_evaluation(args.transport))
    payload = (json.dumps(report, indent=2) + "\n").encode()
    if args.output:
        atomic_write(args.output, payload)
    print(f'{report["passed"]}/{report["total"]} MCP task scenarios passed ({args.transport}).')
    if not report["success"]:
        print(json.dumps([row for row in report["cases"] if not row["passed"]], indent=2))
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
