from typing import List, Dict, Set, Any
from collections import defaultdict

class EntityClusterEngine:
    """
    Implements Common-Input Ownership Heuristic (CIOH) and Peeling Chain Detection.
    """

    def __init__(self):
        self.address_clusters = {}  # address -> cluster_id

    def cluster_common_inputs(self, transactions: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
        """
        If multiple addresses are co-spent in the same transaction input,
        they belong to the same entity cluster.
        """
        clusters = []
        for tx in transactions:
            inputs = set(tx.get("input_addresses", []))
            if len(inputs) > 1:
                # Merge into existing cluster or create new
                matched_indices = []
                for idx, cluster in enumerate(clusters):
                    if not cluster.isdisjoint(inputs):
                        matched_indices.append(idx)

                if matched_indices:
                    merged = inputs
                    for idx in sorted(matched_indices, reverse=True):
                        merged = merged.union(clusters.pop(idx))
                    clusters.append(merged)
                else:
                    clusters.append(inputs)

        entity_map = {}
        for cluster_id, addr_set in enumerate(clusters, start=1):
            entity_map[f"ENTITY_{cluster_id:03d}"] = addr_set
        return entity_map

    @staticmethod
    def detect_peeling_chains(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects repetitive (1-input, 2-output) peeling chain structures.
        """
        peeling_suspects = []
        for tx in transactions:
            inputs = tx.get("input_addresses", [])
            outputs = tx.get("output_addresses", [])
            out_amounts = tx.get("output_amounts", [])

            if len(inputs) == 1 and len(outputs) == 2:
                # Typically 1 small cashout amount and 1 large change amount
                ratio = min(out_amounts) / max(out_amounts) if max(out_amounts) > 0 else 0
                if ratio < 0.20:  # Peeling ratio signature
                    peeling_suspects.append({
                        "txid": tx["txid"],
                        "suspect_type": "Peeling Chain Hop",
                        "peeled_amount": min(out_amounts),
                        "change_amount": max(out_amounts),
                        "confidence": 0.88
                    })
        return peeling_suspects
