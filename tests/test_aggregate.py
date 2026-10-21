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

    def test_missing_individual_meter_is_not_zero(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        del payload["usage"]["spendLimitUsage"]["individualUsed"]
        snap = refresh.aggregate(payload["usage"], payload["plan"], payload["events"])
        self.assertIsNone(snap["spend"]["meterUsd"])
        self.assertIsNone(snap["drift"])
        self.assertEqual(snap["spend"]["onDemandUsd"], 17.12)

    def test_string_pooled_limit(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["usage"]["spendLimitUsage"]["pooledLimit"] = "144500"
        snap = refresh.aggregate(payload["usage"], payload["plan"], payload["events"])
        self.assertEqual(snap["team"]["limitUsd"], 1445.0)

    def test_included_limit_falls_back_to_plan_usage(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        del payload["plan"]["planInfo"]["includedAmountCents"]
        payload["usage"]["planUsage"]["limit"] = 2000
        snap = refresh.aggregate(payload["usage"], payload["plan"], payload["events"])
        self.assertEqual(snap["plan"]["includedApiUsd"], 20.0)

    def test_unbilled_kinds_are_dropped(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["events"].extend(
            [
                {
                    "timestamp": "1700000008000",
                    "kind": "USAGE_EVENT_KIND_ERRORED_NOT_CHARGED",
                    "model": "dropped-err",
                    "chargedCents": 500,
                },
                {
                    "timestamp": "1700000009000",
                    "kind": "USAGE_EVENT_KIND_ABORTED_NOT_CHARGED",
                    "model": "dropped-abort",
                    "chargedCents": 500,
                },
            ]
        )
        snap = refresh.aggregate(payload["usage"], payload["plan"], payload["events"])
        self.assertEqual(snap["unknownKinds"], self.snap["unknownKinds"])
        models = {m["model"] for m in snap["models"]}
        self.assertNotIn("dropped-err", models)
        self.assertNotIn("dropped-abort", models)
        self.assertEqual(snap["spend"]["onDemandUsd"], 17.12)

    def test_display_names_follow_first_party_slug(self):
        bucket = {"grok-4.7-high", "composer-1"}
        self.assertEqual(
            refresh.classify_pool("grok-4.7-high (Auto Balanced)", {}, bucket),
            ("cursor", "bucket"),
        )
        self.assertEqual(
            refresh.classify_pool("Grok 4.6 (Auto Balanced)", {}, bucket),
            ("cursor", "prefix"),
        )
        self.assertEqual(
            refresh.classify_pool("Claude Opus 5.5 (Auto Balanced)", {}, bucket),
            ("other", "other"),
        )
        self.assertEqual(
            refresh.classify_pool("GPT-5.6 Sol (Auto Balanced)", {}, bucket),
            ("other", "other"),
        )


if __name__ == "__main__":
    unittest.main()
