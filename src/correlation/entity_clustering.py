from collections import Counter
from typing import Any, Dict, Iterable, List, Set

from config.settings import (
    COINJOIN_MIN_EQUAL_OUTPUTS,
    COINJOIN_MIN_INPUTS,
    PEEL_MAX_GAP_S,
    PEEL_MAX_RATIO,
    PEEL_MIN_HOPS,
)


class EntityClusterEngine:
    """
    Implements the Common-Input Ownership Heuristic (CIOH), equal-output mixing
    (CoinJoin) detection and multi-hop peeling chain tracing.
    """

    def __init__(self):
        self.address_clusters: Dict[str, str] = {}  # address -> entity id
        self._parent: Dict[str, str] = {}

    def _find(self, address: str) -> str:
        root = address
        while self._parent.setdefault(root, root) != root:
            root = self._parent[root]
        while self._parent[address] != root:  # path compression
            self._parent[address], address = root, self._parent[address]
        return root

    def cluster_common_inputs(self, transactions: List[Dict[str, Any]],
                              skip_txids: Iterable[str] = ()) -> Dict[str, Set[str]]:
        """
        Addresses co-spent as inputs of one transaction are controlled by one entity.
        Transactions in `skip_txids` are excluded: a CoinJoin deliberately combines the
        inputs of unrelated parties, and clustering across it would merge them all.
        """
        skip = set(skip_txids)
        for tx in transactions:
            inputs = list(dict.fromkeys(tx.get("input_addresses", [])))
            if len(inputs) < 2 or tx["txid"] in skip:
                continue
            root = self._find(inputs[0])
            for address in inputs[1:]:
                self._parent[self._find(address)] = root

        groups: Dict[str, Set[str]] = {}
        for address in self._parent:
            groups.setdefault(self._find(address), set()).add(address)

        entity_map = {}
        ordered = sorted(groups.values(), key=lambda s: (-len(s), min(s)))
        for cluster_id, addr_set in enumerate(ordered, start=1):
            entity_id = f"ENTITY_{cluster_id:03d}"
            entity_map[entity_id] = addr_set
            for address in addr_set:
                self.address_clusters[address] = entity_id
        return entity_map

    @staticmethod
    def coinjoin_score(tx: Dict[str, Any]) -> float:
        """
        Share of outputs that carry the single most common amount, for transactions with
        enough distinct inputs and equal outputs to look like a mixing round; else 0.
        """
        amounts = [round(a, 8) for a in tx.get("output_amounts", [])]
        if len(set(tx.get("input_addresses", []))) < COINJOIN_MIN_INPUTS or not amounts:
            return 0.0
        equal = Counter(amounts).most_common(1)[0][1]
        if equal < COINJOIN_MIN_EQUAL_OUTPUTS:
            return 0.0
        return round(equal / len(amounts), 3)

    @staticmethod
    def is_peel_shaped(tx: Dict[str, Any]) -> bool:
        """One spender, two outputs: a small payment and a much larger remainder."""
        out_amounts = tx.get("output_amounts", [])
        if len(out_amounts) != 2 or not 1 <= len(tx.get("input_addresses", [])) <= 2:
            return False
        if max(out_amounts) <= 0:
            return False
        return min(out_amounts) / max(out_amounts) <= PEEL_MAX_RATIO

    @staticmethod
    def detect_peeling_chains(transactions: List[Dict[str, Any]], graph) -> List[Dict[str, Any]]:
        """
        Traces chains in which each hop peels a small amount off and the remainder is
        re-spent by the next peel-shaped hop within PEEL_MAX_GAP_S. A single
        (1-input, 2-output) transaction is the most common shape on the network and is
        not evidence on its own; only chains of PEEL_MIN_HOPS or more are reported.

        `transactions` must be time-sorted with `_ts`; `graph` is the matching
        HeterogeneousGraphBuilder.
        """
        peel = [EntityClusterEngine.is_peel_shaped(tx) for tx in transactions]

        def next_hop(idx: int):
            tx = transactions[idx]
            amounts = tx["output_amounts"]
            remainder_addr = tx["output_addresses"][amounts.index(max(amounts))]
            nxt = graph.spent_by.get((idx, remainder_addr))
            if nxt is None or not peel[nxt]:
                return None
            if transactions[nxt]["_ts"] - tx["_ts"] > PEEL_MAX_GAP_S:
                return None
            return nxt

        successor = {i: next_hop(i) for i in range(len(transactions)) if peel[i]}
        has_predecessor = {nxt for nxt in successor.values() if nxt is not None}

        chains = []
        for start in sorted(successor):
            if start in has_predecessor:
                continue
            path, cursor = [start], successor[start]
            while cursor is not None:
                path.append(cursor)
                cursor = successor.get(cursor)
            if len(path) < PEEL_MIN_HOPS:
                continue
            peeled = [min(transactions[i]["output_amounts"]) for i in path]
            chains.append({
                "chain_id": f"PEEL_{len(chains) + 1:03d}",
                "tx_indices": path,
                "txids": [transactions[i]["txid"] for i in path],
                "hops": len(path),
                "peeled_total": round(sum(peeled), 8),
                "start_amount": round(sum(transactions[path[0]]["input_amounts"]), 8),
                "remainder": round(max(transactions[path[-1]]["output_amounts"]), 8),
                "duration_s": round(transactions[path[-1]]["_ts"] - transactions[path[0]]["_ts"], 3),
            })
        return chains
