import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

from config.settings import CORRELATION_WINDOW_MS

ORIGIN_SIGNALS = ["lead_term", "sensor_agreement", "relay_ratio", "single_announcer"]


class P2PTimingCorrelator:
    """
    First-seen origin estimator for P2P gossip traffic.

    A transaction is announced by its origin before any relay can re-announce it, so the
    earliest announcer seen across the monitoring sensors is the most likely origin. This
    is a statistical estimate, not a proof: the origin may not be connected to any sensor,
    and Bitcoin Core randomises announcement delays. Every attribution therefore carries a
    confidence built from three signals:

      * lead time        - how far ahead of the next distinct announcer the first one
                           was, relative to the typical relay delay
      * sensor agreement - the share of sensors on which that same IP announced first
      * relay ratio      - how often this IP announces transactions it was *not* first
                           for; an IP that mostly relays is a poor origin candidate

    With a `calibration` (logistic weights fitted against known origins) the confidence
    is the estimated probability that the attribution is correct; without one, a fixed
    heuristic combination of the same signals is used.
    """

    @staticmethod
    def correlate_origin_ip(observations: List[Dict[str, Any]],
                            calibration: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        # Group network announcements by TXID
        tx_broadcasts = defaultdict(list)
        for obs in observations:
            tx_broadcasts[obs["txid"]].append(obs)

        announced = defaultdict(int)  # ip -> transactions it announced at all
        first = defaultdict(int)      # ip -> transactions it announced before anyone else
        origin_map = {}
        for txid, broadcasts in tx_broadcasts.items():
            sorted_broadcasts = sorted(broadcasts, key=lambda x: x["timestamp"])
            earliest = sorted_broadcasts[0]
            origin_ip = earliest["src_ip"]
            for ip in {b["src_ip"] for b in sorted_broadcasts}:
                announced[ip] += 1
            first[origin_ip] += 1

            runner_up = next((b for b in sorted_broadcasts if b["src_ip"] != origin_ip), None)
            lead_ms = (runner_up["timestamp"] - earliest["timestamp"]) * 1000.0 if runner_up else None

            first_per_sensor = {}
            for b in sorted_broadcasts:
                first_per_sensor.setdefault(b.get("dst_ip", "sensor"), b["src_ip"])
            sensor_share = sum(1 for ip in first_per_sensor.values() if ip == origin_ip) / len(first_per_sensor)

            origin_map[txid] = {
                "txid": txid,
                "origin_ip": origin_ip,
                "origin_port": earliest.get("src_port"),
                "origin_timestamp": earliest["timestamp"],
                "first_seen_lead_ms": None if lead_ms is None else round(lead_ms, 1),
                "runner_up_ip": runner_up["src_ip"] if runner_up else None,
                "sensor_count": len(first_per_sensor),
                "sensor_agreement": round(sensor_share, 3),
                "announcer_count": len({b["src_ip"] for b in sorted_broadcasts}),
                "peer_hop_count": len(sorted_broadcasts),
            }

        for info in origin_map.values():
            ip = info["origin_ip"]
            info["relay_ratio"] = round(1.0 - first[ip] / announced[ip], 3)
            info["confidence"] = P2PTimingCorrelator.confidence(info, calibration)
        return origin_map

    @staticmethod
    def signals(info: Dict[str, Any]) -> List[float]:
        """The confidence inputs, in ORIGIN_SIGNALS order."""
        lead_ms = info["first_seen_lead_ms"]
        lead_term = 0.0 if lead_ms is None else 1.0 - math.exp(-max(lead_ms, 0.0) / CORRELATION_WINDOW_MS)
        # With one sensor, "agreement" is trivially 100% and carries no information.
        agreement = info["sensor_agreement"] if info["sensor_count"] > 1 else 0.0
        return [lead_term, agreement, info["relay_ratio"], 1.0 if lead_ms is None else 0.0]

    @staticmethod
    def confidence(info: Dict[str, Any], calibration: Optional[Dict[str, Any]] = None) -> float:
        lead_term, agreement, relay_ratio, single = P2PTimingCorrelator.signals(info)
        if calibration:
            z = calibration["bias"] + sum(
                w * x for w, x in zip(calibration["weights"], (lead_term, agreement, relay_ratio, single)))
            return round(1.0 / (1.0 + math.exp(-max(min(z, 60.0), -60.0))), 3)
        if single:
            # A single announcer: nothing to compare against.
            return 0.30
        base = 0.10 + 0.45 * lead_term + 0.45 * agreement
        return round(min(0.99, base * (1.0 - 0.5 * relay_ratio)), 3)
