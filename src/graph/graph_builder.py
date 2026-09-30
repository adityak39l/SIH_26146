from typing import Any, Dict, List


class HeterogeneousGraphBuilder:
    """
    Builds the in-memory graph used by the correlation and ML stages.

    Heterogeneous view (what the investigator sees):
        [IP] -(ANNOUNCED)-> [TX] ;  [WALLET] -(SPENT_IN)-> [TX] -(PAID_TO)-> [WALLET]

    Transaction flow view (what the GNN consumes): a directed edge A -> B whenever
    transaction B spends an address that transaction A paid to. Bulk metadata carries
    addresses rather than outpoints, so a spend is linked to the most recent earlier
    transaction that paid that address.

    Pure Python, no external graph library.
    """

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[tuple] = []
        self.tx_edges: List[tuple] = []  # (src_index, dst_index, address, amount)
        self.preds: List[List[int]] = []
        self.succs: List[List[int]] = []
        self.spent_by: Dict[tuple, int] = {}  # (tx_index, address) -> spending tx index

    def build_from_transactions(self, transactions: List[Dict[str, Any]]):
        """`transactions` must be sorted by first-seen time and carry `_ts` and `_origin_ip`."""
        n = len(transactions)
        self.preds = [[] for _ in range(n)]
        self.succs = [[] for _ in range(n)]
        last_paid: Dict[str, tuple] = {}  # address -> (tx_index, amount)

        for idx, tx in enumerate(transactions):
            txid = tx["txid"]
            self.nodes[txid] = {"type": "TXID", "fee": tx.get("fee", 0)}

            origin_ip = tx.get("_origin_ip")
            if origin_ip:
                self.nodes.setdefault(origin_ip, {"type": "IP"})
                self.edges.append((origin_ip, txid, "ANNOUNCED"))

            for in_addr in tx.get("input_addresses", []):
                self.nodes.setdefault(in_addr, {"type": "WALLET"})
                self.edges.append((in_addr, txid, "SPENT_IN"))
                if in_addr in last_paid:
                    parent, amount = last_paid.pop(in_addr)
                    self.tx_edges.append((parent, idx, in_addr, amount))
                    self.spent_by[(parent, in_addr)] = idx
                    if idx not in self.succs[parent]:
                        self.succs[parent].append(idx)
                        self.preds[idx].append(parent)

            for out_addr, amount in zip(tx.get("output_addresses", []), tx.get("output_amounts", [])):
                self.nodes.setdefault(out_addr, {"type": "WALLET"})
                self.edges.append((txid, out_addr, "PAID_TO"))
                last_paid[out_addr] = (idx, amount)
        return self

    def number_of_nodes(self) -> int:
        return len(self.nodes)

    def number_of_edges(self) -> int:
        return len(self.edges)

    def count_nodes(self, node_type: str) -> int:
        return sum(1 for node in self.nodes.values() if node["type"] == node_type)
