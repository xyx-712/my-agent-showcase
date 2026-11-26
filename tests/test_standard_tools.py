import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from src.tools.registry import TOOL_REGISTRY, get_tools, get_tools_info
from src.agent.tool_executor import tool_executor
from src.agent.tool_router import tool_router
from src.agent.state import AgentState


class StandardToolTests(unittest.TestCase):
    def test_independent_tools(self):
        self.assertEqual({t.name for t in get_tools()}, {"calculator", "file_reader", "time"})
        self.assertTrue(all(isinstance(t, BaseTool) for t in get_tools()))
        self.assertEqual(TOOL_REGISTRY["calculator"].invoke({"expression": "1+4"})["result"], 5)
        self.assertIn("parameters", get_tools_info()["calculator"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"fiction.txt"
            path.write_text("fictional text", encoding="utf-8")
            with patch("src.tools.file_reader.IS_DEMO", False):
                self.assertEqual(TOOL_REGISTRY["file_reader"].invoke({"path": str(path)})["content"], "fictional text")
        self.assertRegex(TOOL_REGISTRY["time"].invoke({}), r"^\d{4}-\d{2}-\d{2} ")

    def test_graph_sequence_and_failures(self):
        graph = StateGraph(AgentState)
        graph.add_node("route", lambda s: {**tool_router(s, None), "tool_calls": tool_router(s, None).get("tool_calls")})
        graph.add_node("tool", tool_executor)
        graph.add_edge(START, "route")
        graph.add_edge("route", "tool")
        graph.add_edge("tool", END)
        result = graph.compile().invoke({"messages": [HumanMessage(content="1+4; 2+6")]})
        self.assertIn("5", result["tool_result"])
        self.assertIn("8", result["tool_result"])
        result = tool_executor({"tool_calls": [{"name":"calculator", "args":{"expression":"3+4"}}, {"name":"time", "args":{}}]})
        self.assertIn("time", result["tool_result"])
        for args in ({}, {"expression": 12}, {"expression": "1+2", "unexpected": True}):
            result = tool_executor({"tool_name": "calculator", "tool_args": args})
            self.assertIn("失败", result["tool_result"])
        result = tool_executor({"tool_name": "unknown", "tool_args": {}})
        self.assertIn("失败", result["tool_result"])
        with patch.object(TOOL_REGISTRY["time"], "func", side_effect=RuntimeError("private details")):
            result = tool_executor({"tool_calls": [{"name":"time", "args":{}}, {"name":"calculator", "args":{"expression":"1+2"}}]})
            self.assertNotIn("private details", result["tool_result"])
            self.assertNotIn("calculator", result["tool_result"])
        self.assertIn("失败", tool_executor({"tool_calls": [{}]*9})["tool_result"])


if __name__ == "__main__":
    unittest.main()
