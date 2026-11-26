import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
import unittest

from src.memory.extractor import extract_memory


class MemoryExtractorTests(unittest.TestCase):
    def test_hobby_updates(self):
        cases = (
            ("我现在不喜欢苹果了，我喜欢香蕉", [("delete", "苹果"), ("save", "香蕉")]),
            ("我不喜欢苹果了，我喜欢香蕉", [("delete", "苹果"), ("save", "香蕉")]),
            ("我喜欢香蕉，我现在不喜欢苹果了", [("save", "香蕉"), ("delete", "苹果")]),
            ("我喜欢篮球、苹果", [("save", "篮球"), ("save", "苹果")]),
            ("我不喜欢苹果了", [("delete", "苹果")]),
            ("我不再喜欢篮球，苹果", [("delete", "篮球"), ("delete", "苹果")]),
            ("我喜欢篮球，苹果", [("save", "篮球"), ("save", "苹果")]),
            ("不喜欢苹果了", [("delete", "苹果")]),
            ("我喜欢苹果，我不喜欢苹果了", [("save", "苹果"), ("delete", "苹果")]),
            ("我不喜欢苹果了，我喜欢苹果", [("delete", "苹果"), ("save", "苹果")]),
            ("我喜欢什么", []),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(extract_memory(message), [
                    {"action": action, "key": "hobby", "value": value}
                    for action, value in expected
                ])

    def test_name_and_job(self):
        self.assertEqual(extract_memory("我改名叫李四"), [
            {"action": "save", "key": "name", "value": "李四"},
        ])
        self.assertEqual(extract_memory("我的工作是软件工程师"), [
            {"action": "save", "key": "job", "value": "软件工程师"},
        ])

    def test_hobby_update_persists_in_isolated_sqlite(self):
        # Configure storage in a fresh process before importing the memory node.
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", dedent("""
                    from types import SimpleNamespace

                    from src.agent.memory_node import memory_extractor_node
                    from src.memory.store import MemoryStore

                    def send(user_id, message):
                        return memory_extractor_node({
                            "user_id": user_id,
                            "messages": [SimpleNamespace(content=message)],
                        })["memory"]

                    updates = (
                        "我现在不喜欢苹果了，我喜欢香蕉",
                        "我不喜欢苹果了，我喜欢香蕉",
                        "我喜欢香蕉，我现在不喜欢苹果了",
                    )
                    send("other", "我喜欢篮球、苹果")
                    for index, update in enumerate(updates):
                        user = f"user-{index}"
                        send(user, "我喜欢篮球、苹果")
                        send(user, update)
                        send(user, "我喜欢香蕉")
                        assert MemoryStore().get(user, "hobby") == "篮球、香蕉"
                        assert send(user, "我喜欢什么") == [
                            {"key": "hobby", "value": "篮球、香蕉"},
                        ]
                    assert MemoryStore().get("other", "hobby") == "篮球、苹果"
                    send("single-delete", "我喜欢篮球、苹果")
                    send("single-delete", "我不喜欢苹果了")
                    assert MemoryStore().get("single-delete", "hobby") == "篮球"
                """)],
                cwd=Path(__file__).resolve().parents[1],
                env={
                    **os.environ,
                    "MY_AGENT_MODE": "demo",
                    "MY_AGENT_DEMO_DATA_DIR": directory,
                    "MY_AGENT_PUBLIC_ORIGIN": "https://demo.test",
                },
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
