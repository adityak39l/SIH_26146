import math

import numpy as np

EULER_GAMMA = 0.5772156649015329


def _average_path_length(n: float) -> float:
    """Average path length of an unsuccessful search in a binary search tree of n points."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1.0) + EULER_GAMMA) - 2.0 * (n - 1.0) / n


class _IsolationTree:
    """One isolation tree stored as flat arrays so that scoring is vectorised."""

    def __init__(self, X: np.ndarray, rng: np.random.Generator, height_limit: int):
        self.feature, self.threshold, self.left, self.right, self.size = [], [], [], [], []
        self._grow(X, rng, 0, height_limit)
        self.feature = np.asarray(self.feature)
        self.threshold = np.asarray(self.threshold)
        self.left = np.asarray(self.left)
        self.right = np.asarray(self.right)
        self.adjust = np.asarray([_average_path_length(s) for s in self.size])

    def _grow(self, X: np.ndarray, rng: np.random.Generator, depth: int, height_limit: int) -> int:
        node = len(self.feature)
        self.feature.append(-1)
        self.threshold.append(0.0)
        self.left.append(-1)
        self.right.append(-1)
        self.size.append(len(X))
        if depth >= height_limit or len(X) <= 1:
            return node
        spread = X.max(axis=0) - X.min(axis=0)
        candidates = np.flatnonzero(spread > 0)
        if len(candidates) == 0:
            return node
        feature = int(rng.choice(candidates))
        threshold = rng.uniform(X[:, feature].min(), X[:, feature].max())
        mask = X[:, feature] < threshold
        self.feature[node] = feature
        self.threshold[node] = threshold
        self.left[node] = self._grow(X[mask], rng, depth + 1, height_limit)
        self.right[node] = self._grow(X[~mask], rng, depth + 1, height_limit)
        return node

    def path_length(self, X: np.ndarray) -> np.ndarray:
        node = np.zeros(len(X), dtype=np.int64)
        depth = np.zeros(len(X))
        active = self.feature[node] >= 0
        while active.any():
            rows = np.flatnonzero(active)
            current = node[rows]
            go_left = X[rows, self.feature[current]] < self.threshold[current]
            node[rows] = np.where(go_left, self.left[current], self.right[current])
            depth[rows] += 1.0
            active = self.feature[node] >= 0
        return depth + self.adjust[node]


class TransactionAnomalyDetector:
    """
    Isolation Forest (Liu, Ting & Zhou, 2008) implemented on NumPy only, so the
    unsupervised stage has no dependency beyond NumPy on an air-gapped host.

    Anomalies are points that random axis-aligned splits isolate quickly. The score is
    2 ** (-E[path length] / c(sample_size)): about 0.5 for ordinary points, towards 1
    for outliers.
    """

    def __init__(self, n_trees: int = 128, sample_size: int = 256, seed: int = 42):
        self.n_trees = n_trees
        self.sample_size = sample_size
        self.seed = seed
        self.trees = []
        self._norm = 1.0

    def fit(self, X: np.ndarray) -> "TransactionAnomalyDetector":
        X = np.asarray(X, dtype=np.float64)
        rng = np.random.default_rng(self.seed)
        sample = min(self.sample_size, len(X))
        height_limit = max(1, math.ceil(math.log2(max(sample, 2))))
        self._norm = _average_path_length(sample) or 1.0
        self.trees = [
            _IsolationTree(X[rng.choice(len(X), size=sample, replace=False)], rng, height_limit)
            for _ in range(self.n_trees)
        ]
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        mean_path = np.mean([tree.path_length(X) for tree in self.trees], axis=0)
        return np.power(2.0, -mean_path / self._norm)

    def train_and_score(self, X: np.ndarray) -> np.ndarray:
        """Fits on the batch under analysis and returns one anomaly score in (0, 1) per row."""
        X = np.asarray(X, dtype=np.float64)
        if len(X) < 8:
            # Too few points to isolate anything meaningfully.
            return np.full(len(X), 0.5)
        return self.fit(X).score(X)
