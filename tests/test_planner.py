"""Pure plan contracts; no application imports or persistent user data."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from src.agent.planner import TaskPlan
from src.agent.tool_executor import execute_plan_step
from src.tools.registry import TOOL_REGISTRY


def step(i, expression, deps=()):
    return {"id": f"s{i}", "order": i, "task_type": "calculation", "tool": "calculator",
            "args": {"expression": expression}, "depends_on": list(deps)}


def plan(*steps):
    return {"action": "execute", "steps": list(steps), "question": ""}


class PlannerTests(unittest.TestCase):
    def test_dependency_result_and_tool_messages(self):
        state = {"plan": plan(step(1, "100+200"), step(2, "$s1.result * 3", ["s1"]))}
        first = execute_plan_step(state)
        state.update(first)
        self.assertEqual(first["execution_records"][0]["result"]["result"], 300)
        state.update(execute_plan_step(state))
        self.assertEqual(state["execution_records"][1]["result"]["result"], 900)
        self.assertEqual(state["execution_records"][1]["args"], {"expression": "(300) * 3"})
        messages = state["execution_messages"]
        self.assertEqual([m.type for m in messages], ["ai", "tool", "ai", "tool"])
        for a, t in zip(messages[::2], messages[1::2]):
            self.assertEqual(a.tool_calls[0]["id"], t.tool_call_id)

    def test_invalid_plans_rejected_before_execution(self):
        valid = plan(step(1, "1+2"), step(2, "$s1.result * 3", ["s1"]))
        mutations = []
        for changes in (
            {"id": "s1"}, {"order": 1}, {"depends_on": ["s2"]},
            {"depends_on": []}, {"args": {"expression": "$s1.content"}},
            {"tool": "file_reader", "args": {"path": "C:/secret.txt"}},
            {"args": {"expression": 123}}, {"args": {"expression": "1", "extra": "bad"}},
            {"args": {"expression": "foo100+200"}},
        ):
            candidate = deepcopy(valid)
            candidate["steps"][1].update(changes)
            mutations.append(candidate)
        mutations += [plan(*(step(i, "1+2") for i in range(1, 10))),
                      {"action": "chat", "steps": [step(1, "1+2")], "question": ""},
                      {"action": "clarify", "steps": [], "question": ""}]
        for candidate in mutations:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                TaskPlan.model_validate(candidate)

    def test_failure_stops_dependents(self):
        state = {"plan": plan(step(1, "1/0"), step(2, "$s1.result*3", ["s1"]))}
        result = execute_plan_step(state)
        self.assertTrue(result["execution_error"])
        self.assertEqual([r["status"] for r in result["execution_records"]], ["failed", "skipped"])
        self.assertEqual(result["execution_messages"][-1].status, "error")
        with patch.object(TOOL_REGISTRY["calculator"], "func", side_effect=RuntimeError("private detail")):
            result = execute_plan_step(state)
            self.assertNotIn("private detail", result["tool_result"])
            self.assertEqual([r["status"] for r in result["execution_records"]], ["failed", "skipped"])
        with patch.object(TOOL_REGISTRY["calculator"], "func", return_value={"success": True, "result": float("nan")}):
            result = execute_plan_step(state)
            self.assertEqual([r["status"] for r in result["execution_records"]], ["failed", "skipped"])

    def test_reference_requires_successful_numeric_result(self):
        original = plan(step(1, "1+2"), step(2, "$s1.result*3", ["s1"]))
        for value in ("300", True, float("inf"), 10**400):
            state = {"plan": original, "plan_index": 1, "execution_records": [
                {"id": "s1", "status": "completed", "result": {"result": value}}]}
            with patch.object(TOOL_REGISTRY["calculator"], "func") as invoke:
                result = execute_plan_step(state)
                invoke.assert_not_called()
                self.assertTrue(result["execution_error"])

    def test_execution_limit_and_parameters(self):
        state = {"plan": plan(step(1, "1+2")), "plan_index": 8}
        self.assertTrue(execute_plan_step(state)["execution_error"])
        state = {"plan": plan({**step(1, "1+2"), "args": {}})}
        self.assertTrue(execute_plan_step(state)["execution_error"])


if __name__ == "__main__":
    unittest.main()
