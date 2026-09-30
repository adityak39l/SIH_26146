from collections import Counter, defaultdict
from typing import Any, Dict, List

import numpy as np

from config.settings import MEDIUM_RISK_THRESHOLD, ORIGIN_MIN_CONFIDENCE, PEEL_MIN_HOPS
from src.ml.features import TX_FEATURE_LABELS, TX_FEATURES
from src.ml.xai_explainer import DISCLAIMER, ForensicLeadExplainer, evidence_hash, severity_for


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def _components(n: int, members: List[int], preds: List[List[int]]) -> List[List[int]]:
    """Connected components of the flow graph restricted to `members`."""
    inside = set(members)
    parent = {i: i for i in members}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in members:
        for p in preds[i]:
            if p in inside:
                parent[find(i)] = find(p)
    groups = defaultdict(list)
    for i in members:
        groups[find(i)].append(i)
    return [sorted(group) for group in groups.values()]


def build_cases(prep, scores, fusion) -> List[Dict[str, Any]]:
    """
    Groups flagged transactions that are linked by money flow into cases, because an
    investigator works a laundering operation, not a list of isolated transactions.
    An unflagged transaction sitting between two flagged ones is kept as a bridge so
    that one weak hop does not split an operation in two.
    """
    txs, graph, risk = prep.transactions, prep.graph, scores.risk
    flagged = {i for i in range(len(txs)) if risk[i] >= MEDIUM_RISK_THRESHOLD}
    bridges = {
        i for i in range(len(txs)) if i not in flagged
        and any(p in flagged for p in graph.preds[i]) and any(s in flagged for s in graph.succs[i])
    }
    spent_anywhere = {(parent, address) for parent, _, address, _ in graph.tx_edges}

    cases = []
    for members in _components(len(txs), sorted(flagged | bridges), graph.preds):
        core = [i for i in members if i in flagged]
        local = {idx: pos for pos, idx in enumerate(members)}

        flow = defaultdict(float)
        for parent, child, _, amount in graph.tx_edges:
            if parent in local and child in local:
                flow[(local[parent], local[child])] += amount
        funded_inside = {child for _, child in flow}

        inflow = sum(sum(txs[i]["input_amounts"]) for i in members if local[i] not in funded_inside)
        first_ts, last_ts = txs[members[0]]["_ts"], txs[members[-1]]["_ts"]

        # Outputs that leave the case: unspent when the capture ends, or spent elsewhere.
        terminals = []
        for i in members:
            for address, amount in zip(txs[i]["output_addresses"], txs[i]["output_amounts"]):
                spender = graph.spent_by.get((i, address))
                if spender is None or spender not in local:
                    terminals.append({
                        "address": address,
                        "amount_btc": round(amount, 8),
                        "status": "unspent at end of capture" if (i, address) not in spent_anywhere
                                  else "spent outside this case",
                    })
        terminals.sort(key=lambda t: t["amount_btc"], reverse=True)

        origins = _origins(txs, members)
        tags = _typology(txs, members, local, flow)
        mean_shap = scores.shap[core].mean(axis=0)
        mean_evidence = scores.evidence[core].mean(axis=0)
        peak = max(core, key=lambda i: risk[i])
        entity_ids = sorted({prep.address_entity[a] for i in members
                             for a in txs[i]["input_addresses"] if a in prep.address_entity})
        peel_hops = max((txs[i].get("_peel_hops", 0) for i in members), default=0)
        peeled = sum(min(txs[i]["output_amounts"]) for i in members
                     if txs[i].get("_peel_hops", 0) >= PEEL_MIN_HOPS)

        case = {
            "risk_score": round(float(risk[peak]), 1),
            "mean_risk": round(float(np.mean(risk[core])), 1),
            "severity": severity_for(float(risk[peak])),
            "typology": " + ".join(tags),
            "typology_tags": tags,
            "tx_count": len(members),
            "inflow_btc": round(inflow, 8),
            "peel_hops": peel_hops,
            "peeled_btc": round(peeled, 8),
            "first_seen": first_ts,
            "last_seen": last_ts,
            "duration": _duration(last_ts - first_ts),
            "origins": origins,
            "entities": [{"entity_id": e, "addresses": len(prep.entities[e])} for e in entity_ids],
            "terminal_outputs": terminals[:6],
            "terminal_output_count": len(terminals),
            "factors": ForensicLeadExplainer.factors(mean_evidence, mean_shap),
            "base_value_log_odds": round(fusion.base_value, 4),
            "gnn_drivers": _gnn_drivers(scores.gnn_drivers[core].mean(axis=0)),
            "transactions": [_tx_row(txs[i], risk[i], scores, i, i in bridges) for i in members],
            "edges": [[a, b, round(amount, 8)] for (a, b), amount in sorted(flow.items())],
            "notes": DISCLAIMER,
        }
        case["narrative"] = _narrative(case)
        cases.append(case)

    cases.sort(key=lambda c: (-c["risk_score"], -c["inflow_btc"]))
    for rank, case in enumerate(cases, start=1):
        case["case_id"] = f"CASE-{rank:03d}"
        case["evidence_hash"] = evidence_hash(case)
    return cases


def _tx_row(tx: Dict[str, Any], risk: float, scores, idx: int, bridge: bool) -> Dict[str, Any]:
    origin, geo = tx.get("_origin", {}), tx.get("_geo", {})
    return {
        "txid": tx["txid"],
        "timestamp": tx["_ts"],
        "risk_score": round(float(risk), 1),
        "severity": severity_for(float(risk)),
        "bridge": bridge,
        "inputs": len(tx["input_addresses"]),
        "outputs": len(tx["output_addresses"]),
        "value_btc": round(sum(tx["input_amounts"]), 8),
        "fee_btc": tx.get("fee"),
        "origin_ip": origin.get("origin_ip"),
        "origin_confidence": origin.get("confidence"),
        "origin_lead_ms": origin.get("first_seen_lead_ms"),
        "origin_country": geo.get("country"),
        "origin_category": geo.get("category"),
        "gnn_prob": round(float(scores.gnn_prob[idx]), 4),
        "anomaly": round(float(scores.anomaly[idx]), 4),
        "evidence": [round(float(v), 3) for v in scores.evidence[idx]],
        "shap": [round(float(v), 3) for v in scores.shap[idx]],
    }


def _gnn_drivers(mean_drop: np.ndarray, top: int = 4) -> List[Dict[str, Any]]:
    """The transaction features the GNN reacted to most, by mean occlusion sensitivity."""
    order = np.argsort(-np.abs(mean_drop))[:top]
    return [{"feature": TX_FEATURES[j], "label": TX_FEATURE_LABELS[TX_FEATURES[j]],
             "log_odds_drop": round(float(mean_drop[j]), 3)} for j in order]


def _origins(txs: List[Dict[str, Any]], members: List[int]) -> List[Dict[str, Any]]:
    grouped = defaultdict(list)
    for i in members:
        if txs[i].get("_origin_ip"):
            grouped[txs[i]["_origin_ip"]].append(txs[i])
    rows = []
    for ip, items in grouped.items():
        geo = items[0]["_geo"]
        rows.append({
            "ip": ip,
            "transactions": len(items),
            "country": geo["country"],
            "asn": geo["asn"],
            "asn_org": geo["asn_org"],
            "category": geo["category"],
            "category_label": geo["category_label"],
            "mean_confidence": round(float(np.mean([t["_origin"]["confidence"] for t in items])), 3),
        })
    for row in rows:
        # Below the threshold the first announcer is more likely a relay than the origin.
        row["resolved"] = row["mean_confidence"] >= ORIGIN_MIN_CONFIDENCE
    rows.sort(key=lambda r: (not r["resolved"], -r["transactions"], r["ip"]))
    return rows


def _typology(txs, members, local, flow) -> List[str]:
    children, parents = Counter(a for a, _ in flow), Counter(b for _, b in flow)
    tags = []
    if any(txs[i]["_coinjoin"] >= 0.5 for i in members):
        tags.append("CoinJoin mixing")
    if any(txs[i].get("_peel_hops", 0) >= PEEL_MIN_HOPS for i in members):
        tags.append("Peeling chain")
    if any(children[local[i]] >= 4 and txs[i]["_coinjoin"] < 0.5 for i in members):
        tags.append("Fan-out / fan-in structuring")
    if any(parents[local[i]] >= 2 and len(txs[i]["output_addresses"]) == 1 for i in members):
        if "Fan-out / fan-in structuring" not in tags:
            tags.append("Consolidation sweep")
    return tags or ["Anomalous flow"]


def _narrative(case: Dict[str, Any]) -> str:
    parts = [f"{case['tx_count']} linked transaction{'s' if case['tx_count'] != 1 else ''} carrying "
             f"{case['inflow_btc']:.4f} BTC over {case['duration']}."]
    tags = case["typology_tags"]
    if "CoinJoin mixing" in tags:
        parts.append("An equal-output mixing round breaks the link between senders and receivers.")
    if "Peeling chain" in tags:
        parts.append(f"A {case['peel_hops']}-hop peeling chain splits off {case['peeled_btc']:.4f} BTC in small "
                     f"outputs while forwarding the remainder each hop.")
    if "Fan-out / fan-in structuring" in tags:
        parts.append("Funds are fanned out into near-equal parts, moved one hop each and re-aggregated.")
    if "Consolidation sweep" in tags:
        parts.append("Outputs from earlier hops are swept together into a single address.")
    resolved = [o for o in case["origins"] if o["resolved"]]
    unresolved = sum(o["transactions"] for o in case["origins"] if not o["resolved"])
    if resolved:
        top = resolved[0]
        parts.append(f"The origin was resolved to {len(resolved)} IP address"
                     f"{'es' if len(resolved) != 1 else ''}; most frequent is {top['ip']} "
                     f"({top['category_label']}, {top['country']}, {top['asn']}) with mean attribution "
                     f"confidence {top['mean_confidence']:.2f}.")
        if any(o["category"] == "tor_exit" for o in resolved):
            parts.append("A Tor exit identifies the relay, not the sender.")
    if unresolved:
        parts.append(f"For {unresolved} transaction{'s' if unresolved != 1 else ''} the origin could not be "
                     f"resolved: only relays were seen announcing.")
    if case["terminal_outputs"]:
        top = case["terminal_outputs"][0]
        parts.append(f"Largest onward output: {top['amount_btc']:.4f} BTC at {top['address']} ({top['status']}).")
    return " ".join(parts)


def origin_table(prep, scores, limit: int = 40) -> List[Dict[str, Any]]:
    """Per origin IP: how many transactions it announced first and how many were flagged."""
    grouped = defaultdict(list)
    for idx, tx in enumerate(prep.transactions):
        if tx.get("_origin_ip"):
            grouped[tx["_origin_ip"]].append(idx)
    rows = []
    for ip, indices in grouped.items():
        geo = prep.transactions[indices[0]]["_geo"]
        risks = scores.risk[indices]
        rows.append({
            "ip": ip,
            "country": geo["country"],
            "asn": geo["asn"],
            "asn_org": geo["asn_org"],
            "category": geo["category"],
            "category_label": geo["category_label"],
            "transactions": len(indices),
            "flagged": int(np.sum(risks >= MEDIUM_RISK_THRESHOLD)),
            "max_risk": round(float(risks.max()), 1),
            "mean_confidence": round(float(np.mean(
                [prep.transactions[i]["_origin"]["confidence"] for i in indices])), 3),
        })
    rows.sort(key=lambda r: (-r["flagged"], -r["max_risk"], -r["transactions"], r["ip"]))
    return rows[:limit]
