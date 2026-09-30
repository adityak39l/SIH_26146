import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from config.settings import (
    DEMO_DATA_DIR,
    DEMO_GROUND_TRUTH,
    MEDIUM_RISK_THRESHOLD,
    MODEL_FILE,
    ORIGIN_MIN_CONFIDENCE,
    OUTPUT_DIR,
    PEEL_MIN_HOPS,
    PIPELINE_VERSION,
    RAW_DATA_DIR,
)
from src.correlation.entity_clustering import EntityClusterEngine
from src.correlation.p2p_correlator import P2PTimingCorrelator
from src.graph.graph_builder import HeterogeneousGraphBuilder
from src.ingestion.geo_enricher import OfflineGeoEnricher
from src.ingestion.parser import BulkMetadataParser, Dataset, sha256_file
from src.ml.anomaly_detector import TransactionAnomalyDetector
from src.ml.features import TX_FEATURES, build_tx_features, respend_delays
from src.ml.gnn_classifier import GraphSAGEClassifier
from src.ml.risk_fusion import ABSENT_LABELS, EVIDENCE, RiskFusionModel, build_evidence
from src.ml.xai_explainer import ForensicLeadExplainer, severity_for


@dataclass
class Prepared:
    """Everything the correlation stages derive from a dataset, before any model runs."""

    transactions: List[Dict[str, Any]]
    origin_map: Dict[str, Dict[str, Any]]
    graph: HeterogeneousGraphBuilder
    entities: Dict[str, set]
    address_entity: Dict[str, str]
    chains: List[Dict[str, Any]]
    X: np.ndarray
    edges: np.ndarray
    since: List[float]
    until: List[float]
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Scores:
    anomaly: np.ndarray
    gnn_prob: np.ndarray
    evidence: np.ndarray
    risk: np.ndarray   # 0 - 100
    shap: np.ndarray   # log-odds contribution per evidence signal
    gnn_drivers: np.ndarray  # occlusion sensitivity of the GNN per transaction feature


@dataclass
class ModelBundle:
    gnn: GraphSAGEClassifier
    fusion: RiskFusionModel
    origin_calibration: Optional[Dict[str, Any]]
    meta: Dict[str, Any]


def prepare(dataset: Dataset, enricher: OfflineGeoEnricher = None,
            origin_calibration: Optional[Dict[str, Any]] = None) -> Prepared:
    """Correlates the two layers and builds the graph, clusters, chains and features."""
    enricher = enricher or OfflineGeoEnricher()

    # 1. Network layer -> origin IP per TXID
    origin_map = P2PTimingCorrelator.correlate_origin_ip(dataset.observations, origin_calibration)

    # 2. Join on TXID: each transaction gets a first-seen time and an attributed origin
    transactions, unobserved = [], 0
    for txid, record in dataset.transactions.items():
        tx = dict(record)
        origin = origin_map.get(txid)
        if origin:
            tx["_ts"] = origin["origin_timestamp"]
            tx["_origin"] = origin
            tx["_origin_ip"] = origin["origin_ip"]
            tx["_geo"] = enricher.enrich(origin["origin_ip"])
            origin["resolved"] = origin["confidence"] >= ORIGIN_MIN_CONFIDENCE
            tx["_origin_category"] = tx["_geo"]["category"] if origin["resolved"] else "unresolved"
        elif tx.get("timestamp") is not None:
            tx["_ts"] = float(tx["timestamp"])
            unobserved += 1
        else:
            unobserved += 1
            continue  # no time reference at all: cannot be placed in the flow
        transactions.append(tx)
    transactions.sort(key=lambda t: (t["_ts"], t["txid"]))

    # 3. Graph: IP -> TX -> wallet, plus the transaction flow graph
    graph = HeterogeneousGraphBuilder().build_from_transactions(transactions)

    # 4. Entity resolution and typology tracing
    engine = EntityClusterEngine()
    for tx in transactions:
        tx["_coinjoin"] = engine.coinjoin_score(tx)
        tx["_peel_hops"] = 0
    entities = engine.cluster_common_inputs(
        transactions, skip_txids=[tx["txid"] for tx in transactions if tx["_coinjoin"] >= 0.5])
    chains = engine.detect_peeling_chains(transactions, graph)
    for chain in chains:
        for idx in chain["tx_indices"]:
            transactions[idx]["_peel_hops"] = chain["hops"]
            transactions[idx]["_peel_chain"] = chain["chain_id"]

    # 5. Blockchain-layer features for the models
    X = build_tx_features(transactions, graph)
    since, until = respend_delays(transactions, graph)
    edges = np.asarray(
        [(p, i) for i, preds in enumerate(graph.preds) for p in preds], dtype=np.int64).reshape(-1, 2)

    observed_txids = set(origin_map)
    stats = {
        "observations": len(dataset.observations),
        "transactions": len(transactions),
        "origin_attributed": sum(1 for tx in transactions if tx.get("_origin", {}).get("resolved")),
        "origin_unresolved": sum(1 for tx in transactions if tx.get("_origin") and not tx["_origin"]["resolved"]),
        "unobserved_transactions": unobserved,
        "uncorrelated_observations": sum(
            1 for o in dataset.observations if o["txid"] not in dataset.transactions),
        "observed_txids": len(observed_txids),
        "wallet_addresses": graph.count_nodes("WALLET"),
        "origin_ips": graph.count_nodes("IP"),
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "flow_edges": len(edges),
        "entities": len(entities),
        "peel_chains": len(chains),
        "coinjoin_transactions": sum(1 for tx in transactions if tx["_coinjoin"] >= 0.5),
    }
    return Prepared(transactions, origin_map, graph, entities, engine.address_clusters,
                    chains, X, edges, since, until, stats)


def score(prep: Prepared, models: ModelBundle) -> Scores:
    anomaly = TransactionAnomalyDetector().train_and_score(prep.X)
    gnn_prob = models.gnn.predict_proba(prep.X, prep.edges)
    evidence = build_evidence(prep.transactions, gnn_prob, anomaly, prep.since, prep.until)
    return Scores(anomaly, gnn_prob, evidence, models.fusion.predict_proba(evidence) * 100.0,
                  models.fusion.shap_values(evidence), models.gnn.occlusion(prep.X, prep.edges))


def load_models(model_file: Path = MODEL_FILE, verbose: bool = False) -> ModelBundle:
    """Loads the trained bundle, training it first if it has not been built yet."""
    model_file = Path(model_file)
    if not model_file.exists():
        from src.pipeline.train import train
        if verbose:
            print(f"[*] No trained model at {model_file}; training on simulated traffic...")
        train(model_file=model_file, verbose=verbose)
    with np.load(model_file, allow_pickle=False) as state:
        state = {key: state[key] for key in state.files}
    meta = json.loads(str(state["meta"]))
    meta["sha256"] = sha256_file(model_file)
    meta["file"] = model_file.name
    calibration = {"weights": [float(w) for w in state["origin_weights"]],
                   "bias": float(state["origin_bias"][0])}
    return ModelBundle(GraphSAGEClassifier.from_state(state), RiskFusionModel.from_state(state),
                       calibration, meta)


def analyze(source=None, ground_truth: Optional[Path] = None, verbose: bool = False) -> Dict[str, Any]:
    """Runs the full offline pipeline and returns a JSON-serialisable result."""
    from src.pipeline.cases import build_cases, origin_table
    from src.pipeline.evaluate import evaluate

    started = time.time()
    log = print if verbose else (lambda *_: None)
    if source is None:
        source = DEMO_DATA_DIR if DEMO_DATA_DIR.exists() else RAW_DATA_DIR / "sample_transactions.json"
        if ground_truth is None and source == DEMO_DATA_DIR:
            ground_truth = DEMO_GROUND_TRUTH

    log(f"[*] Ingesting raw metadata from: {source}")
    dataset = BulkMetadataParser.load_dataset(source)
    log(f"[+] {len(dataset.observations)} network observations, "
        f"{len(dataset.transactions)} blockchain transactions from {len(dataset.sources)} file(s).")

    models = load_models(verbose=verbose)
    fusion = models.fusion

    log("[*] Correlating network layer with blockchain layer (first-seen origin, entities, chains)...")
    prep = prepare(dataset, origin_calibration=models.origin_calibration)
    s = prep.stats
    log(f"[+] Origin attributed for {s['origin_attributed']}/{s['transactions']} transactions; "
        f"{s['entities']} entities, {s['peel_chains']} peeling chains, "
        f"{s['coinjoin_transactions']} mixing rounds.")
    log(f"[+] Graph built: {s['graph_nodes']} nodes, {s['graph_edges']} edges.")

    log("[*] Scoring: Isolation Forest + GraphSAGE + risk fusion...")
    scores = score(prep, models)

    log("[*] Building explainable cases (exact Shapley attributions)...")
    cases = build_cases(prep, scores, fusion)
    order = np.argsort(-scores.risk)
    leads = [
        ForensicLeadExplainer.generate_dossier(
            prep.transactions[i], scores.risk[i], scores.evidence[i], scores.shap[i], fusion.base_value)
        for i in order[:25] if scores.risk[i] >= MEDIUM_RISK_THRESHOLD
    ]

    severities = [severity_for(r) for r in scores.risk]
    summary = dict(prep.stats)
    summary.update({
        "flagged_transactions": int(np.sum(scores.risk >= MEDIUM_RISK_THRESHOLD)),
        "cases": len(cases),
        "cases_by_severity": {level: sum(1 for c in cases if c["severity"] == level)
                              for level in ("CRITICAL", "HIGH", "MEDIUM")},
        "transactions_by_severity": {level: severities.count(level)
                                     for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
        "capture_start": prep.transactions[0]["_ts"] if prep.transactions else None,
        "capture_end": prep.transactions[-1]["_ts"] if prep.transactions else None,
    })

    result = {
        "meta": {
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": dataset.sources,
            "model": models.meta,
            "geo_source": "MaxMind GeoLite2 (.mmdb)" if OfflineGeoEnricher().has_real_db else "bundled offline CIDR table",
        },
        "summary": summary,
        "cases": cases,
        "leads": leads,
        "origins": origin_table(prep, scores),
        "model_card": {
            "evidence": [
                {"key": key, "label": label, "absent_label": ABSENT_LABELS.get(key),
                 "weight": round(float(w), 4), "background": round(float(b), 4)}
                for (key, label), w, b in zip(EVIDENCE, fusion.weights, fusion.background)
            ],
            "base_value_log_odds": round(fusion.base_value, 4),
            "tx_features": TX_FEATURES,
            "thresholds": {"medium": MEDIUM_RISK_THRESHOLD, "peel_min_hops": PEEL_MIN_HOPS},
        },
        "evaluation": None,
    }
    if ground_truth and Path(ground_truth).exists():
        with open(ground_truth, "r", encoding="utf-8") as f:
            truth = json.load(f)["transactions"]
        result["evaluation"] = evaluate(prep, scores, cases, truth)

    result["meta"]["runtime_s"] = round(time.time() - started, 2)
    return result


def run_offline_pipeline(sample_file: str = None) -> List[Dict[str, Any]]:
    """Runs the pipeline, prints the ranked leads and writes output/leads.json."""
    result = analyze(sample_file, verbose=True)

    print("\n================ TOP INVESTIGATIVE CASES ================")
    for case in result["cases"][:10]:
        print(f"[{case['severity']:8s}] {case['case_id']} | score {case['risk_score']:5.1f} | "
              f"{case['tx_count']:3d} tx | {case['inflow_btc']:10.4f} BTC | {case['typology']}")
        origin = case["origins"][0] if case["origins"] else None
        if origin:
            print(f"    origin {origin['ip']} ({origin['category_label']}, {origin['country']}, {origin['asn']}), "
                  f"confidence {origin['mean_confidence']:.2f}")
        for factor in case["factors"][:3]:
            print(f"    -> {factor['factor']} ({factor['impact']} log-odds, {factor['share_pct']:.0f}% of push)")
    print("==========================================================")

    evaluation = result["evaluation"]
    if evaluation:
        fused = evaluation["detectors"]["fused"]
        print(f"[=] Against ground truth: precision {fused['precision']:.3f}, recall {fused['recall']:.3f}, "
              f"F1 {fused['f1']:.3f}; origin attribution {evaluation['origin']['accuracy']:.3f}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "leads.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print(f"[+] Full result written to {OUTPUT_DIR / 'leads.json'} ({result['meta']['runtime_s']} s)\n")
    return result["leads"]


if __name__ == "__main__":
    import sys

    # Optional argument: a capture file, or a folder of CSV/JSON/XML files.
    run_offline_pipeline(sys.argv[1] if len(sys.argv) > 1 else None)
