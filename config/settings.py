from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
DEMO_DATA_DIR = RAW_DATA_DIR / "demo"
EVAL_DIR = DATA_DIR / "eval"
GEOIP_DIR = DATA_DIR / "geoip"
MODELS_DIR = DATA_DIR / "models"
OUTPUT_DIR = BASE_DIR / "output"
DOCS_DIR = BASE_DIR / "docs"

# GeoIP Databases (Offline MaxMind files, optional)
GEOIP_CITY_DB = GEOIP_DIR / "GeoLite2-City.mmdb"
GEOIP_ASN_DB = GEOIP_DIR / "GeoLite2-ASN.mmdb"
# Bundled CIDR table used when the .mmdb files are absent, and always for the
# network category (Tor exit / VPN / hosting), which MaxMind does not carry.
OFFLINE_NETWORK_TABLE = GEOIP_DIR / "offline_networks.csv"

# Trained model bundle (GraphSAGE weights + risk-fusion weights)
MODEL_FILE = MODELS_DIR / "vigil_chain_v1.npz"
DEMO_GROUND_TRUTH = EVAL_DIR / "demo_ground_truth.json"
# Written by `python -m src.pipeline.elliptic`; shown in the console when present.
ELLIPTIC_RESULTS = EVAL_DIR / "elliptic_results.json"

PIPELINE_VERSION = "2.0.0"

# Risk Engine Thresholds (0 - 100 scale)
CRITICAL_RISK_THRESHOLD = 85.0
HIGH_RISK_THRESHOLD = 65.0
MEDIUM_RISK_THRESHOLD = 40.0

# Typical P2P gossip propagation delay (milliseconds). A first-seen lead much
# larger than this is strong evidence that the first announcer is the origin.
CORRELATION_WINDOW_MS = 250

# Below this confidence a first-seen attribution is reported as unresolved and its
# network is not used as evidence: the announcer is more likely a relay than the origin.
ORIGIN_MIN_CONFIDENCE = 0.5

# Peeling chain detection
PEEL_MIN_HOPS = 3
PEEL_MAX_GAP_S = 1800.0
PEEL_MAX_RATIO = 0.25

# Equal-output mixing (CoinJoin) detection
COINJOIN_MIN_INPUTS = 3
COINJOIN_MIN_EQUAL_OUTPUTS = 3

# Window used to count transactions announced by the same origin IP
ORIGIN_BURST_WINDOW_S = 600.0
