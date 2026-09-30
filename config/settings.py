import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
GEOIP_DIR = DATA_DIR / "geoip"
MODELS_DIR = DATA_DIR / "models"

# GeoIP Databases (Offline MaxMind files)
GEOIP_CITY_DB = GEOIP_DIR / "GeoLite2-City.mmdb"
GEOIP_ASN_DB = GEOIP_DIR / "GeoLite2-ASN.mmdb"

# Risk Engine Thresholds (0 - 100 scale)
HIGH_RISK_THRESHOLD = 75.0
MEDIUM_RISK_THRESHOLD = 45.0

# Correlation Time Window (in milliseconds for P2P gossip propagation)
CORRELATION_WINDOW_MS = 250
