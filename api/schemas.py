# api/schemas.py
# Pydantic models for HTTP request/response serialization.
# Request shape mirrors input_parser.py SPEC_SCHEMA exactly.
# Response shape mirrors engine/deployment_planner.py DeploymentPlan.

from pydantic import BaseModel, Field
from typing import Optional


# ── Request ───────────────────────────────────────────────────────────────────

class FeatureValue(BaseModel):
    value: float = Field(gt=0, description="Must be a positive number")
    unit:  str


class RouterSpecRequest(BaseModel):
    model:          str = Field(min_length=1, max_length=200, json_schema_extra={"strip_whitespace": True})
    vendor:         Optional[str] = "Unknown"
    series:         Optional[str] = ""
    switching_cap:  FeatureValue
    forwarding_rate: FeatureValue
    ipv4_routes:    FeatureValue
    dram_gb:        FeatureValue
    stacking_bw:    Optional[FeatureValue] = None
    vlan_ids:       Optional[FeatureValue] = None
    mac_addresses:  Optional[FeatureValue] = None

    def to_raw(self) -> dict:
        """Convert to the raw dict format expected by input_parser.parse()."""
        raw = {
            "model":  self.model,
            "vendor": self.vendor,
            "series": self.series,
        }
        for field_name in (
            "switching_cap", "forwarding_rate", "ipv4_routes", "dram_gb",
            "stacking_bw", "vlan_ids", "mac_addresses",
        ):
            val = getattr(self, field_name)
            if val is not None:
                raw[field_name] = {"value": val.value, "unit": val.unit}
        return raw


# ── Response ──────────────────────────────────────────────────────────────────

class NodeSpecResponse(BaseModel):
    node_id:     str
    role:        str
    vcpu:        int
    ram_gb:      int
    ports:       int
    storage_gb:  int
    profile_name: str


class ClusterSpecResponse(BaseModel):
    cluster_id:    str
    topology_type: str
    node_count:    int
    total_vcpu:    int
    total_ram_gb:  int
    total_ports:   int
    nodes:         list[NodeSpecResponse]


class ConfidenceResponse(BaseModel):
    score:            float
    label:            str
    signal_strength:  float
    graph_match:      float
    constraint_clean: float
    profile_fit:      float
    feature_coverage: float = 0.5   # new (IMPROVE-03); default 0.5 for backward compat
    breakdown:        list[str]


class DeploymentPlanResponse(BaseModel):
    router_id:           str
    router_name:         str = ""
    plan_status:         str = "ok"          # "ok" | "needs_review"
    plan_status_reason:  str = ""            # human-readable reason when needs_review
    valid:               bool
    cluster_count:       int
    topology_type:       str
    ha_enabled:          bool
    clusters:            list[ClusterSpecResponse]
    warnings:            list[str]
    violations:          list[str]
    reasoning:           list[str]
    explanation:         str
    simple_explanation:  str = ""
    similarity_score:    float = 1.0
    similar_to:          Optional[str] = None
    confidence:          Optional[ConfidenceResponse] = None
    data_quality_score:  float = 1.0         # 0.0–1.0, computed before inference
    pattern_name:        str = ""
    pattern_description: str = ""
    graph_ids:           list[str] = Field(default_factory=list)

class ExplainRequest(BaseModel):
    nodes: list[dict] = Field(default_factory=list, max_length=50)
    edges: list[dict] = Field(default_factory=list, max_length=100)


class ErrorResponse(BaseModel):
    error:   str
    detail:  Optional[str] = None
