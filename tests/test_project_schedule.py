import unittest
from src.tools.project_schedule import calculate_network, normalized_date, number


class NetworkTests(unittest.TestCase):
    def node(self, name, duration, deps=(), **extra):
        return dict(name=name, remaining=duration, dependencies=list(deps), as_of="2026-04-10", **extra)

    def test_serial_parallel_and_critical_change(self):
        a, b, c = self.node("A", 2), self.node("B", 5, ["A"]), self.node("C", 3, ["A"])
        result = calculate_network([a, b, c])
        self.assertEqual(result["remaining"], 7)
        self.assertEqual(result["critical_path"], ["A", "B"])
        mixed = calculate_network([a, b, c, self.node("D", 1, ["B", "C"])])
        self.assertEqual(mixed["remaining"], 8)
        self.assertEqual(mixed["critical_path"], ["A", "B", "D"])
        c["remaining"] = 9
        self.assertEqual(calculate_network([a, b, c])["critical_path"], ["A", "C"])
        self.assertEqual(calculate_network([self.node("A", 2), self.node("B", 5)])["remaining"], 5)

    def test_invalid(self):
        for nodes in (
            [self.node("A", 1, ["B"]), self.node("B", 1, ["A"])],
            [self.node("A", 1, ["missing"])],
            [self.node("A", 1), self.node("A", 2)],
            [self.node("A", -1)],
            [self.node("A", 1), dict(name="B", remaining=2, as_of="2026-04-11")],
        ):
            with self.assertRaises(ValueError):
                calculate_network(nodes)

    def test_calendar(self):
        result = calculate_network([self.node("A", 3)], {
            "start": "2026-04-10", "weekdays": [0, 1, 2, 3, 4],
            "holidays": ["2026-04-13"], "workdays": ["2026-04-11"],
        })
        self.assertEqual(result["finish_date"], "2026-04-14")
        self.assertEqual(normalized_date("二零二六年四月十日").isoformat(), "2026-04-10")
        self.assertEqual(number("二十三"), 23)
        self.assertEqual(normalized_date("二〇二六年四月十日").isoformat(), "2026-04-10")
        with self.assertRaises(ValueError):
            number("一二")
        for ambiguous in ("一百一", "一千二", "一二十"):
            with self.assertRaises(ValueError):
                number(ambiguous)
        self.assertEqual(number("一百零一"), 101)
        delayed = self.node("A", 3, release=5)
        self.assertEqual(calculate_network([delayed])["remaining"], 8)


if __name__ == "__main__":
    unittest.main()
