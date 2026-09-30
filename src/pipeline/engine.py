from config.settings import RAW_DATA_DIR
from src.ingestion.parser import BulkMetadataParser
from src.correlation.p2p_correlator import P2PTimingCorrelator
from src.correlation.entity_clustering import EntityClusterEngine
from src.graph.graph_builder import HeterogeneousGraphBuilder
from src.ml.anomaly_detector import TransactionAnomalyDetector
from src.ml.xai_explainer import ForensicLeadExplainer

def run_offline_pipeline(sample_file: str = None):
    file_path = sample_file or (RAW_DATA_DIR / "sample_transactions.json")
    print(f"[*] Ingesting raw metadata from: {file_path}")
    transactions = BulkMetadataParser.parse_file(str(file_path))
    print(f"[+] Successfully parsed {len(transactions)} transaction records.")

    # 1. P2P Correlation
    print("[*] Correlating network-layer timestamps with blockchain TXIDs...")
    origin_map = P2PTimingCorrelator.correlate_origin_ip(transactions)
    print(f"[+] Identified origin nodes for {len(origin_map)} unique TXIDs.")

    # 2. Entity Clustering
    print("[*] Running Common-Input Heuristic clustering & peeling chain detection...")
    cluster_engine = EntityClusterEngine()
    clusters = cluster_engine.cluster_common_inputs(transactions)
    peeling_chains = {p["txid"]: p for p in cluster_engine.detect_peeling_chains(transactions)}
    print(f"[+] Resolved {len(clusters)} actor entities and {len(peeling_chains)} peeling chain hops.")

    # 3. Graph Construction
    print("[*] Constructing heterogeneous graph...")
    builder = HeterogeneousGraphBuilder()
    graph = builder.build_from_transactions(transactions)
    print(f"[+] Graph built: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.")

    # 4. AI/ML Anomaly Scoring
    print("[*] Running Unsupervised Anomaly Detection...")
    detector = TransactionAnomalyDetector()
    anomaly_scores = detector.train_and_score(transactions)

    # 5. XAI Explainability & Dossier Generation
    print("[*] Generating Explainable Intelligence Dossiers (XAI)...")
    leads = []
    for idx, tx in enumerate(transactions):
        txid = tx["txid"]
        origin = origin_map.get(txid, {})
        is_peel = txid in peeling_chains
        lead = ForensicLeadExplainer.generate_dossier(txid, anomaly_scores[idx], origin, is_peel)
        leads.append(lead)

    print("\n================ TOP INVESTIGATIVE LEADS (NTRO) ================")
    for lead in sorted(leads, key=lambda x: x["risk_score"], reverse=True):
        print(f"[{lead['severity']}] TXID: {lead['txid'][:18]}... | Score: {lead['risk_score']}/100 | Origin IP: {lead['origin_ip']} ({lead['origin_country']})")
        for f in lead["top_contributing_factors"]:
            print(f"    -> {f['factor']} ({f['impact']})")
    print("=================================================================\n")
    return leads

if __name__ == "__main__":
    run_offline_pipeline()
