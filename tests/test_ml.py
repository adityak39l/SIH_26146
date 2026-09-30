import unittest

import numpy as np

from src.ml.anomaly_detector import TransactionAnomalyDetector
from src.ml.gnn_classifier import GraphSAGEClassifier
from src.ml.risk_fusion import EVIDENCE, RiskFusionModel


class IsolationForestTests(unittest.TestCase):
    def test_outliers_score_higher_than_the_cluster(self):
        rng = np.random.default_rng(0)
        X = np.vstack([rng.normal(0, 1, size=(300, 4)), [[9, 9, 9, 9], [-9, 9, -9, 9]]])
        scores = TransactionAnomalyDetector().train_and_score(X)
        self.assertTrue(np.all((scores > 0) & (scores < 1)))
        self.assertGreater(scores[-2:].min(), np.percentile(scores[:300], 99))

    def test_tiny_batches_are_not_scored(self):
        self.assertTrue(np.allclose(TransactionAnomalyDetector().train_and_score(np.zeros((3, 4))), 0.5))


class GraphSAGETests(unittest.TestCase):
    def test_backpropagation_matches_numerical_gradient(self):
        rng = np.random.default_rng(1)
        n, d = 12, 5
        X = rng.normal(size=(n, d))
        edges = np.array([(i, j) for i in range(n) for j in range(n) if i < j and rng.random() < 0.25])
        y = (rng.random(n) < 0.4).astype(float)
        weight = np.ones(n)
        model = GraphSAGEClassifier(in_dim=d, hidden=6, seed=3)
        _, grads = model._loss_and_grads(X, edges, y, weight, l2=1e-3)

        eps = 1e-6
        for key, param in model.params.items():
            flat = param.reshape(-1)
            for idx in rng.choice(flat.size, size=min(4, flat.size), replace=False):
                original = flat[idx]
                flat[idx] = original + eps
                up, _ = model._loss_and_grads(X, edges, y, weight, l2=1e-3)
                flat[idx] = original - eps
                down, _ = model._loss_and_grads(X, edges, y, weight, l2=1e-3)
                flat[idx] = original
                self.assertAlmostEqual((up - down) / (2 * eps), grads[key].reshape(-1)[idx], places=5,
                                       msg=f"gradient mismatch in {key}[{idx}]")

    def test_learns_a_label_that_only_neighbours_reveal(self):
        # Every node has the same features; the label is "is funded by a marked node".
        rng = np.random.default_rng(2)
        n = 200
        marked = rng.random(n) < 0.3
        X = np.column_stack([marked.astype(float), rng.normal(size=n)])
        edges = np.array([(i, i + 1) for i in range(n - 1)])
        y = np.zeros(n)
        y[1:] = marked[:-1]
        model = GraphSAGEClassifier(in_dim=2, hidden=8, seed=0)
        history = model.fit(X, edges, y, epochs=200, lr=0.02)
        self.assertLess(history[-1], history[0] * 0.2)
        predicted = model.predict_proba(X, edges) >= 0.5
        self.assertGreater(np.mean(predicted == (y > 0.5)), 0.95)

    def test_state_round_trip(self):
        model = GraphSAGEClassifier(in_dim=3, hidden=4, seed=5)
        X, edges = np.random.default_rng(0).normal(size=(6, 3)), np.array([(0, 1), (1, 2), (3, 4)])
        restored = GraphSAGEClassifier.from_state(model.state())
        self.assertTrue(np.allclose(model.predict_proba(X, edges), restored.predict_proba(X, edges)))


class RiskFusionTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(4)
        self.E = rng.random((400, len(EVIDENCE)))
        self.y = (self.E[:, 0] + 0.5 * self.E[:, 2] + rng.normal(0, 0.1, 400) > 0.9).astype(float)
        self.model = RiskFusionModel().fit(self.E, self.y)

    def test_learns_the_informative_signals(self):
        self.assertGreater(self.model.weights[0], 1.0)
        self.assertGreater(self.model.weights[0], abs(self.model.weights[5]))

    def test_shapley_values_add_up_to_the_score(self):
        shap = self.model.shap_values(self.E)
        self.assertTrue(np.allclose(shap.sum(axis=1) + self.model.base_value, self.model.logit(self.E)))

    def test_average_transaction_has_zero_contributions(self):
        self.assertTrue(np.allclose(self.model.shap_values(self.model.background[None, :]), 0.0))


if __name__ == "__main__":
    unittest.main()
