import math
from collections import Counter
from typing import Any, Dict, List

import numpy as np

# Delay assumed when a transaction's parent / child is outside the capture window.
NO_LINK_DELAY_S = 7 * 86400.0

TX_FEATURES = [
    "log_value",        # log1p(total input value, BTC)
    "log_inputs",       # log1p(number of inputs)
    "log_outputs",      # log1p(number of outputs)
    "log_fee_rate",     # log10(fee / value)
    "output_ratio",     # smallest output / largest output
    "equal_out_frac",   # share of outputs carrying the most common amount
    "log_respend",      # log1p(seconds since the funding transaction)
    "log_next_spend",   # log1p(seconds until an output is spent again)
    "log_in_degree",    # funding transactions inside the capture
    "log_out_degree",   # spending transactions inside the capture
]

TX_FEATURE_LABELS = {
    "log_value": "transaction value",
    "log_inputs": "number of inputs",
    "log_outputs": "number of outputs",
    "log_fee_rate": "fee relative to value",
    "output_ratio": "small-to-large output ratio",
    "equal_out_frac": "share of equal-valued outputs",
    "log_respend": "time since the funding transaction",
    "log_next_spend": "time until the outputs were re-spent",
    "log_in_degree": "number of funding transactions",
    "log_out_degree": "number of spending transactions",
}


def respend_delays(transactions: List[Dict[str, Any]], graph) -> tuple:
    """Seconds since the latest funding tx, and until the earliest spending tx, per transaction."""
    since, until = [], []
    for idx, tx in enumerate(transactions):
        preds, succs = graph.preds[idx], graph.succs[idx]
        since.append(tx["_ts"] - max(transactions[p]["_ts"] for p in preds) if preds else NO_LINK_DELAY_S)
        until.append(min(transactions[s]["_ts"] for s in succs) - tx["_ts"] if succs else NO_LINK_DELAY_S)
    return since, until


def build_tx_features(transactions: List[Dict[str, Any]], graph) -> np.ndarray:
    """Blockchain-layer feature matrix [n_tx, len(TX_FEATURES)]; no network-layer fields."""
    since, until = respend_delays(transactions, graph)
    rows = []
    for idx, tx in enumerate(transactions):
        in_amounts = tx.get("input_amounts", [])
        out_amounts = tx.get("output_amounts", [])
        value = sum(in_amounts) or sum(out_amounts)
        fee = float(tx.get("fee") or 0.0)
        if out_amounts and max(out_amounts) > 0:
            ratio = min(out_amounts) / max(out_amounts) if len(out_amounts) > 1 else 1.0
            equal = Counter(round(a, 8) for a in out_amounts).most_common(1)[0][1] / len(out_amounts)
        else:
            ratio, equal = 1.0, 1.0
        rows.append([
            math.log1p(value),
            math.log1p(len(tx.get("input_addresses", []))),
            math.log1p(len(out_amounts)),
            math.log10(fee / value + 1e-8) if value > 0 else -8.0,
            ratio,
            equal if len(out_amounts) > 1 else 0.0,
            math.log1p(max(since[idx], 0.0)),
            math.log1p(max(until[idx], 0.0)),
            math.log1p(len(graph.preds[idx])),
            math.log1p(len(graph.succs[idx])),
        ])
    return np.asarray(rows, dtype=np.float64).reshape(len(transactions), len(TX_FEATURES))
