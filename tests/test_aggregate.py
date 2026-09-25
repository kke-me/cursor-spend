import json
import unittest
from pathlib import Path

import refresh

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "payload.json"


class AggregateTest(unittest.TestCase):
    def setUp(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.snap = refresh.aggregate(payload["usage"], payload["plan"], payload["events"])

    def test_headline_is_cursor_meter_not_event_sum(self):
        self.assertEqual(self.snap["spend"]["meterUsd"], 4.4)
        self.assertEqual(self.snap["spend"]["onDemandUsd"], 17.12)
        self.assertEqual(self.snap["pools"]["cursor"]["percentUsed"], 10)
        self.assertEqual(self.snap["pools"]["other"]["percentUsed"], 80)

    def test_drift_when_event_sum_disagrees(self):
        drift = self.snap["drift"]
        self.assertEqual(drift["meterUsd"], 4.4)
        self.assertEqual(drift["eventUsd"], 17.12)
        self.assertAlmostEqual(drift["deltaUsd"], 12.72)

    def test_unknown_kinds_are_kept_out_of_totals(self):
        self.assertEqual(
            self.snap["unknownKinds"],
            [
                {"kind": "(empty)", "count": 1},
                {"kind": "USAGE_EVENT_KIND_ERRORED", "count": 1},
            ],
        )
        models = {m["model"] for m in self.snap["models"]}
        self.assertNotIn("mystery", models)
        self.assertNotIn("old-model", models)

    def test_pool_source_order(self):
        pools = {m["model"]: m["pool"] for m in self.snap["models"]}
        self.assertEqual(pools["composer-1"], "cursor")
        self.assertEqual(pools["default"], "cursor")
        self.assertEqual(pools["grok-new"], "cursor")
        self.assertEqual(pools["kimi"], "other")
        self.assertEqual(pools["claude"], "cursor")
        self.assertEqual(self.snap["prefixFallback"], ["grok-new"])


if __name__ == "__main__":
    unittest.main()
