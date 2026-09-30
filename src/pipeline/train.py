"""
Trains the GraphSAGE classifier and the risk-fusion model on simulated traffic and
writes the bundle to data/models/.

The two models are fitted on disjoint simulations: the fusion model must see the GNN's
behaviour on traffic the GNN was not trained on, otherwise it learns to over-trust it.
The demo capture (seed 7) is used by neither.

Usage:
    python -m src.pipeline.train
"""
import json
from pathlib import Path

import numpy as np

from config.settings import MODEL_FILE, PIPELINE_VERSION
from src.ml.anomaly_detector import TransactionAnomalyDetector
from src.ml.features import TX_FEATURES
from src.ml.gnn_classifier import GraphSAGEClassifier
from src.correlation.p2p_correlator import ORIGIN_SIGNALS, P2PTimingCorrelator
from src.ml.risk_fusion import EVIDENCE_KEYS, RiskFusionModel, build_evidence, fit_logistic
from src.simulation.generator import TrafficSimulator

GNN_SEEDS = list(range(101, 113))
FUSION_SEEDS = list(range(201, 207))


def _simulate(seed: int, origin_calibration: dict):
    from src.pipeline.engine import prepare

    sim = TrafficSimulator(seed=seed).generate()
    prep = prepare(sim.dataset(), origin_calibration=origin_calibration)
    y = np.array([sim.truth[tx["txid"]]["label"] for tx in prep.transactions], dtype=np.float64)
    return prep, y


def _calibrate_origin(seeds, log) -> dict:
    """
    Fits P(first-seen announcer is the true origin | lead time, sensor agreement, relay
    ratio). Unbalanced fit: the output has to be a probability, not a detection score.
    """
    signals, correct = [], []
    for seed in seeds:
        sim = TrafficSimulator(seed=seed).generate()
        for txid, info in P2PTimingCorrelator.correlate_origin_ip(sim.observations).items():
            signals.append(P2PTimingCorrelator.signals(info))
            correct.append(float(info["origin_ip"] == sim.truth[txid]["origin_ip"]))
    weights, bias = fit_logistic(np.asarray(signals), np.asarray(correct), l2=0.1, balanced=False)
    for key, weight in zip(ORIGIN_SIGNALS, weights):
        log(f"    {key:17s} weight {weight:+.3f}")
    log(f"    {'bias':17s}        {bias:+.3f}  "
        f"(first-seen correct in {np.mean(correct):.1%} of {len(correct)} transactions)")
    return {"weights": [float(w) for w in weights], "bias": float(bias), "transactions": len(correct)}


def train(model_file: Path = MODEL_FILE, verbose: bool = True, epochs: int = 300) -> dict:
    log = print if verbose else (lambda *_: None)

    log("[*] Calibrating origin-attribution confidence against known origins...")
    calibration = _calibrate_origin(GNN_SEEDS + FUSION_SEEDS, log)

    log(f"[*] Simulating {len(GNN_SEEDS)} training captures for GraphSAGE...")
    features, edges, labels, offset = [], [], [], 0
    for seed in GNN_SEEDS:
        prep, y = _simulate(seed, calibration)
        features.append(prep.X)
        edges.append(prep.edges + offset)
        labels.append(y)
        offset += len(y)
    X, edge_index, y = np.vstack(features), np.vstack(edges), np.concatenate(labels)
    log(f"[+] {len(y)} transactions, {len(edge_index)} flow edges, {int(y.sum())} in laundering scenarios.")

    gnn = GraphSAGEClassifier(in_dim=X.shape[1], hidden=24, seed=0)
    history = gnn.fit(X, edge_index, y, epochs=epochs, verbose=verbose)

    log(f"[*] Simulating {len(FUSION_SEEDS)} held-out captures for risk fusion...")
    evidence, labels = [], []
    for seed in FUSION_SEEDS:
        prep, y_f = _simulate(seed, calibration)
        anomaly = TransactionAnomalyDetector().train_and_score(prep.X)
        gnn_prob = gnn.predict_proba(prep.X, prep.edges)
        evidence.append(build_evidence(prep.transactions, gnn_prob, anomaly, prep.since, prep.until))
        labels.append(y_f)
    E, y_f = np.vstack(evidence), np.concatenate(labels)
    fusion = RiskFusionModel().fit(E, y_f)
    for key, weight in zip(EVIDENCE_KEYS, fusion.weights):
        log(f"    {key:15s} weight {weight:+.3f}")
    log(f"    {'bias':15s}        {fusion.bias:+.3f}")

    meta = {
        "pipeline_version": PIPELINE_VERSION,
        "architecture": f"GraphSAGE mean, 2 layers, hidden {gnn.hidden}; logistic risk fusion",
        "training_data": "simulated traffic (src/simulation/generator.py)",
        "gnn_seeds": GNN_SEEDS,
        "fusion_seeds": FUSION_SEEDS,
        "gnn_train_transactions": int(len(y)),
        "gnn_train_positives": int(y.sum()),
        "gnn_final_loss": round(history[-1], 5),
        "fusion_train_transactions": int(len(y_f)),
        "tx_features": TX_FEATURES,
        "evidence": EVIDENCE_KEYS,
        "origin_signals": ORIGIN_SIGNALS,
        "origin_calibration_transactions": calibration["transactions"],
    }
    model_file = Path(model_file)
    model_file.parent.mkdir(parents=True, exist_ok=True)
    np.savez(model_file, meta=np.array(json.dumps(meta)), origin_weights=np.array(calibration["weights"]),
             origin_bias=np.array([calibration["bias"]]), **gnn.state(), **fusion.state())
    log(f"[+] Model bundle written to {model_file}")
    return meta


if __name__ == "__main__":
    train()
