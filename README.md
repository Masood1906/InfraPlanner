# Infra Planner

An AI-powered Kubernetes infrastructure planning system for virtualized network routers. Submit a router's hardware specifications and receive a concrete, graph-reasoned Kubernetes deployment plan — including cluster topology, node profiles, HA configuration, and a confidence score.

---

## How It Works

The system follows a multi-stage pipeline:

```
Router Spec (JSON)
      │
      ▼
┌─────────────┐
│   Parser    │  Validates fields, normalizes units, resolves aliases
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  Rule Validator │  Hard floors/ceilings, model name checks, ratio checks
└──────┬──────────┘
       │
       ▼
┌──────────────────┐
│ Agentic Validator│  LLM identity + spec consistency check (unknown routers only)
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  Entity Mapper   │  Matches router to FalkorDB knowledge graph via cosine similarity
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  Data Quality    │  Scores input quality (0.0–1.0); skips inference if < 0.40
│     Gate         │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Graph Traversal  │  RouterModel → RouterFeature → OperationalImplication
│  (FalkorDB)      │             → InfraRequirement → NodeProfile → DeploymentPattern
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Inference Engine │  Scales resource targets using log-compressed demand formula
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│   Constraint     │  Validates node counts, caps per-role maximums
│   Validator      │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Deployment       │  Builds clusters, matches DeploymentPattern from graph
│   Planner        │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Confidence Score │  5-signal weighted score (signal, graph match, constraints,
│  + Explainer     │  profile fit, feature coverage)
└──────────────────┘
```

---

## Project Structure

```
K8S/
├── main.py                    # Entry point: CLI smoke-test or FastAPI server
├── api/
│   ├── app.py                 # FastAPI application factory + CORS
│   ├── routes.py              # HTTP route handlers
│   ├── schemas.py             # Pydantic request/response models
│   ├── auth.py                # API key verification
│   └── dependencies.py        # FastAPI lifespan + graph dependency injection
├── parser/
│   ├── input_parser.py        # Raw dict → ParsedSpec, unit normalization
│   ├── normalizer.py          # Unit conversion + range validation
│   ├── validator.py           # Rule-based physical plausibility checks
│   ├── agentic_validator.py   # LLM-based identity + spec consistency (Layer 1.5)
│   └── entity_mapper.py       # Cosine similarity match to graph RouterModel nodes
├── engine/
│   ├── inference.py           # Demand-scaled resource target computation
│   ├── constraint_validator.py# Per-role node count caps and violation detection
│   ├── deployment_planner.py  # Cluster builder + graph-driven topology matching
│   ├── confidence.py          # 5-signal confidence score computation
│   └── explainer.py           # LLM-generated plain-English plan explanation
├── graph/
│   ├── schema.py              # Node labels, relationship types, index statements
│   ├── seed.py                # Seeds the knowledge graph from router_registry.json
│   ├── router_registry.py     # Registry loader
│   ├── router_registry.json   # Known router specs (source of truth for seeding)
│   ├── queries.py             # All FalkorDB Cypher query functions
│   └── weight_engine.py       # Log-normalized edge weight computation
├── frontend/                  # React + Vite frontend
│   └── src/
│       ├── components/        # UI panels: RouterForm, GraphViewer, ConfidencePanel, etc.
│       └── utils/             # API client, constants
├── tests/                     # pytest test suite
├── docker-compose.yml         # FalkorDB + API services
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Graph Ontology

The knowledge graph (FalkorDB) models the relationship between router hardware and Kubernetes infrastructure:

```
RouterModel
    │ HAS_FEATURE
    ▼
RouterFeature  ──[IMPLIES weight]──▶  OperationalImplication
                                              │ REQUIRES priority
                                              ▼
                                       InfraRequirement
                                              │ SATISFIED_BY fit_score
                                              ▼
                                          NodeProfile  ──[FITS_PATTERN]──▶  DeploymentPattern
```

| Node Type | Description |
|---|---|
| `RouterModel` | A known router (e.g. `cisco_9300x`) |
| `RouterFeature` | A hardware metric (e.g. Switching Capacity = 640 Gbps) |
| `OperationalImplication` | What the feature implies operationally (e.g. `oi_high_pkt`) |
| `InfraRequirement` | A Kubernetes resource requirement (e.g. CPU ≥ 32 vCPU) |
| `NodeProfile` | A concrete K8s node spec (vCPU, RAM, ports, storage, role) |
| `DeploymentPattern` | A topology template (e.g. `high_performance`, `compute_heavy`) |

---

## Inference Engine

Resource demand is computed using a **log-compressed super-linear formula**:

```
demand_target = seed_min × (1 + signal × ln(1 + signal))
```

Where `signal` is the sum of implication weights × influence coefficients for each resource type. This formula prevents over-provisioning small routers while correctly scaling up for high-end SP/WAN devices.

**Implication → Resource Influence Map:**

| Implication | cpu | memory | networking | ports | routing | storage |
|---|---|---|---|---|---|---|
| `oi_high_pkt` | 3.0 | — | — | — | — | 0.5 |
| `oi_high_net` | — | — | 2.0 | 1.5 | — | — |
| `oi_high_route` | — | 1.5 | — | — | 3.0 | — |
| `oi_high_mem` | — | 2.5 | — | — | — | — |
| `oi_port_dense` | — | — | — | 2.0 | — | — |

---

## Confidence Score

Each plan is scored 0.0–1.0 from five weighted signals:

| Signal | Weight | Description |
|---|---|---|
| `signal_strength` | 0.20 | Average implication weight across resource targets |
| `graph_match` | 0.25 | 1.0 = exact known router; cosine score for unknown |
| `constraint_clean` | 0.25 | Penalizes range warnings (−0.20), cap warnings (−0.15), violations (−0.20) |
| `profile_fit` | 0.20 | Average fit score of selected NodeProfiles |
| `feature_coverage` | 0.10 | Fraction of submitted features recognized by the inference engine |

**Labels:** `HIGH` (≥0.85) · `MEDIUM` (≥0.65) · `LOW` (≥0.40) · `VERY LOW` (<0.40)

Plans scoring below 0.40 are rejected at the API layer.

---

## Validation Layers

The pipeline applies four sequential validation layers before inference:

**Layer 1 — Rule-based (`parser/validator.py`)**
- Model name length and format checks
- Rejects vendor-only names (e.g. `"cisco"` alone)
- Rejects non-networking brands (consumer electronics, automotive, etc.)
- Hard physical floors and ceilings per feature
- DRAM vs. IPv4 route table consistency (e.g. >500K routes requires ≥8 GB DRAM)
- Forwarding rate / switching capacity ratio (must be 0.3–2.0 Mpps/Gbps)

**Layer 1.5 — Agentic (`parser/agentic_validator.py`)**
- Fires only for unknown/low-similarity routers (similarity < 0.30)
- LLM (GPT-4o-mini) checks: is this a real enterprise router? Are the specs consistent with the claimed model?
- Rejects on high/medium confidence negative verdict; passes on low confidence (benefit of the doubt)
- Any LLM failure passes silently — the data quality gate is the safety net

**Layer 2 — Data Quality Gate (`main.py`)**
- Computes a pre-inference quality score from similarity + feature range coverage
- Skips inference entirely and returns `plan_status: "needs_review"` if score < 0.40

**Layer 3 — Confidence Gate (`api/routes.py`)**
- Rejects the HTTP response if the final confidence score < 0.40

---

## API Endpoints

Base path: `/api/v1`

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/plan` | None | Generate a deployment plan (read-only graph) |
| `POST` | `/admin/routers` | API Key | Persist a new router to the graph + generate plan |
| `GET` | `/health` | None | Liveness check + graph node count |
| `GET` | `/graph/routers` | None | List all RouterModel nodes |
| `GET` | `/graph/router/{id}/chain` | None | Full reasoning chain for a router |
| `GET` | `/graph/nodes` | None | All graph nodes (for Relationship Explorer) |
| `GET` | `/graph/path` | None | Shortest path between two nodes |
| `GET` | `/graph/data` | None | Full graph nodes + edges for visualization |
| `POST` | `/graph/explain` | API Key | LLM explanation of a graph path |

### POST /plan — Request Body

```json
{
  "model": "Cisco 9300X",
  "vendor": "Cisco",
  "series": "9300",
  "switching_cap":   { "value": 640,   "unit": "Gbps"  },
  "forwarding_rate": { "value": 2232,  "unit": "Mpps"  },
  "ipv4_routes":     { "value": 32000, "unit": "count" },
  "dram_gb":         { "value": 8,     "unit": "GB"    },
  "stacking_bw":     { "value": 1,     "unit": "TBps"  },
  "vlan_ids":        { "value": 1200,  "unit": "count" },
  "mac_addresses":   { "value": 16000, "unit": "count" }
}
```

Required fields: `model`, `switching_cap`, `forwarding_rate`, `ipv4_routes`, `dram_gb`.

### Response

```json
{
  "router_id": "cisco_9300x",
  "router_name": "Cisco 9300X",
  "plan_status": "ok",
  "valid": true,
  "cluster_count": 1,
  "topology_type": "high_performance",
  "ha_enabled": true,
  "clusters": [...],
  "confidence": {
    "score": 0.87,
    "label": "HIGH",
    "signal_strength": 0.91,
    "graph_match": 1.0,
    "constraint_clean": 1.0,
    "profile_fit": 0.95,
    "feature_coverage": 0.86,
    "breakdown": [...]
  },
  "similarity_score": 1.0,
  "data_quality_score": 1.0,
  "explanation": "...",
  "simple_explanation": "...",
  "warnings": [],
  "violations": [],
  "reasoning": [...]
}
```

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for the frontend)
- Python 3.11+ (for local development)

### 1. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
FALKOR_HOST=localhost
FALKOR_PORT=6379
GRAPH_NAME=infra_planner
API_PORT=8000
API_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
LLM_EXPLANATION_ENABLED=true
ALLOWED_ORIGINS=http://localhost:5173
```

### 2. Start the Backend

```bash
docker compose up --build
```

This starts:
- `infra_falkordb` — FalkorDB graph database on port 6379 (browser UI on port 3000)
- `infra_planner_api` — FastAPI server on port 8000

The API automatically seeds the knowledge graph with known routers from `graph/router_registry.json` on startup.

### 3. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

### 4. Verify

```bash
curl http://localhost:8000/api/v1/health
```

---

## Local Development (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Start FalkorDB separately (requires Docker)
docker run -p 6379:6379 falkordb/falkordb:latest

# Run CLI smoke-test (seeds graph + runs example pipeline)
python main.py

# Start API server
python main.py --serve
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Test files in `tests/`:

| File | Coverage |
|---|---|
| `test_parser.py` | Input parsing, unit conversion, alias resolution |
| `test_validator.py` | All rule-based validation checks |
| `test_engine.py` | Inference, constraint validation, deployment planning |
| `test_confidence.py` | Confidence score computation |
| `test_pipeline.py` | End-to-end pipeline integration |
| `test_api.py` | HTTP route handlers |
| `test_registry.py` | Router registry loading |
| `test_data_quality.py` | Data quality gate logic |
| `test_security.py` | Auth, input sanitization |

---

## Adding a New Router

1. Add the router spec to `graph/router_registry.json`
2. Restart the API (or run `python main.py` to re-seed)
3. Optionally add name aliases to `ROUTER_ALIASES` in `parser/input_parser.py`

The weight engine (`graph/weight_engine.py`) automatically computes all IMPLIES edge weights using the log-normalized formula — no manual weight tuning needed.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `FALKOR_HOST` | `localhost` | FalkorDB hostname |
| `FALKOR_PORT` | `6379` | FalkorDB port |
| `GRAPH_NAME` | `infra_planner` | Graph name in FalkorDB |
| `API_PORT` | `8000` | FastAPI server port |
| `API_SECRET_KEY` | — | Required for admin endpoints |
| `ALLOWED_ORIGINS` | `*` | CORS allowed origins (comma-separated) |
| `OPENAI_API_KEY` | — | Required for LLM explanation + agentic validation |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for LLM calls |
| `LLM_EXPLANATION_ENABLED` | `true` | Toggle LLM features on/off |

---

## Architecture Notes

- The graph is **read-only** during normal `/plan` requests. Only `/admin/routers` writes to the graph.
- The agentic validator (LLM) fires **only for unknown routers** (similarity < 0.30). Known routers incur zero LLM cost.
- The data quality gate runs **before graph traversal** — junk inputs never reach the inference engine.
- All topology classification is **graph-driven** via `DeploymentPattern` nodes. There is no hardcoded topology logic in the planner.
- Edge weights are **auto-computed** from router feature values using a shared log-normalized formula in `weight_engine.py`.
