"""
Evaluates the blockchain-layer models on the Elliptic dataset: about 200,000 real
Bitcoin transactions, of which about 46,000 carry an illicit / licit label
(Weber et al., "Anti-Money Laundering in Bitcoin", KDD 2019 workshop).

Elliptic has no network-layer data (no IP addresses), so this measures the GNN and the
anomaly detector only. Origin attribution and risk fusion cannot be tested on it.

Protocol, as in the paper: time steps 1-34 for training, 35-49 for testing. The time
steps are disconnected graphs, so the test graphs are never seen during training.

Laundering patterns drift over time, so a validation window right next to the training
data is far too optimistic. Labels from steps 1-25 are used for fitting and steps 30-34
for choosing the epoch and the decision threshold, with steps 26-29 left as a gap that
mimics the distance to the test period. Standardised features are clipped to +-3: the
raw features reach hundreds of standard deviations, and clipping was chosen on that
validation window, not on the test set.

The dataset is not redistributed here. It is downloaded on first use (about 150 MB):
    python -m src.pipeline.elliptic
Needs pandas for the CSV files.
"""
import argparse
import json
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from config.settings import DATA_DIR, ELLIPTIC_RESULTS, EVAL_DIR
from src.ml.anomaly_detector import TransactionAnomalyDetector
from src.ml.gnn_classifier import GraphSAGEClassifier
from src.ml.risk_fusion import fit_logistic
from src.pipeline.evaluate import average_precision, roc_auc

ELLIPTIC_DIR = DATA_DIR / "external" / "elliptic"
RESULTS_FILE = ELLIPTIC_RESULTS
SOURCE_URL = "https://data.pyg.org/datasets/elliptic"
FILES = ("elliptic_txs_classes.csv", "elliptic_txs_edgelist.csv", "elliptic_txs_features.csv")
TRAIN_END, FIT_END, VALIDATION_START, TEST_START = 34, 25, 30, 35
CLIP = 3.0
REFERENCE = ("Weber et al. (2019) report an illicit-class F1 of about 0.63 for a GCN and about 0.79 "
             "for a random forest on this split")


def load():
    """Returns features [n, 165], time step [n], label [n] (1 illicit, 0 licit, -1 unknown), edges [e, 2]."""
    cache = ELLIPTIC_DIR / "elliptic.npz"
    if cache.exists():
        with np.load(cache) as data:
            return data["X"], data["steps"], data["y"], data["edges"]

    import pandas as pd

    ELLIPTIC_DIR.mkdir(parents=True, exist_ok=True)
    frames = {}
    for name in FILES:
        archive = ELLIPTIC_DIR / f"{name}.zip"
        if not archive.exists():
            print(f"[*] Downloading {name}.zip ...")
            urllib.request.urlretrieve(f"{SOURCE_URL}/{name}.zip", archive)
        with zipfile.ZipFile(archive) as z:
            inner = next(n for n in z.namelist() if n.endswith(".csv"))
            with z.open(inner) as f:
                frames[name] = pd.read_csv(f, header=None if "features" in name else 0)

    features = frames["elliptic_txs_features.csv"]
    index = {txid: i for i, txid in enumerate(features[0].astype(np.int64))}
    classes = frames["elliptic_txs_classes.csv"]
    y = np.full(len(features), -1, dtype=np.int8)
    for txid, label in zip(classes["txId"], classes["class"].astype(str)):
        if label in ("1", "2"):
            y[index[txid]] = 1 if label == "1" else 0
    edge_frame = frames["elliptic_txs_edgelist.csv"]
    edges = np.array([(index[a], index[b]) for a, b in zip(edge_frame["txId1"], edge_frame["txId2"])], dtype=np.int64)
    X = features.iloc[:, 2:].to_numpy(dtype=np.float32)
    steps = features[1].to_numpy(dtype=np.int16)
    np.savez_compressed(cache, X=X, steps=steps, y=y, edges=edges)
    return X, steps, y, edges


def _subgraph(keep: np.ndarray, X, y, edges):
    """Nodes where `keep` is true, with edges re-indexed. Time steps never share edges."""
    new_index = np.full(len(keep), -1, dtype=np.int64)
    new_index[keep] = np.arange(keep.sum())
    inside = keep[edges[:, 0]] & keep[edges[:, 1]]
    return X[keep].astype(np.float64), y[keep], new_index[edges[inside]]


def _best_threshold(y: np.ndarray, score: np.ndarray) -> float:
    """Threshold with the highest F1 for the positive class."""
    order = np.argsort(-score)
    hits = np.cumsum(y[order])
    precision = hits / np.arange(1, len(y) + 1)
    recall = hits / max(y.sum(), 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    return float(score[order][int(np.argmax(f1))])


def _metrics(y: np.ndarray, score: np.ndarray, threshold: float) -> dict:
    pred = score >= threshold
    tp, fp, fn = int(np.sum(pred & (y == 1))), int(np.sum(pred & (y == 0))), int(np.sum(~pred & (y == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "roc_auc": round(roc_auc(y, score), 4), "average_precision": round(average_precision(y, score), 4),
        "tp": tp, "fp": fp, "fn": fn, "threshold": round(threshold, 4),
    }


def _train_graphsage(X, y, edges, fit_mask, val_mask, epochs: int, hidden: int, log) -> tuple:
    """Trains and returns (model at its best validation epoch, that epoch, validation threshold)."""
    model = GraphSAGEClassifier(in_dim=X.shape[1], hidden=hidden, seed=0, clip=CLIP)
    best = {"ap": -1.0}

    def checkpoint(step: int) -> None:
        if step % 10:
            return
        score = model.predict_proba(X, edges)[val_mask]
        ap = average_precision(y[val_mask], score)
        if ap > best["ap"]:
            best.update(ap=ap, step=step, params={k: v.copy() for k, v in model.params.items()},
                        threshold=_best_threshold(y[val_mask], score))
        log(f"    epoch {step:4d}  validation average precision {ap:.4f}")

    model.fit(X, edges, np.clip(y, 0, 1), epochs=epochs, lr=0.01, l2=5e-4, mask=fit_mask, callback=checkpoint)
    model.params = best["params"]
    return model, best["step"], best["threshold"]


def run(epochs: int = 100, hidden: int = 64, verbose: bool = True) -> dict:
    log = print if verbose else (lambda *_: None)
    started = time.time()
    X, steps, y, edges = load()
    log(f"[+] Elliptic: {len(X)} transactions, {len(edges)} edges, {int((y == 1).sum())} illicit, "
        f"{int((y == 0).sum())} licit, {int((y == -1).sum())} unlabelled.")

    Xa, ya, ea = _subgraph(steps <= TRAIN_END, X, y, edges)
    Xb, yb, eb = _subgraph(steps >= TEST_START, X, y, edges)
    steps_a = steps[steps <= TRAIN_END]
    fit_mask = (ya >= 0) & (steps_a <= FIT_END)
    val_mask = (ya >= 0) & (steps_a >= VALIDATION_START)
    test_mask = yb >= 0
    y_test = yb[test_mask]
    results = {}

    log("[*] Logistic regression on transaction features (no graph)...")
    mean, std = Xa[fit_mask].mean(axis=0), Xa[fit_mask].std(axis=0)
    std[std < 1e-9] = 1.0
    weights, bias = fit_logistic(np.clip((Xa[fit_mask] - mean) / std, -CLIP, CLIP), ya[fit_mask], l2=10.0)
    linear = lambda M: 1.0 / (1.0 + np.exp(-np.clip(np.clip((M - mean) / std, -CLIP, CLIP) @ weights + bias, -60, 60)))
    results["logistic"] = {"label": "Logistic regression (features only)",
                           **_metrics(y_test, linear(Xb[test_mask]), _best_threshold(ya[val_mask], linear(Xa[val_mask])))}

    log("[*] Same network with the graph removed (a plain neural network)...")
    no_edges = np.zeros((0, 2), dtype=np.int64)
    mlp, mlp_step, mlp_threshold = _train_graphsage(Xa, ya, no_edges, fit_mask, val_mask, epochs, hidden, log)
    results["mlp"] = {"label": "Neural network without the graph", "epochs": mlp_step,
                      **_metrics(y_test, mlp.predict_proba(Xb, no_edges)[test_mask], mlp_threshold)}

    log("[*] GraphSAGE on the transaction graph...")
    gnn, gnn_step, gnn_threshold = _train_graphsage(Xa, ya, ea, fit_mask, val_mask, epochs, hidden, log)
    results["graphsage"] = {"label": "GraphSAGE (this project's GNN)", "epochs": gnn_step,
                            **_metrics(y_test, gnn.predict_proba(Xb, eb)[test_mask], gnn_threshold)}

    log("[*] Isolation Forest (unsupervised, labels never used)...")
    anomaly = TransactionAnomalyDetector().fit(Xa).score(Xb)[test_mask]
    results["isolation_forest"] = {"label": "Isolation Forest (unsupervised)",
                                   **_metrics(y_test, anomaly, float(np.sort(anomaly)[-int(y_test.sum())]))}

    report = {
        "dataset": "Elliptic Bitcoin dataset (Weber et al., 2019)",
        "transactions": int(len(X)), "edges": int(len(edges)), "features": int(X.shape[1]),
        "labelled_illicit": int((y == 1).sum()), "labelled_licit": int((y == 0).sum()),
        "split": f"fit on time steps 1-{FIT_END}, tune on {VALIDATION_START}-{TRAIN_END}, "
                 f"test on {TEST_START}-49 (unseen graphs)",
        "preprocessing": f"standardised features clipped to +-{CLIP:g}, chosen on the validation window",
        "test_illicit": int(y_test.sum()), "test_licit": int((y_test == 0).sum()),
        "architecture": f"GraphSAGE mean, 2 layers, hidden {hidden}, NumPy",
        "reference": REFERENCE,
        "detectors": results,
        "runtime_s": round(time.time() - started, 1),
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1)

    log(f"\n{'Detector (illicit class, test steps 35-49)':44s} {'Prec':>6s} {'Recall':>7s} {'F1':>6s} {'ROC-AUC':>8s} {'AP':>6s}")
    for d in results.values():
        log(f"{d['label']:44s} {d['precision']:6.3f} {d['recall']:7.3f} {d['f1']:6.3f} {d['roc_auc']:8.3f} {d['average_precision']:6.3f}")
    log(f"\n[+] Written to {RESULTS_FILE} ({report['runtime_s']} s)")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the blockchain-layer models on the Elliptic dataset.")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--hidden", type=int, default=64)
    args = parser.parse_args()
    run(epochs=args.epochs, hidden=args.hidden)
