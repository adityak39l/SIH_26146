from typing import List, Dict, Any

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

class HeterogeneousGraphBuilder:
    """
    Constructs an in-memory directed heterogeneous graph linking:
    [IP Node] -> (BROADCASTS) -> [TXID Node] -> (SPENDS_FROM) -> [Wallet Address]
    Uses NetworkX when installed, with an internal pure-Python fallback.
    """

    def __init__(self):
        if HAS_NETWORKX:
            self.graph = nx.MultiDiGraph()
        else:
            self.nodes = {}
            self.edges = []

    def build_from_transactions(self, transactions: List[Dict[str, Any]]):
        if HAS_NETWORKX:
            for tx in transactions:
                txid = tx["txid"]
                src_ip = tx["src_ip"]

                self.graph.add_node(txid, type="TXID", fee=tx.get("fee", 0))
                self.graph.add_node(src_ip, type="IP", country=tx.get("geo_country"), asn=tx.get("asn"))
                self.graph.add_edge(src_ip, txid, relationship="BROADCASTED_BY", timestamp=tx["timestamp"])

                for in_addr in tx.get("input_addresses", []):
                    self.graph.add_node(in_addr, type="WALLET")
                    self.graph.add_edge(in_addr, txid, relationship="SPENDS_INPUT")

                for out_addr in tx.get("output_addresses", []):
                    self.graph.add_node(out_addr, type="WALLET")
                    self.graph.add_edge(txid, out_addr, relationship="OUTPUTS_TO")
            return self.graph
        else:
            for tx in transactions:
                txid = tx["txid"]
                src_ip = tx["src_ip"]
                self.nodes[txid] = {"type": "TXID", "fee": tx.get("fee", 0)}
                self.nodes[src_ip] = {"type": "IP", "country": tx.get("geo_country"), "asn": tx.get("asn")}
                self.edges.append((src_ip, txid, "BROADCASTED_BY"))

                for in_addr in tx.get("input_addresses", []):
                    self.nodes[in_addr] = {"type": "WALLET"}
                    self.edges.append((in_addr, txid, "SPENDS_INPUT"))

                for out_addr in tx.get("output_addresses", []):
                    self.nodes[out_addr] = {"type": "WALLET"}
                    self.edges.append((txid, out_addr, "OUTPUTS_TO"))
            return self

    def number_of_nodes(self):
        return len(self.nodes)

    def number_of_edges(self):
        return len(self.edges)
