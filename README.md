# VIGIL-CHAIN: AI-Powered Monitoring & Analysis of Bitcoin Transaction Traffic

[![Smart India Hackathon 2026](https://img.shields.io/badge/SIH-2026-blue.svg)](https://sih.gov.in)
[![Challenge ID](https://img.shields.io/badge/Challenge-SIH26146-emerald.svg)](https://sih.gov.in/sih2026PS)
[![Sponsoring Agency](https://img.shields.io/badge/Sponsor-NTRO-red.svg)](https://ntro.gov.in)
[![Platform](https://img.shields.io/badge/Platform-100%25%20Offline%20Linux-black.svg)](#)

> **Official Solution for Smart India Hackathon 2026 — Challenge #146**  
> **Sponsoring Agency:** National Technical Research Organisation (NTRO), Prime Minister's Office (PMO) / NSA, Govt. of India.  
> **Domain:** Blockchain & Cybersecurity (Software Edition)

---

## 1. Problem Overview
Bitcoin's pseudonymous, peer-to-peer (P2P) architecture enables criminal syndicates, ransomware cartels, and money launderers to obscure asset trails. 

Current signals intelligence faces a **Dual-Layer Blindspot**:
* **Network Layer:** Observes physical IPs, ports, and timestamps, but cannot attribute transaction hashes or wallet ownership.
* **Blockchain Layer:** Observes UTXOs, amounts, and wallet addresses, but cannot pinpoint physical origin nodes.

**NTRO Objective:** Build a **complete offline Linux system** that ingests bulk metadata (CSV/JSON/XML), correlates **network-layer observations (IP/port/timing)** with **blockchain-layer data (wallet/TXID/amount)**, and applies **real AI/ML models** (not just rules) to detect anomalies, cluster entities, and generate **explainable investigative leads**.

---

## 2. System Architecture

```
+-------------------------------------------------------------------------------+
|                        OFFLINE INGESTION & ENRICHMENT                         |
|   Bulk CSV/JSON/XML Metadata  -->  Columnar Parser  -->  MaxMind GeoIP2/ASN   |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                     CORRELATION & GRAPH RESOLUTION ENGINE                     |
|   * Earliest P2P Diffusion Correlator    * Common-Input Ownership Clustering  |
|   * Multi-hop Peeling Chain Detector     * Heterogeneous Directed Graph       |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                        DUAL-STAGE AI/ML ANALYTICS ENGINE                      |
|   Stage 1: Isolation Forest (Anomaly)  |  Stage 2: Graph Neural Networks (GNN)|
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                      EXPLAINABLE AI (XAI) & DOSSIER TRIAGE                    |
|   SHAP Feature Attributions  -->  Automated Court-Admissible Dossier Export   |
+-------------------------------------------------------------------------------+
```

---

## 3. Directory Structure

```text
sih26146-vigil-chain/
│
├── config/             # Settings, paths, and risk thresholds
├── data/
│   ├── raw/            # Bulk input transaction files (CSV/JSON/XML)
│   ├── geoip/          # Offline MaxMind GeoLite2 databases (.mmdb)
│   └── models/         # Pre-trained model weights
├── src/
│   ├── ingestion/      # Streaming parser & offline GeoIP enrichment
│   ├── correlation/    # P2P timing correlator & entity clustering
│   ├── graph/          # Heterogeneous networkx graph constructor
│   ├── ml/             # Anomaly detector (Isolation Forest) & GNN
│   ├── pipeline/       # End-to-end intelligence execution engine
│   └── api/            # FastAPI offline REST endpoints
├── tests/              # Test suites
├── Dockerfile          # Air-gapped Linux container configuration
├── run_offline.sh      # Linux one-click execution script
├── run_offline.bat     # Windows one-click execution script
└── requirements.txt    # Pinned dependencies
```

---

## 4. Quick Start (100% Offline Execution)

### On Linux:
```bash
chmod +x run_offline.sh
./run_offline.sh
```

### On Windows:
```cmd
run_offline.bat
```

### Running Manually:
```bash
pip install -r requirements.txt
python -m src.pipeline.engine
uvicorn src.api.main:app --reload
```

---

## 5. Key Innovations for NTRO Judges
1. **100% Air-Gapped / Offline Guarantee:** Zero external network calls; everything runs locally in-memory.
2. **Diffusion Tree Reversal:** Reconstructs the earliest P2P gossip broadcast to statistically attribute the origin IP.
3. **Court-Admissible XAI:** Integrates SHAP attributions so law enforcement officers understand exactly why a transaction was flagged.
