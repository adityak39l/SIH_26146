import csv
import ipaddress
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import GEOIP_ASN_DB, GEOIP_CITY_DB, OFFLINE_NETWORK_TABLE

try:
    import maxminddb
    HAS_MAXMINDDB = True
except ImportError:
    HAS_MAXMINDDB = False

HIGH_RISK_CATEGORIES = ("tor_exit", "vpn")

CATEGORY_LABELS = {
    "tor_exit": "Tor exit relay",
    "vpn": "Commercial VPN",
    "hosting": "Datacentre / hosting",
    "residential": "Residential ISP",
    "mobile": "Mobile carrier",
    "exchange": "Exchange infrastructure",
    "sensor": "Monitoring sensor",
    "unknown": "Unclassified network",
}


class OfflineGeoEnricher:
    """
    Performs 100% offline GeoIP and ASN attribution.

    Country/ASN come from local MaxMind .mmdb files when they are present (and the
    `maxminddb` package is installed); otherwise from the bundled CIDR table. The network
    category (Tor exit, VPN, hosting, ...) always comes from the CIDR table, which should
    be refreshed from a Tor exit-list snapshot before each air-gapped deployment.
    """

    def __init__(self, table_path: Path = OFFLINE_NETWORK_TABLE):
        # prefix length -> {network address as int -> row}; longest prefix wins.
        self._prefixes: Dict[int, Dict[int, Dict[str, str]]] = {}
        self._asn_category: Dict[str, str] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}
        if Path(table_path).exists():
            with open(table_path, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    network = ipaddress.ip_network(row["cidr"].strip())
                    key = (network.version, network.prefixlen)
                    self._prefixes.setdefault(key, {})[int(network.network_address)] = row
                    self._asn_category.setdefault(row["asn"], row["category"])
        self._order = sorted(self._prefixes, key=lambda k: k[1], reverse=True)

        self._city_reader = self._asn_reader = None
        self.has_real_db = HAS_MAXMINDDB and GEOIP_CITY_DB.exists() and GEOIP_ASN_DB.exists()
        if self.has_real_db:
            self._city_reader = maxminddb.open_database(str(GEOIP_CITY_DB))
            self._asn_reader = maxminddb.open_database(str(GEOIP_ASN_DB))

    def _table_lookup(self, ip_address: str) -> Optional[Dict[str, str]]:
        try:
            ip = ipaddress.ip_address(ip_address)
        except ValueError:
            return None
        value = int(ip)
        for version, prefixlen in self._order:
            if version != ip.version:
                continue
            shift = ip.max_prefixlen - prefixlen
            row = self._prefixes[(version, prefixlen)].get((value >> shift) << shift)
            if row:
                return row
        return None

    def enrich(self, ip_address: str, existing_country: str = None, existing_asn: str = None) -> Dict[str, Any]:
        cache_key = f"{ip_address}|{existing_country}|{existing_asn}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        row = self._table_lookup(ip_address) or {}
        country = existing_country or row.get("country") or "UNKNOWN"
        asn = existing_asn or row.get("asn") or "UNKNOWN"
        asn_org = row.get("org") or "Unknown network"
        source = "offline CIDR table" if row else "unresolved"

        if self.has_real_db:
            city = self._city_reader.get(ip_address) or {}
            asn_record = self._asn_reader.get(ip_address) or {}
            if city.get("country", {}).get("iso_code"):
                country = city["country"]["iso_code"]
                source = "MaxMind GeoLite2"
            if asn_record.get("autonomous_system_number"):
                asn = f"AS{asn_record['autonomous_system_number']}"
                asn_org = asn_record.get("autonomous_system_organization", asn_org)

        category = row.get("category") or self._asn_category.get(asn, "unknown")
        result = {
            "ip": ip_address,
            "country": country,
            "asn": asn,
            "asn_org": asn_org,
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "is_high_risk_network": category in HIGH_RISK_CATEGORIES,
            "source": source,
        }
        self._cache[cache_key] = result
        return result
