import sys
import unittest
from pathlib import Path

from dashboard.topics import TopicStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "main" / "tools"))
from dashboard_topic_rates import TopicRates


class TopicTests(unittest.TestCase):
    def test_only_received_topics_and_actual_arrival_rate(self):
        rates = TopicRates()
        self.assertEqual(rates.snapshot(0), [])
        rates.record("/sensor", 1)
        self.assertEqual(rates.snapshot(1)[0]["hz"], None)
        for stamp in (1.1, 1.2, 1.3):
            rates.record("/sensor", stamp)
        self.assertEqual(rates.snapshot(1.3)[0]["hz"], 10)
        self.assertEqual(rates.snapshot(4.4), [])
        rates.record("/sensor", 10)
        self.assertIsNone(rates.snapshot(10)[0]["hz"])
        rates.remove("/sensor")
        self.assertEqual(rates.snapshot(10), [])

    def test_empty_and_lost_collector_expire_reports(self):
        store = TopicStore()
        self.assertEqual(store.snapshot(100), [])
        store.update({"topics": [{"name": "/sensor", "hz": 10, "age": 1}]}, now=100)
        self.assertEqual(store.snapshot(101), [{"name": "/sensor", "hz": 10, "retained": False}])
        self.assertEqual(store.snapshot(102), [])
        store.update({"topics": []}, now=103)
        self.assertEqual(store.snapshot(103), [])

    def test_invalid_reports_do_not_replace_valid_data(self):
        store = TopicStore()
        store.update({"topics": [{"name": "/sensor", "hz": None, "age": 0}]}, now=10)
        invalid = [None, {}, {"topics": "bad"}, {"topics": [None]}]
        for field, value in (("hz", float("nan")), ("hz", float("inf")), ("hz", -1),
                             ("hz", True), ("age", None), ("age", -1), ("name", "bad"), ("retained", "yes")):
            row = {"name": "/sensor", "hz": 10, "age": 0}
            row[field] = value
            invalid.append({"topics": [row]})
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                store.update(payload, now=10)
        self.assertEqual(store.snapshot(10), [{"name": "/sensor", "hz": None, "retained": False}])

    def test_retained_topics_need_actual_reception_but_survive_silence(self):
        rates = TopicRates()
        rates.set_retained("/tf_static", True)
        self.assertEqual(rates.snapshot(0), [])
        rates.record("/tf_static", 1)
        report = rates.snapshot(100)
        self.assertEqual(report, [{"name": "/tf_static", "hz": None, "age": 99, "retained": True}])
        store = TopicStore()
        store.update({"topics": report}, now=100)
        self.assertEqual(store.snapshot(102), [{"name": "/tf_static", "hz": None, "retained": True}])
        self.assertEqual(store.snapshot(103), [])  # Collector loss still expires the row.
        rates.remove("/tf_static")  # Publisher gone/replaced.
        self.assertEqual(rates.snapshot(104), [])
        rates.record("/tf_static", 105)
        self.assertFalse(rates.snapshot(105)[0]["retained"])


if __name__ == "__main__":
    unittest.main()
