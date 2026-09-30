"""
Scores a pipeline run against ground truth.

Usage:
    python -m src.pipeline.evaluate
"""
import json
from collections import Counter, defaultdict
from typing import Any, Dict, List

import numpy as np

from config.settings import MEDIUM_RISK_THRESHOLD


def _prf(y: np.ndarray, pred: np.ndarray) -> Dict[str, float]:
    tp = int(np.sum((pred == 1) & (y == 1)))
    fp = int(np.sum((pred == 1) & (y == 0)))
    fn = int(np.sum((pred == 0) & (y == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4)}


def roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    """Probability that a random positive outranks a random negative (ties count half)."""
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    sorted_scores = score[order]
    start = 0
    while start < len(score):
        end = start
        while end + 1 < len(score) and sorted_scores[end + 1] == sorted_scores[start]:
            end += 1
        ranks[order[start:end + 1]] = (start + end) / 2.0 + 1.0
        start = end + 1
    positives, negatives = int(y.sum()), int(len(y) - y.sum())
    if positives == 0 or negatives == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2.0) / (positives * negatives))


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(-score, kind="mergesort")
    hits = y[order]
    if hits.sum() == 0:
        return float("nan")
    precision_at_k = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float(np.sum(precision_at_k * hits) / hits.sum())


def evaluate(prep, scores, cases: List[Dict[str, Any]], truth: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    txs = prep.transactions
    known = [i for i, tx in enumerate(txs) if tx["txid"] in truth]
    y = np.array([truth[txs[i]["txid"]]["label"] for i in known])

    # The rule the first prototype used: one input, two outputs, small/large ratio < 0.2.
    rule = np.array([
        int(len(txs[i]["input_addresses"]) == 1 and len(txs[i]["output_amounts"]) == 2
            and min(txs[i]["output_amounts"]) / max(txs[i]["output_amounts"]) < 0.2)
        for i in known
    ])
    risk, gnn, anomaly = scores.risk[known], scores.gnn_prob[known], scores.anomaly[known]
    # Isolation Forest has no natural cut-off; flag as many as there are true positives.
    k = max(int(y.sum()), 1)
    anomaly_pred = np.zeros(len(known), dtype=int)
    anomaly_pred[np.argsort(-anomaly)[:k]] = 1

    detectors = {
        "rule_baseline": {"label": "Single-transaction peel rule (first prototype)", **_prf(y, rule)},
        "isolation_forest": {"label": "Isolation Forest alone (top-k)", **_prf(y, anomaly_pred),
                             "roc_auc": round(roc_auc(y, anomaly), 4),
                             "average_precision": round(average_precision(y, anomaly), 4)},
        "graphsage": {"label": "GraphSAGE alone (p >= 0.5)", **_prf(y, (gnn >= 0.5).astype(int)),
                      "roc_auc": round(roc_auc(y, gnn), 4),
                      "average_precision": round(average_precision(y, gnn), 4)},
        "fused": {"label": f"Fused risk score (>= {MEDIUM_RISK_THRESHOLD:.0f})",
                  **_prf(y, (risk >= MEDIUM_RISK_THRESHOLD).astype(int)),
                  "roc_auc": round(roc_auc(y, risk), 4),
                  "average_precision": round(average_precision(y, risk), 4)},
    }

    # Recall per laundering typology for the fused score
    by_typology = defaultdict(lambda: [0, 0])
    for pos, i in enumerate(known):
        typology = truth[txs[i]["txid"]]["typology"]
        by_typology[typology][0] += int(risk[pos] >= MEDIUM_RISK_THRESHOLD)
        by_typology[typology][1] += 1
    typologies = [{"typology": t, "flagged": f, "total": n, "rate": round(f / n, 4)}
                  for t, (f, n) in sorted(by_typology.items())]

    # Origin attribution
    buckets = {"below 0.50": [0, 0], "0.50 - 0.75": [0, 0], "0.75 and above": [0, 0]}
    correct = total = 0
    for i in known:
        origin = txs[i].get("_origin")
        if not origin:
            continue
        hit = int(origin["origin_ip"] == truth[txs[i]["txid"]]["origin_ip"])
        confidence = origin["confidence"]
        name = "below 0.50" if confidence < 0.5 else ("0.50 - 0.75" if confidence < 0.75 else "0.75 and above")
        buckets[name][0] += hit
        buckets[name][1] += 1
        correct += hit
        total += 1

    # How much of each simulated operation ends up inside a single case
    case_of = {row["txid"]: case["case_id"] for case in cases for row in case["transactions"]}
    scenarios = defaultdict(list)
    for txid, info in truth.items():
        if info.get("scenario"):
            scenarios[info["scenario"]].append(txid)
    recovered = []
    for name, txids in sorted(scenarios.items()):
        hits = Counter(case_of[t] for t in txids if t in case_of)
        best_case, best = hits.most_common(1)[0] if hits else (None, 0)
        recovered.append({"scenario": name, "transactions": len(txids), "best_case": best_case,
                          "in_best_case": best, "coverage": round(best / len(txids), 4)})

    return {
        "transactions": len(known),
        "positives": int(y.sum()),
        "detectors": detectors,
        "typologies": typologies,
        "origin": {
            "accuracy": round(correct / total, 4) if total else None,
            "correct": correct,
            "total": total,
            "by_confidence": [{"bucket": name, "correct": c, "total": n,
                               "accuracy": round(c / n, 4) if n else None}
                              for name, (c, n) in buckets.items()],
        },
        "scenarios": recovered,
    }


def main() -> None:
    from src.pipeline.engine import analyze

    evaluation = analyze()["evaluation"]
    if not evaluation:
        print("[!] No ground truth available for the default dataset.")
        return
    print(f"Transactions: {evaluation['transactions']}  (laundering-scenario: {evaluation['positives']})\n")
    print(f"{'Detector':48s} {'Prec':>6s} {'Recall':>7s} {'F1':>6s} {'ROC-AUC':>8s} {'AP':>6s}")
    for d in evaluation["detectors"].values():
        auc = f"{d['roc_auc']:.3f}" if "roc_auc" in d else "-"
        ap = f"{d['average_precision']:.3f}" if "average_precision" in d else "-"
        print(f"{d['label']:48s} {d['precision']:6.3f} {d['recall']:7.3f} {d['f1']:6.3f} {auc:>8s} {ap:>6s}")
    print("\nFused-score detection rate by ground-truth typology:")
    for t in evaluation["typologies"]:
        print(f"  {t['typology']:14s} {t['flagged']:4d} / {t['total']:4d}  ({t['rate']:.1%})")
    origin = evaluation["origin"]
    print(f"\nOrigin attribution: {origin['correct']} / {origin['total']} = {origin['accuracy']:.1%}")
    for b in origin["by_confidence"]:
        if b["total"]:
            print(f"  confidence {b['bucket']:15s} {b['correct']:4d} / {b['total']:4d}  ({b['accuracy']:.1%})")
    print("\nScenario recovery (share of each operation inside one case):")
    for s in evaluation["scenarios"]:
        print(f"  {s['scenario']:10s} {s['in_best_case']:3d} / {s['transactions']:3d}  -> {s['best_case']}")
    print()
    print(json.dumps({"fused": evaluation["detectors"]["fused"]}, indent=1))


if __name__ == "__main__":
    main()
