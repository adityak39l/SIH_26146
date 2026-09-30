import json
import unittest

from config.settings import DEMO_DATA_DIR, MEDIUM_RISK_THRESHOLD, RAW_DATA_DIR
from src.ml.xai_explainer import evidence_hash
from src.pipeline.engine import analyze
from src.pipeline.export import render_dashboard
from src.simulation.generator import TrafficSimulator


class SimulatorTests(unittest.TestCase):
    def test_same_seed_gives_the_same_capture(self):
        a, b = TrafficSimulator(seed=11).generate(), TrafficSimulator(seed=11).generate()
        self.assertEqual(a.transactions, b.transactions)
        self.assertEqual(a.observations, b.observations)

    def test_transactions_balance(self):
        sim = TrafficSimulator(seed=12).generate()
        for tx in sim.transactions:
            spent = sum(tx["output_amounts"]) + tx["fee"]
            self.assertAlmostEqual(sum(tx["input_amounts"]), spent, places=7)
            self.assertGreater(tx["fee"], 0)
            self.assertTrue(all(v > 0 for v in tx["output_amounts"]))


class DemoPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze()

    def test_demo_capture_is_the_default_source(self):
        self.assertTrue(DEMO_DATA_DIR.exists())
        files = {s["file"] for s in self.result["meta"]["sources"]}
        self.assertEqual(files, {"blockchain_transactions.json", "network_observations.csv"})

    def test_beats_the_single_transaction_rule(self):
        detectors = self.result["evaluation"]["detectors"]
        self.assertGreater(detectors["fused"]["f1"], detectors["rule_baseline"]["f1"] + 0.2)
        self.assertGreater(detectors["fused"]["recall"], 0.85)
        self.assertGreater(detectors["fused"]["precision"], 0.7)

    def test_network_layer_adds_to_the_graph_model(self):
        detectors = self.result["evaluation"]["detectors"]
        self.assertGreater(detectors["fused"]["f1"], detectors["graphsage"]["f1"])

    def test_confident_attributions_are_reliable(self):
        buckets = {b["bucket"]: b for b in self.result["evaluation"]["origin"]["by_confidence"]}
        self.assertGreater(buckets["0.75 and above"]["accuracy"], 0.95)
        self.assertLess(buckets["below 0.50"]["accuracy"], 0.5)

    def test_cases_are_ranked_and_explained(self):
        cases = self.result["cases"]
        self.assertGreater(len(cases), 0)
        scores = [c["risk_score"] for c in cases]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for case in cases:
            self.assertGreaterEqual(case["risk_score"], MEDIUM_RISK_THRESHOLD)
            self.assertTrue(case["narrative"])
            self.assertTrue(case["factors"])
            record = {k: v for k, v in case.items() if k != "evidence_hash"}
            self.assertEqual(case["evidence_hash"], evidence_hash(record))
            for a, b, _ in case["edges"]:
                self.assertLess(a, b)  # money only flows forward in time

    def test_replay_stream_adds_up_to_the_summary(self):
        stream, summary = self.result["stream"], self.result["summary"]
        self.assertEqual(len(stream), summary["transactions"])
        self.assertEqual(sum(x["o"] for x in stream), summary["observations"])
        self.assertEqual(sum(x["r"] >= MEDIUM_RISK_THRESHOLD for x in stream), summary["flagged_transactions"])
        self.assertEqual(len({x["c"] for x in stream if x["c"]}), summary["cases"])
        self.assertEqual([x["t"] for x in stream], sorted(x["t"] for x in stream))

    def test_simulator_inputs_reproduce_the_model(self):
        # The console recomputes risk as sigmoid(bias + sum(weight * value)); check that
        # the exported numbers give back the pipeline's own score for a real transaction.
        import math
        card = self.result["model_card"]
        tx = self.result["cases"][0]["transactions"][0]
        logit = card["bias"] + sum(e["weight"] * v for e, v in zip(card["evidence"], tx["evidence"]))
        self.assertAlmostEqual(100 / (1 + math.exp(-logit)), tx["risk_score"], delta=0.5)

    def test_real_data_results_are_well_formed_when_present(self):
        real = self.result["real_data"]
        if real is None:
            self.skipTest("Elliptic results not generated (python -m src.pipeline.elliptic)")
        self.assertEqual(set(real["detectors"]), {"logistic", "mlp", "graphsage", "isolation_forest"})
        for detector in real["detectors"].values():
            self.assertTrue(0.0 <= detector["f1"] <= 1.0)
            self.assertEqual(detector["tp"] + detector["fn"], real["test_illicit"])

    def test_result_is_json_and_renders(self):
        html = render_dashboard(json.loads(json.dumps(self.result)))
        self.assertNotIn("__VIGIL_DATA__", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)


class LegacySampleTests(unittest.TestCase):
    def test_combined_record_format_still_loads(self):
        result = analyze(RAW_DATA_DIR / "sample_transactions.json")
        self.assertEqual(result["summary"]["observations"], 3)
        self.assertEqual(result["summary"]["transactions"], 2)
        self.assertIsNone(result["evaluation"])


class ApiTests(unittest.TestCase):
    def test_endpoints(self):
        from fastapi.testclient import TestClient
        from src.api.main import app

        client = TestClient(app)
        self.assertEqual(client.get("/api/status").status_code, 200)
        self.assertIn("VIGIL-CHAIN Analyst Console", client.get("/").text)
        cases = client.get("/api/cases").json()
        self.assertGreater(cases["total"], 0)
        first = cases["cases"][0]["case_id"]
        self.assertEqual(client.get(f"/api/cases/{first}").json()["case_id"], first)
        self.assertEqual(client.get("/api/cases/CASE-999").status_code, 404)
        self.assertIn("leads", client.get("/api/leads").json())


if __name__ == "__main__":
    unittest.main()
