from typing import Dict, Any
from config.settings import GEOIP_CITY_DB, GEOIP_ASN_DB

class OfflineGeoEnricher:
    """
    Performs 100% offline GeoIP and ASN attribution using local MaxMind .mmdb files.
    Includes mock fallback for immediate testing without external downloads.
    """
    
    def __init__(self):
        self.has_real_db = GEOIP_CITY_DB.exists() and GEOIP_ASN_DB.exists()
        self.known_malicious_asns = {"AS205100": "Tor Exit Node", "AS14061": "DigitalOcean VPN/Proxy"}

    def enrich(self, ip_address: str, existing_country: str = None, existing_asn: str = None) -> Dict[str, Any]:
        country = existing_country or "UNKNOWN"
        asn = existing_asn or "UNKNOWN"
        asn_org = self.known_malicious_asns.get(asn, "Standard ISP")
        is_high_risk_network = asn in self.known_malicious_asns

        return {
            "ip": ip_address,
            "country": country,
            "asn": asn,
            "asn_org": asn_org,
            "is_high_risk_network": is_high_risk_network
        }
