import math
from bisect import bisect_left, bisect_right
from typing import Any, Dict, List

import numpy as np

from config.settings import ORIGIN_BURST_WINDOW_S

# Evidence signals fused into the final risk score: (key, plain-language label).
EVIDENCE = [
    ("gnn_prob", "Graph neural network: laundering-topology probability"),
    ("anomaly", "Isolation Forest: statistical outlier score"),
    ("origin_tor", "First-seen origin is a Tor exit relay"),
    ("origin_vpn", "First-seen origin is a commercial VPN range"),
    ("origin_hosting", "First-seen origin is a datacentre / hosting range"),
    ("origin_exchange", "First-seen origin is known exchange infrastructure"),
    ("peel_chain", "Member of a multi-hop peeling chain"),
    ("coinjoin", "Equal-output mixing (CoinJoin) structure"),
    ("velocity", "Funds re-spent within minutes"),
    ("origin_burst", "Burst of transactions from the same origin IP"),
]
EVIDENCE_KEYS = [key for key, _ in EVIDENCE]
EVIDENCE_LABELS = dict(EVIDENCE)
# Yes/no signals still contribute when they are absent (relative to average traffic),
# and have to be worded that way or the explanation reads as its opposite.
ABSENT_LABELS = {
    "origin_tor": "Origin is not a Tor exit relay",
    "origin_vpn": "Origin is not a commercial VPN range",
    "origin_hosting": "Origin is not a datacentre / hosting range",
    "origin_exchange": "Origin is not known exchange infrastructure",
    "peel_chain": "Not part of a multi-hop peeling chain",
    "coinjoin": "No equal-output mixing structure",
}


def build_evidence(transactions: List[Dict[str, Any]], gnn_prob: np.ndarray, anomaly: np.ndarray,
                   since: List[float], until: List[float]) -> np.ndarray:
    """
    Evidence matrix [n_tx, len(EVIDENCE)], every column scaled to roughly [0, 1].
    `transactions` must carry `_ts`, `_origin_ip`, `_origin_category`, `_peel_hops`
    and `_coinjoin`. `_origin_category` is "unresolved" when the attribution is too weak
    to be used as evidence, so none of the origin_* signals fire for it.
    """
    by_origin: Dict[str, List[float]] = {}
    for tx in transactions:
        if tx.get("_origin_ip"):
            by_origin.setdefault(tx["_origin_ip"], []).append(tx["_ts"])

    rows = []
    for idx, tx in enumerate(transactions):
        category = tx.get("_origin_category", "unknown")
        # Transactions are time-sorted, so each per-origin list is sorted too.
        times = by_origin.get(tx.get("_origin_ip"), [])
        neighbours = (bisect_right(times, tx["_ts"] + ORIGIN_BURST_WINDOW_S)
                      - bisect_left(times, tx["_ts"] - ORIGIN_BURST_WINDOW_S) - 1)
        rows.append([
            float(gnn_prob[idx]),
            float(anomaly[idx]),
            1.0 if category == "tor_exit" else 0.0,
            1.0 if category == "vpn" else 0.0,
            1.0 if category == "hosting" else 0.0,
            1.0 if category == "exchange" else 0.0,
            min(1.0, math.log2(1 + tx.get("_peel_hops", 0)) / 4.0),
            float(tx.get("_coinjoin", 0.0)),
            math.exp(-min(since[idx], until[idx]) / 300.0),
            min(1.0, math.log2(1 + max(neighbours, 0)) / 4.0),
        ])
    return np.asarray(rows, dtype=np.float64).reshape(len(transactions), len(EVIDENCE))


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, balanced: bool = True,
                 iterations: int = 50) -> tuple:
    """
    L2-penalised logistic regression by Newton's method (IRLS). Returns (weights, bias).
    `balanced` re-weights the classes equally, which suits detection; leave it off when
    the output must be a calibrated probability.
    """
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n, d = X.shape
    if balanced:
        positives = max(y.sum(), 1.0)
        negatives = max(n - y.sum(), 1.0)
        sample_weight = np.where(y > 0.5, n / (2.0 * positives), n / (2.0 * negatives))
    else:
        sample_weight = np.ones(n)

    A = np.hstack([X, np.ones((n, 1))])
    penalty = np.eye(d + 1) * l2
    penalty[d, d] = 0.0  # the bias is not regularised
    theta = np.zeros(d + 1)
    for _ in range(iterations):
        prob = 1.0 / (1.0 + np.exp(-np.clip(A @ theta, -60.0, 60.0)))
        gradient = A.T @ (sample_weight * (prob - y)) + penalty @ theta
        curvature = sample_weight * prob * (1.0 - prob)
        hessian = (A * curvature[:, None]).T @ A + penalty + np.eye(d + 1) * 1e-9
        step = np.linalg.solve(hessian, gradient)
        theta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return theta[:d], float(theta[d])


class RiskFusionModel:
    """
    L2-regularised logistic regression over the evidence signals.

    It is deliberately linear: for a linear model the Shapley value of each signal has
    the exact closed form  phi_i = w_i * (x_i - E[x_i])  in log-odds, so every risk score
    decomposes into per-signal contributions that sum to the score with no sampling and
    no approximation. That is what makes a lead auditable line by line.
    """

    def __init__(self, n_features: int = len(EVIDENCE)):
        self.weights = np.zeros(n_features)
        self.bias = 0.0
        self.background = np.zeros(n_features)  # E[x] over the training traffic

    def fit(self, E: np.ndarray, y: np.ndarray, l2: float = 1.0) -> "RiskFusionModel":
        E = np.asarray(E, dtype=np.float64)
        self.weights, self.bias = fit_logistic(E, y, l2=l2, balanced=True)
        self.background = E.mean(axis=0)
        return self

    def logit(self, E: np.ndarray) -> np.ndarray:
        return np.asarray(E, dtype=np.float64) @ self.weights + self.bias

    def predict_proba(self, E: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(self.logit(E), -60.0, 60.0)))

    @property
    def base_value(self) -> float:
        """Log-odds of the average training transaction: the SHAP expected value."""
        return float(self.background @ self.weights + self.bias)

    def shap_values(self, E: np.ndarray) -> np.ndarray:
        """Exact Shapley values in log-odds; each row sums to logit(x) - base_value."""
        return (np.asarray(E, dtype=np.float64) - self.background) * self.weights

    def state(self) -> Dict[str, np.ndarray]:
        return {
            "fusion_weights": self.weights,
            "fusion_bias": np.array([self.bias]),
            "fusion_background": self.background,
        }

    @classmethod
    def from_state(cls, state) -> "RiskFusionModel":
        model = cls(n_features=len(state["fusion_weights"]))
        model.weights = np.asarray(state["fusion_weights"])
        model.bias = float(np.asarray(state["fusion_bias"])[0])
        model.background = np.asarray(state["fusion_background"])
        return model
