import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Union

LIST_FIELDS = ("input_addresses", "output_addresses", "input_amounts", "output_amounts")
AMOUNT_FIELDS = ("input_amounts", "output_amounts")
NETWORK_FIELDS = ("timestamp", "src_ip", "src_port", "dst_ip", "dst_port", "txid")
SUPPORTED_SUFFIXES = (".json", ".jsonl", ".ndjson", ".csv", ".xml")


@dataclass
class Dataset:
    """Network-layer observations and blockchain-layer transactions, joined on TXID."""

    observations: List[Dict[str, Any]] = field(default_factory=list)
    transactions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sources: List[Dict[str, Any]] = field(default_factory=list)


class BulkMetadataParser:
    """
    Parser for bulk Bitcoin P2P and blockchain transaction metadata.
    Supports CSV, JSON, JSON Lines and XML files completely offline.

    A record may carry network-layer fields (src_ip, timestamp, ...), blockchain-layer
    fields (input_addresses, amounts, ...) or both. `load_dataset` splits them into the
    two layers so that they can be correlated on TXID.
    """

    @staticmethod
    def parse_json(file_path: Path) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("records") or data.get("transactions") or [data]
        return data

    @staticmethod
    def parse_jsonl(file_path: Path) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    @staticmethod
    def parse_csv(file_path: Path) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]

    @staticmethod
    def parse_xml(file_path: Path) -> List[Dict[str, Any]]:
        """
        Expects <root><record><field>value</field>...</record>...</root>. A field with
        child elements is read as a list. Files declaring a DOCTYPE are rejected: the
        standard-library parser expands entities, and seized or third-party files must
        not be able to exhaust memory that way.
        """
        _reject_doctype(file_path)
        records = []
        for _, elem in ET.iterparse(file_path, events=("end",)):
            if elem.tag not in ("record", "transaction", "observation"):
                continue
            record = {}
            for child in elem:
                if len(child):
                    record[child.tag] = [(item.text or "").strip() for item in child]
                else:
                    record[child.tag] = (child.text or "").strip()
            records.append(record)
            elem.clear()
        return records

    @staticmethod
    def parse_file(file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Dataset file not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix == ".json":
            records = BulkMetadataParser.parse_json(path)
        elif suffix in (".jsonl", ".ndjson"):
            records = BulkMetadataParser.parse_jsonl(path)
        elif suffix == ".csv":
            records = BulkMetadataParser.parse_csv(path)
        elif suffix == ".xml":
            records = BulkMetadataParser.parse_xml(path)
        else:
            raise ValueError(f"Unsupported format: {path.suffix}")
        return [normalize_record(r) for r in records]

    @staticmethod
    def load_dataset(source: Union[str, Path, Iterable[Union[str, Path]]]) -> Dataset:
        """Loads one file, several files, or every supported file in a directory."""
        dataset = Dataset()
        for path in _expand_sources(source):
            records = BulkMetadataParser.parse_file(path)
            for record in records:
                txid = record.get("txid")
                if not txid:
                    continue
                if record.get("src_ip") and record.get("timestamp") is not None:
                    dataset.observations.append({k: record[k] for k in NETWORK_FIELDS if k in record})
                if record.get("input_addresses") or record.get("output_addresses"):
                    tx = dataset.transactions.setdefault(txid, {})
                    for key, value in record.items():
                        if key not in ("src_ip", "src_port", "dst_ip", "dst_port", "timestamp"):
                            tx.setdefault(key, value)
                    # Geo fields supplied with the capture describe the announcing peer
                    # of that one record, not the transaction.
                    tx.pop("geo_country", None)
                    tx.pop("asn", None)
            dataset.sources.append({
                "file": path.name,
                "sha256": sha256_file(path),
                "records": len(records),
            })
        return dataset


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Coerces the string values produced by CSV/XML into the types the JSON form uses."""
    out = dict(record)
    for key in LIST_FIELDS:
        if key in out:
            out[key] = _as_list(out[key])
            if key in AMOUNT_FIELDS:
                out[key] = [float(v) for v in out[key]]
    if out.get("timestamp") not in (None, ""):
        out["timestamp"] = float(out["timestamp"])
    elif "timestamp" in out:
        del out["timestamp"]
    for key in ("src_port", "dst_port"):
        if out.get(key) not in (None, ""):
            out[key] = int(float(out[key]))
    if out.get("fee") not in (None, ""):
        out["fee"] = float(out["fee"])
    return out


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    separator = "|" if "|" in text else (";" if ";" in text else None)
    return [part.strip() for part in text.split(separator)] if separator else [text]


def _expand_sources(source: Union[str, Path, Iterable[Union[str, Path]]]) -> List[Path]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_dir():
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
            if not files:
                raise FileNotFoundError(f"No CSV/JSON/XML files found in: {path}")
            return files
        if not path.exists():
            raise FileNotFoundError(f"Dataset file not found: {path}")
        return [path]
    return [Path(p) for p in source]


def _reject_doctype(path: Path) -> None:
    tail = b""
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            window = (tail + chunk).upper()
            if b"<!DOCTYPE" in window or b"<!ENTITY" in window:
                raise ValueError(f"XML with DOCTYPE/ENTITY declarations is not accepted: {path.name}")
            tail = chunk[-16:]
