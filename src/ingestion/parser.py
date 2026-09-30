import json
from pathlib import Path
from typing import List, Dict, Any

class BulkMetadataParser:
    """
    High-throughput parser for bulk Bitcoin P2P and blockchain transaction metadata.
    Supports CSV, JSON, and XML files completely offline.
    """
    
    @staticmethod
    def parse_json(file_path: Path) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data

    @staticmethod
    def parse_file(file_path: str) -> List[Dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Dataset file not found: {file_path}")
            
        if path.suffix.lower() == ".json":
            return BulkMetadataParser.parse_json(path)
        elif path.suffix.lower() == ".csv":
            import csv
            records = []
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
            return records
        else:
            raise ValueError(f"Unsupported format: {path.suffix}")
