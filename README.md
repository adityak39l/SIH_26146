# VIGIL-CHAIN: AI-Powered Monitoring & Analysis of Bitcoin Transaction Traffic

> **Smart India Hackathon 2026 — Problem Statement 26146** (Blockchain & Cybersecurity, software edition; problem posed by NTRO).
> **Live console:** https://adityak39l.github.io/SIH_26146/
>
> This is a student prototype. It is not an official system of any agency, and every transaction in this repository is synthetic.

---

## 1. The problem

Two groups of tools each see half of a Bitcoin transaction:

| Layer | Sees | Cannot see |
|---|---|---|
| **Network** (P2P capture) | IP, port, timestamp of each announcement | which wallets and amounts are involved |
| **Blockchain** (ledger) | wallets, amounts, transaction graph | which machine sent it |

The task is an **offline Linux system** that ingests bulk metadata (CSV/JSON/XML), joins the two layers, applies **real ML rather than fixed rules**, and produces **explainable investigative leads**.

## 2. What the system does

```
 network_observations.csv ─┐
                           ├─► join on TXID ─► first-seen origin + calibrated confidence ─┐
 blockchain_transactions ──┘                                                              │
        │                                                                                 ▼
        └─► flow graph ─► entity clusters, peel chains, mixing ─► Isolation Forest ─► risk fusion ─► cases
                                                                  GraphSAGE (GNN) ──┘   (exact Shapley)
```

1. **Ingest** — CSV, JSON, JSON Lines and XML. The two layers arrive as separate files and are joined on the transaction ID. Every input file is hashed (SHA-256).
2. **Attribute the origin** — the peer that announces a transaction first is its most likely origin. Three signals (lead time over the next announcer, agreement between sensors, how often that IP merely relays) give a **calibrated confidence**. Below 0.5 the origin is reported as *unresolved* instead of naming a relay.
3. **Enrich offline** — country, ASN and network type (Tor exit / VPN / hosting / residential / exchange) from a bundled CIDR table, or MaxMind `.mmdb` files if present. No network calls anywhere.
4. **Resolve entities** — common-input ownership clustering (union-find), skipped inside CoinJoin rounds where it would wrongly merge strangers. Multi-hop peeling chains, equal-output mixing and fan-out/fan-in are traced on the money-flow graph.
5. **Score** — three models:
   - **Isolation Forest** — unsupervised outlier score.
   - **GraphSAGE** — a 2-layer graph neural network that reads each transaction with the transactions that fund it and spend it, kept in separate directions.
   - **Risk fusion** — logistic regression over the GNN, the Isolation Forest and the network-layer evidence.
6. **Explain** — the fusion model is linear, so each signal's **Shapley value is exact** (`w·(x − E[x])`), with no sampling. Every case shows what raised the score, what lowered it, what the GNN reacted to, where the money went, and a SHA-256 of the record.
7. **Group into cases** — flagged transactions linked by money flow become one case, because an investigator works an operation, not a list of transactions.

All three models are implemented directly on **NumPy** ([src/ml/](src/ml/)): no scikit-learn, PyTorch or SHAP package is needed, which keeps an air-gapped install to a handful of wheels and makes every line auditable. The GNN's hand-written backpropagation is checked against numerical gradients in the tests.

## 3. Results on the demo capture

The demo capture ([data/raw/demo/](data/raw/demo/)) has 633 transactions and 4,528 network observations; 99 transactions belong to simulated laundering operations. It was used for neither training nor tuning. Reproduce with `python -m src.pipeline.evaluate`.

| Detector | Precision | Recall | F1 |
|---|---|---|---|
| Single-transaction peel rule (the first prototype) | 0.291 | 0.646 | 0.401 |
| Isolation Forest alone | 0.121 | 0.121 | 0.121 |
| GraphSAGE alone (blockchain layer only) | 0.714 | 0.859 | 0.780 |
| **Fused risk score (both layers)** | **0.809** | **0.939** | **0.869** |

- **Why fusion beats the GNN:** the simulation includes exchange hot-wallet withdrawals, which on-chain are indistinguishable from a laundering peel chain. Only the network layer separates them. That is the point of joining the two layers.
- **Origin attribution:** the first-seen IP is the true origin for 89.3% of transactions. At confidence ≥ 0.75 it is right 98.8% of the time; below 0.5 it is right 8.5% of the time, which is why those are reported as unresolved.
- **Operations recovered:** 8 of the 9 simulated operations land entirely in one case; the ninth is split (9 of 14 transactions in its main case).
- The Isolation Forest is weak alone: laundering here is structured, not statistically extreme. It is kept as one signal among several.

**Read these numbers correctly.** Training and test data come from the same simulator ([src/simulation/generator.py](src/simulation/generator.py)), with different seeds. They show the pipeline works end to end and that each stage adds something; they do not predict accuracy on real traffic.

### On real Bitcoin data (Elliptic)

The blockchain-layer models were also run on the Elliptic dataset: 203,769 real Bitcoin transactions and 234,355 payment links, of which 4,545 are labelled illicit and 42,019 licit. Labels from time steps 1-25 are used for fitting, 30-34 for choosing the epoch and threshold, and 35-49 (graphs never seen in training) for testing. Reproduce with `python -m src.pipeline.elliptic` (downloads about 150 MB, needs pandas, takes about 10 minutes).

| Detector (illicit class, 1,083 illicit of 16,670 test transactions) | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|
| Logistic regression, features only | 0.199 | 0.803 | 0.319 | 0.873 |
| Neural network without the graph | 0.258 | 0.495 | 0.339 | 0.830 |
| **GraphSAGE** | **0.349** | **0.440** | **0.389** | **0.875** |
| Isolation Forest (unsupervised) | 0.000 | 0.000 | 0.000 | 0.169 |

What this shows, plainly:

- **The graph helps on real data too:** +0.05 F1 and +0.045 ROC-AUC over the identical network with the edges removed.
- **The absolute score is modest.** Weber et al. (2019) report about 0.63 F1 for a GCN and about 0.79 for a random forest on this split. Our small NumPy GraphSAGE ranks transactions reasonably (ROC-AUC 0.875) but loses precision as laundering patterns drift between the training and test periods. Closing that gap (tree ensembles, temporal models) is the first roadmap item.
- **Anomaly detection alone fails on real data** (ROC-AUC 0.169, worse than chance): real illicit transactions sit inside the normal range, which is why the supervised graph model is needed.
- Elliptic has no IP-level data, so origin attribution and the fused two-layer score cannot be tested on it; those results remain simulation-only.

## 4. Quick start (offline)

```bash
pip install -r requirements.txt        # numpy, fastapi, uvicorn

python -m src.pipeline.engine          # run the pipeline, print ranked cases, write output/leads.json
python -m src.pipeline.evaluate        # metrics against ground truth
python -m src.pipeline.export          # build docs/index.html (standalone console, opens from disk)
python -m uvicorn src.api.main:app     # console + REST API at http://127.0.0.1:8000
python -m unittest discover -s tests -t .
```

Or one click: `./run_offline.sh` (Linux) / `run_offline.bat` (Windows).

To analyse your own capture, pass a file or a folder: `python -m src.pipeline.engine path/to/folder`.

| Command | Purpose |
|---|---|
| `python -m src.simulation.generator --seed 7` | regenerate the demo capture |
| `python -m src.pipeline.train` | retrain the models (about 20 s on a laptop CPU) |

REST endpoints: `/` (console), `/api/summary`, `/api/cases`, `/api/cases/{id}`, `/api/leads`, `/api/status`, `POST /api/refresh`.

### Input format

**Network layer** (`.csv`): `timestamp, src_ip, src_port, dst_ip, dst_port, txid` — one row per announcement seen by a sensor (`dst_ip`).
**Blockchain layer** (`.json`): `txid, input_addresses, output_addresses, input_amounts, output_amounts, fee, script_type`.
A single file carrying both sets of fields per record also works ([data/raw/sample_transactions.json](data/raw/sample_transactions.json)). In CSV, list fields are `|`-separated.

## 5. Repository layout

```text
config/settings.py          paths and thresholds
data/raw/demo/              synthetic two-layer demo capture
data/eval/                  ground truth for the demo capture (never read by the pipeline)
data/geoip/                 offline CIDR table; drop GeoLite2 .mmdb files here to use them
data/models/                trained model bundle (.npz)
src/ingestion/              parsers (CSV/JSON/JSONL/XML), offline geo/ASN enrichment
src/correlation/            first-seen origin estimator, entity clustering, chain tracing
src/graph/                  heterogeneous graph + transaction flow graph
src/ml/                     Isolation Forest, GraphSAGE, risk fusion, Shapley explanations
src/simulation/             synthetic traffic generator
src/pipeline/               engine, training, evaluation, case building, console export
src/dashboard/              analyst console template (single file, no external assets)
src/api/                    FastAPI server
docs/index.html             prebuilt console for static hosting
tests/                      unit and end-to-end tests
```

## 6. Limits

- **Simulated two-layer data.** No public dataset joins P2P announcements to labelled transactions, so the network layer and the fused score are tested on simulated traffic only. The blockchain layer is also tested on real data (Elliptic), where it is weaker than published baselines.
- **First-seen attribution is an estimate.** It needs sensors connected to a large share of the network, and Bitcoin Core deliberately randomises announcement timing. It cannot see through Tor or a VPN: it reports the exit, not the sender.
- **A flag is not a finding.** CoinJoin is also used lawfully, and exchanges legitimately produce peel-chain shapes. Each output is a lead that must be corroborated; whether it is admissible as evidence is for a court to decide, not the software.
- **Address-level linking.** The metadata carries addresses, not outpoints, so a spend is linked to the most recent earlier payment to that address.
- **Scale.** The demo runs in under a second; the code is single-process and in-memory. Bulk captures in the tens of millions of rows need a columnar store and sparse batching.
- **Offline table.** The bundled CIDR table is a small seed for the demo; it should be replaced by GeoLite2 plus a Tor exit-list snapshot taken before each air-gapped deployment.

## 7. Roadmap

1. Close the gap to published Elliptic results: gradient-boosted trees on node features plus GNN embeddings, and training that is robust to drift over time.
2. Replace first-seen with a diffusion-model estimator (rumour centrality) that uses the full announcement order per sensor.
3. Add change-address heuristics and cross-capture entity memory, so clusters persist between runs.
4. Temporal GNN over a sliding window for streaming captures; DuckDB/Parquet ingestion for bulk scale.
5. Signed dossiers (detached signature over the record hash) and an append-only audit log for chain of custody.
6. An analyst feedback loop: confirmed and dismissed cases become training labels.
