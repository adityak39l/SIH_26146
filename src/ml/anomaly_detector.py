from typing import List, Dict, Any

try:
    from sklearn.ensemble import IsolationForest
    import numpy as np
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

class TransactionAnomalyDetector:
    """
    Unsupervised statistical anomaly isolation for transaction traffic spikes.
    Uses Isolation Forest when scikit-learn is installed, with a statistical fallback.
    """

    def __init__(self):
        if HAS_SKLEARN:
            self.model = IsolationForest(contamination=0.1, random_state=42)
            self.is_fitted = False

    def train_and_score(self, transactions: List[Dict[str, Any]]) -> List[float]:
        if HAS_SKLEARN:
            features = []
            for tx in transactions:
                in_len = len(tx.get("input_addresses", []))
                out_len = len(tx.get("output_addresses", []))
                fee = float(tx.get("fee", 0.0))
                total_out = sum(tx.get("output_amounts", [0.0]))
                fee_ratio = fee / total_out if total_out > 0 else 0
                features.append([in_len, out_len, fee, total_out, fee_ratio])
            
            X = np.array(features)
            if len(X) < 2:
                return [10.0 for _ in transactions]
            self.model.fit(X)
            scores = -self.model.score_samples(X)
            min_s, max_s = scores.min(), scores.max()
            if max_s - min_s == 0:
                return [50.0 for _ in scores]
            return (((scores - min_s) / (max_s - min_s)) * 100).tolist()
        else:
            # Pure Python statistical baseline
            scores = []
            for tx in transactions:
                score = 15.0
                fee = float(tx.get("fee", 0.0))
                total_out = sum(tx.get("output_amounts", [0.0]))
                fee_ratio = fee / total_out if total_out > 0 else 0
                if fee_ratio > 0.0001:
                    score += 25.0
                if len(tx.get("output_addresses", [])) == 2:
                    score += 20.0
                scores.append(score)
            return scores
