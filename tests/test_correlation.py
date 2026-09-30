import unittest

from src.correlation.entity_clustering import EntityClusterEngine
from src.correlation.p2p_correlator import P2PTimingCorrelator
from src.graph.graph_builder import HeterogeneousGraphBuilder


def obs(ts, src, dst, txid="t1"):
    return {"timestamp": ts, "src_ip": src, "dst_ip": dst, "txid": txid}


def tx(txid, ts, inputs, outputs):
    return {"txid": txid, "_ts": ts,
            "input_addresses": [a for a, _ in inputs], "input_amounts": [v for _, v in inputs],
            "output_addresses": [a for a, _ in outputs], "output_amounts": [v for _, v in outputs]}


class CorrelatorTests(unittest.TestCase):
    def test_earliest_announcer_is_the_origin(self):
        origin = P2PTimingCorrelator.correlate_origin_ip([
            obs(10.300, "relay", "s1"), obs(10.010, "origin", "s1"), obs(10.020, "origin", "s2"),
        ])["t1"]
        self.assertEqual(origin["origin_ip"], "origin")
        self.assertEqual(origin["runner_up_ip"], "relay")
        self.assertAlmostEqual(origin["first_seen_lead_ms"], 290.0, places=0)
        self.assertEqual(origin["sensor_agreement"], 1.0)

    def test_clear_lead_is_more_confident_than_a_photo_finish(self):
        clear = P2PTimingCorrelator.correlate_origin_ip(
            [obs(1.0, "a", "s1"), obs(1.0, "a", "s2"), obs(1.9, "b", "s1")])["t1"]
        close = P2PTimingCorrelator.correlate_origin_ip(
            [obs(1.0, "a", "s1"), obs(1.001, "b", "s2"), obs(1.002, "b", "s1")])["t1"]
        self.assertGreater(clear["confidence"], close["confidence"])

    def test_an_ip_that_mostly_relays_is_a_weak_origin(self):
        observations = []
        for i in range(10):  # "relay" announces every transaction but is first only once
            txid = f"t{i}"
            observations += [obs(i + 0.30, "relay", "s1", txid), obs(i + 0.01, f"user{i}", "s1", txid)]
        observations += [obs(99.0, "relay", "s1", "last"), obs(99.4, "other", "s1", "last")]
        origins = P2PTimingCorrelator.correlate_origin_ip(observations)
        self.assertEqual(origins["last"]["origin_ip"], "relay")
        self.assertGreater(origins["last"]["relay_ratio"], 0.8)
        self.assertLess(origins["last"]["confidence"], origins["t0"]["confidence"])

    def test_single_announcer_gets_low_confidence(self):
        origin = P2PTimingCorrelator.correlate_origin_ip([obs(1.0, "a", "s1")])["t1"]
        self.assertLessEqual(origin["confidence"], 0.3)


class ClusteringTests(unittest.TestCase):
    def test_common_inputs_merge_transitively(self):
        txs = [tx("1", 1, [("A", 1), ("B", 1)], [("X", 2)]),
               tx("2", 2, [("B", 1), ("C", 1)], [("Y", 2)]),
               tx("3", 3, [("D", 1)], [("Z", 1)])]
        entities = EntityClusterEngine().cluster_common_inputs(txs)
        self.assertEqual(list(entities.values()), [{"A", "B", "C"}])

    def test_coinjoin_inputs_are_not_merged(self):
        mix = tx("mix", 1, [("A", 1.1), ("B", 1.2), ("C", 1.3)],
                 [("X", 1.0), ("Y", 1.0), ("Z", 1.0), ("a", 0.1), ("b", 0.2), ("c", 0.3)])
        self.assertGreaterEqual(EntityClusterEngine.coinjoin_score(mix), 0.5)
        self.assertEqual(EntityClusterEngine().cluster_common_inputs([mix], skip_txids=["mix"]), {})

    def test_batch_payout_is_not_a_coinjoin(self):
        payout = tx("p", 1, [("A", 10)], [("X", 1.0), ("Y", 2.0), ("Z", 3.0), ("W", 3.9)])
        self.assertEqual(EntityClusterEngine.coinjoin_score(payout), 0.0)


class PeelChainTests(unittest.TestCase):
    @staticmethod
    def _chain(gap):
        txs, addr, balance = [], "start", 10.0
        for hop in range(5):
            txs.append(tx(f"h{hop}", hop * gap, [(addr, balance)], [(f"peel{hop}", 0.1), (f"chg{hop}", balance - 0.1)]))
            addr, balance = f"chg{hop}", balance - 0.1
        return txs

    def test_chain_is_traced_end_to_end(self):
        txs = self._chain(gap=30)
        graph = HeterogeneousGraphBuilder().build_from_transactions(txs)
        chains = EntityClusterEngine.detect_peeling_chains(txs, graph)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["hops"], 5)
        self.assertAlmostEqual(chains[0]["peeled_total"], 0.5)

    def test_slow_respends_are_not_a_chain(self):
        txs = self._chain(gap=6 * 3600)
        graph = HeterogeneousGraphBuilder().build_from_transactions(txs)
        self.assertEqual(EntityClusterEngine.detect_peeling_chains(txs, graph), [])

    def test_single_payment_with_change_is_not_a_chain(self):
        txs = self._chain(gap=30)[:1]
        graph = HeterogeneousGraphBuilder().build_from_transactions(txs)
        self.assertEqual(EntityClusterEngine.detect_peeling_chains(txs, graph), [])


class GraphTests(unittest.TestCase):
    def test_spend_links_follow_addresses(self):
        txs = [tx("a", 1, [("A", 2)], [("B", 1.5), ("C", 0.5)]), tx("b", 2, [("B", 1.5)], [("D", 1.5)])]
        graph = HeterogeneousGraphBuilder().build_from_transactions(txs)
        self.assertEqual(graph.preds, [[], [0]])
        self.assertEqual(graph.succs, [[1], []])
        self.assertEqual(graph.spent_by[(0, "B")], 1)
        self.assertEqual(graph.count_nodes("WALLET"), 4)


if __name__ == "__main__":
    unittest.main()
