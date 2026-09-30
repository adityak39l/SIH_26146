import json
import tempfile
import unittest
from pathlib import Path

from src.ingestion.geo_enricher import OfflineGeoEnricher
from src.ingestion.parser import BulkMetadataParser

RECORD = {
    "timestamp": 1790000000.25, "src_ip": "185.220.101.5", "src_port": 51000,
    "dst_ip": "198.51.100.11", "dst_port": 8333, "txid": "ab" * 32,
    "input_addresses": ["addr_in_1", "addr_in_2"], "output_addresses": ["addr_out_1"],
    "input_amounts": [1.5, 0.5], "output_amounts": [1.999], "fee": 0.001,
}


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, record):
        self.assertEqual(record["timestamp"], 1790000000.25)
        self.assertEqual(record["src_port"], 51000)
        self.assertEqual(record["input_addresses"], ["addr_in_1", "addr_in_2"])
        self.assertEqual(record["input_amounts"], [1.5, 0.5])
        self.assertEqual(record["fee"], 0.001)

    def test_json(self):
        path = self.dir / "a.json"
        path.write_text(json.dumps([RECORD]), encoding="utf-8")
        self._check(BulkMetadataParser.parse_file(path)[0])

    def test_jsonl(self):
        path = self.dir / "a.jsonl"
        path.write_text(json.dumps(RECORD) + "\n\n", encoding="utf-8")
        self._check(BulkMetadataParser.parse_file(path)[0])

    def test_csv_with_pipe_separated_lists(self):
        path = self.dir / "a.csv"
        header = list(RECORD)
        row = ["|".join(map(str, v)) if isinstance(v, list) else str(v) for v in RECORD.values()]
        path.write_text(",".join(header) + "\n" + ",".join(row) + "\n", encoding="utf-8")
        self._check(BulkMetadataParser.parse_file(path)[0])

    def test_xml(self):
        fields = "".join(
            f"<{k}>" + ("".join(f"<item>{i}</item>" for i in v) if isinstance(v, list) else str(v)) + f"</{k}>"
            for k, v in RECORD.items())
        path = self.dir / "a.xml"
        path.write_text(f"<records><record>{fields}</record></records>", encoding="utf-8")
        self._check(BulkMetadataParser.parse_file(path)[0])

    def test_xml_with_doctype_is_rejected(self):
        path = self.dir / "bomb.xml"
        path.write_text('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><records></records>', encoding="utf-8")
        with self.assertRaises(ValueError):
            BulkMetadataParser.parse_file(path)

    def test_unsupported_format(self):
        path = self.dir / "a.parquet"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            BulkMetadataParser.parse_file(path)

    def test_two_layer_files_are_joined_on_txid(self):
        network = {k: RECORD[k] for k in ("timestamp", "src_ip", "src_port", "dst_ip", "dst_port", "txid")}
        ledger = {k: RECORD[k] for k in ("txid", "input_addresses", "output_addresses",
                                         "input_amounts", "output_amounts", "fee")}
        (self.dir / "ledger.json").write_text(json.dumps([ledger]), encoding="utf-8")
        (self.dir / "network.jsonl").write_text(json.dumps(network) + "\n", encoding="utf-8")
        dataset = BulkMetadataParser.load_dataset(self.dir)
        self.assertEqual(len(dataset.observations), 1)
        self.assertEqual(list(dataset.transactions), [RECORD["txid"]])
        self.assertNotIn("src_ip", dataset.transactions[RECORD["txid"]])
        self.assertEqual(len(dataset.sources), 2)
        self.assertEqual(len(dataset.sources[0]["sha256"]), 64)


class GeoEnricherTests(unittest.TestCase):
    def setUp(self):
        self.geo = OfflineGeoEnricher()

    def test_tor_exit_range(self):
        info = self.geo.enrich("185.220.101.5")
        self.assertEqual(info["category"], "tor_exit")
        self.assertEqual(info["asn"], "AS205100")
        self.assertTrue(info["is_high_risk_network"])

    def test_residential_range_is_not_high_risk(self):
        info = self.geo.enrich("49.37.10.20")
        self.assertEqual((info["country"], info["category"]), ("IN", "residential"))
        self.assertFalse(info["is_high_risk_network"])

    def test_unknown_and_malformed_addresses(self):
        self.assertEqual(self.geo.enrich("8.8.8.8")["category"], "unknown")
        self.assertEqual(self.geo.enrich("not-an-ip")["country"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
