from typing import List, Dict, Any
from collections import defaultdict

class P2PTimingCorrelator:
    """
    Reconstructs P2P gossip diffusion trees to isolate the earliest injector/origin IP.
    """

    @staticmethod
    def correlate_origin_ip(transactions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        # Group network broadcasts by TXID
        tx_broadcasts = defaultdict(list)
        for tx in transactions:
            tx_broadcasts[tx["txid"]].append(tx)

        origin_map = {}
        for txid, broadcasts in tx_broadcasts.items():
            # Sort by broadcast timestamp ascending
            sorted_broadcasts = sorted(broadcasts, key=lambda x: x["timestamp"])
            earliest = sorted_broadcasts[0]
            
            origin_map[txid] = {
                "txid": txid,
                "origin_ip": earliest["src_ip"],
                "origin_timestamp": earliest["timestamp"],
                "origin_country": earliest.get("geo_country", "UNKNOWN"),
                "origin_asn": earliest.get("asn", "UNKNOWN"),
                "peer_hop_count": len(sorted_broadcasts)
            }
        return origin_map
