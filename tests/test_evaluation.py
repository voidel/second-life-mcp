import asyncio

import pytest

from second_life_mcp.evaluation import check_expectation, evaluate, run_evaluation


@pytest.mark.parametrize("transport", ["in-process", "stdio"])
def test_practical_tasks_over_mcp(transport):
    report = asyncio.run(run_evaluation(transport))
    assert report["total"] >= 18
    assert report["success"], [row for row in report["cases"] if not row["passed"]]


def test_expectations_do_not_coerce_types_or_ignore_missing_fields():
    assert not check_expectation({"found": 1}, {"path": ["found"], "operator": "equals", "value": True})
    assert not check_expectation({}, {"path": ["symbol", "type"], "operator": "equals", "value": "string"})


def test_failed_task_is_reported_without_stopping_later_tasks():
    from types import SimpleNamespace
    class Client:
        async def call_tool(self, name, arguments):
            if name == "broken":
                raise RuntimeError("backend")
            return SimpleNamespace(is_error=False, structured_content={"ok": True})
    cases = [{"id": name, "tool": name, "arguments": {}, "checks": []} for name in ("broken", "working")]
    report = asyncio.run(evaluate(Client(), cases))
    assert not report["success"]
    assert report["passed"] == 1
    assert report["cases"][1]["passed"]
