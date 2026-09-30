from typing import Dict, List, Tuple

import numpy as np


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


def _mean_aggregate(H: np.ndarray, src: np.ndarray, dst: np.ndarray, inv_deg: np.ndarray) -> np.ndarray:
    """Row i receives the mean of H[src] over all edges (src -> i)."""
    out = np.zeros_like(H)
    np.add.at(out, dst, H[src])
    return out * inv_deg[:, None]


def _mean_aggregate_backward(dM: np.ndarray, src: np.ndarray, dst: np.ndarray, inv_deg: np.ndarray) -> np.ndarray:
    dH = np.zeros_like(dM)
    np.add.at(dH, src, (dM * inv_deg[:, None])[dst])
    return dH


class GraphSAGEClassifier:
    """
    Two-layer GraphSAGE node classifier (Hamilton, Ying & Leskovec, 2017) with mean
    aggregation, written on NumPy with hand-derived backpropagation.

    Each layer combines a transaction's own representation with the mean of the
    transactions that fund it and, separately, the mean of those that spend it:

        h' = ReLU(h W_self + mean(h_funding) W_in + mean(h_spending) W_out + b)

    Keeping the two directions apart lets the model tell "spends change from a peel"
    from "is spent by a peel", which an undirected aggregator cannot. The model is
    inductive: it is trained on one set of graphs and applied to unseen captures.
    """

    def __init__(self, in_dim: int, hidden: int = 24, seed: int = 0, clip: float = None):
        rng = np.random.default_rng(seed)
        self.in_dim = in_dim
        self.hidden = hidden
        # Standardised features are clipped to +-clip when set. Real ledger features have
        # extreme tails, and a network that leans on them does not carry over to later data.
        self.clip = clip

        def glorot(rows: int, cols: int) -> np.ndarray:
            limit = np.sqrt(6.0 / (rows + cols))
            return rng.uniform(-limit, limit, size=(rows, cols))

        self.params: Dict[str, np.ndarray] = {
            "W1_self": glorot(in_dim, hidden), "W1_in": glorot(in_dim, hidden),
            "W1_out": glorot(in_dim, hidden), "b1": np.zeros(hidden),
            "W2_self": glorot(hidden, hidden), "W2_in": glorot(hidden, hidden),
            "W2_out": glorot(hidden, hidden), "b2": np.zeros(hidden),
            "w_out": glorot(hidden, 1)[:, 0], "b_out": np.zeros(1),
        }
        self.mean = np.zeros(in_dim)
        self.std = np.ones(in_dim)

    @staticmethod
    def _edges(edges: np.ndarray, n: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
        src, dst = edges[:, 0], edges[:, 1]
        inv_in = 1.0 / np.maximum(np.bincount(dst, minlength=n), 1)
        inv_out = 1.0 / np.maximum(np.bincount(src, minlength=n), 1)
        return src, dst, inv_in, inv_out

    def _forward(self, X: np.ndarray, edges: np.ndarray) -> Tuple[np.ndarray, dict]:
        p = self.params
        src, dst, inv_in, inv_out = self._edges(edges, len(X))
        cache = {"src": src, "dst": dst, "inv_in": inv_in, "inv_out": inv_out, "H0": X}

        H = X
        for layer in ("1", "2"):
            M_in = _mean_aggregate(H, src, dst, inv_in)     # from funding transactions
            M_out = _mean_aggregate(H, dst, src, inv_out)   # from spending transactions
            Z = H @ p[f"W{layer}_self"] + M_in @ p[f"W{layer}_in"] + M_out @ p[f"W{layer}_out"] + p[f"b{layer}"]
            cache[f"M_in{layer}"], cache[f"M_out{layer}"], cache[f"Z{layer}"] = M_in, M_out, Z
            H = np.maximum(Z, 0.0)
            cache[f"H{layer}"] = H
        logits = H @ p["w_out"] + p["b_out"][0]
        return logits, cache

    def _loss_and_grads(self, X: np.ndarray, edges: np.ndarray, y: np.ndarray,
                        sample_weight: np.ndarray, l2: float) -> Tuple[float, Dict[str, np.ndarray]]:
        p = self.params
        logits, c = self._forward(X, edges)
        prob = _sigmoid(logits)
        eps = 1e-12
        total = sample_weight.sum()
        loss = -np.sum(sample_weight * (y * np.log(prob + eps) + (1 - y) * np.log(1 - prob + eps))) / total
        loss += 0.5 * l2 * sum(np.sum(v * v) for k, v in p.items() if k.startswith("W") or k == "w_out")

        grads: Dict[str, np.ndarray] = {}
        d_logits = sample_weight * (prob - y) / total
        grads["w_out"] = c["H2"].T @ d_logits + l2 * p["w_out"]
        grads["b_out"] = np.array([d_logits.sum()])
        dH = np.outer(d_logits, p["w_out"])

        for layer, below in (("2", "H1"), ("1", "H0")):
            dZ = dH * (c[f"Z{layer}"] > 0)
            grads[f"W{layer}_self"] = c[below].T @ dZ + l2 * p[f"W{layer}_self"]
            grads[f"W{layer}_in"] = c[f"M_in{layer}"].T @ dZ + l2 * p[f"W{layer}_in"]
            grads[f"W{layer}_out"] = c[f"M_out{layer}"].T @ dZ + l2 * p[f"W{layer}_out"]
            grads[f"b{layer}"] = dZ.sum(axis=0)
            if layer == "1":
                break  # the gradient with respect to the input features is not needed
            dH = (dZ @ p[f"W{layer}_self"].T
                  + _mean_aggregate_backward(dZ @ p[f"W{layer}_in"].T, c["src"], c["dst"], c["inv_in"])
                  + _mean_aggregate_backward(dZ @ p[f"W{layer}_out"].T, c["dst"], c["src"], c["inv_out"]))
        return float(loss), grads

    def fit(self, X: np.ndarray, edges: np.ndarray, y: np.ndarray, epochs: int = 300,
            lr: float = 0.01, l2: float = 1e-4, verbose: bool = False,
            mask: np.ndarray = None, callback=None) -> List[float]:
        """
        Full-batch Adam on class-balanced binary cross-entropy. Returns the loss history.

        `mask` selects the nodes whose labels are used; the others still pass messages,
        which is how partly labelled graphs are trained. `callback(step)` is called after
        every update, e.g. to track validation performance.
        """
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        mask = np.ones(len(y), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
        self.mean = X.mean(axis=0)
        self.std = X.std(axis=0)
        self.std[self.std < 1e-9] = 1.0
        Xn = self._normalise(X)

        labelled = float(mask.sum())
        positives = max(y[mask].sum(), 1.0)
        negatives = max(labelled - y[mask].sum(), 1.0)
        sample_weight = np.where(y > 0.5, labelled / (2.0 * positives), labelled / (2.0 * negatives)) * mask

        m = {k: np.zeros_like(v) for k, v in self.params.items()}
        v = {k: np.zeros_like(val) for k, val in self.params.items()}
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        history = []
        for step in range(1, epochs + 1):
            loss, grads = self._loss_and_grads(Xn, edges, y, sample_weight, l2)
            history.append(loss)
            for key in self.params:
                m[key] = beta1 * m[key] + (1 - beta1) * grads[key]
                v[key] = beta2 * v[key] + (1 - beta2) * grads[key] ** 2
                m_hat = m[key] / (1 - beta1 ** step)
                v_hat = v[key] / (1 - beta2 ** step)
                self.params[key] = self.params[key] - lr * m_hat / (np.sqrt(v_hat) + eps)
            if verbose and (step == 1 or step % 50 == 0):
                print(f"    epoch {step:4d}  loss {loss:.4f}")
            if callback:
                callback(step)
        return history

    def _normalise(self, X: np.ndarray) -> np.ndarray:
        Xn = (np.asarray(X, dtype=np.float64) - self.mean) / self.std
        return np.clip(Xn, -self.clip, self.clip) if self.clip else Xn

    def predict_proba(self, X: np.ndarray, edges: np.ndarray) -> np.ndarray:
        if len(X) == 0:
            return np.zeros(0)
        logits, _ = self._forward(self._normalise(X), edges)
        return _sigmoid(logits)

    def occlusion(self, X: np.ndarray, edges: np.ndarray) -> np.ndarray:
        """
        Occlusion sensitivity, [n, in_dim]: the drop in each node's log-odds when one
        input feature is replaced by its training mean for the node and its neighbours.
        Positive means the feature pushed that node towards "laundering". This is a
        perturbation estimate that says what the GNN reacted to; it is not an exact
        Shapley value, because GNN features interact through the layers.
        """
        Xn = self._normalise(X)
        if len(Xn) == 0:
            return np.zeros((0, self.in_dim))
        base, _ = self._forward(Xn, edges)
        drops = np.zeros_like(Xn)
        for j in range(self.in_dim):
            occluded = Xn.copy()
            occluded[:, j] = 0.0
            drops[:, j] = base - self._forward(occluded, edges)[0]
        return drops

    def state(self) -> Dict[str, np.ndarray]:
        state = {f"gnn_{k}": v for k, v in self.params.items()}
        state["gnn_mean"], state["gnn_std"] = self.mean, self.std
        return state

    @classmethod
    def from_state(cls, state) -> "GraphSAGEClassifier":
        model = cls(in_dim=state["gnn_W1_self"].shape[0], hidden=state["gnn_W1_self"].shape[1])
        model.params = {k: np.asarray(state[f"gnn_{k}"]) for k in model.params}
        model.mean, model.std = np.asarray(state["gnn_mean"]), np.asarray(state["gnn_std"])
        return model
