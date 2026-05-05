# engine/deployment_planner.py
# Produces the final structured deployment plan from a validated
# InferenceResult + ValidationResult.
#
# Change 6: topology classification is now graph-driven.
# The planner queries DeploymentPattern nodes to find the best matching
# pattern for the selected node roles. No hardcoded topology logic.

from dataclasses import dataclass, field
from engine.inference import InferenceResult, NodeSelection
from engine.constraint_validator import ValidationResult
from engine.confidence import ConfidenceScore


@dataclass
class NodeSpec:
    node_id:      str
    role:         str
    vcpu:         int
    ram_gb:       int
    ports:        int
    storage_gb:   int
    profile_name: str


@dataclass
class ClusterSpec:
    cluster_id:    str
    topology_type: str
    nodes: list[NodeSpec] = field(default_factory=list)

    @property
    def total_vcpu(self) -> int:
        return sum(n.vcpu for n in self.nodes)

    @property
    def total_ram_gb(self) -> int:
        return sum(n.ram_gb for n in self.nodes)

    @property
    def total_ports(self) -> int:
        return sum(n.ports for n in self.nodes)

    @property
    def node_count(self) -> int:
        return len(self.nodes)


@dataclass
class DeploymentPlan:
    router_id:           str
    clusters:            list[ClusterSpec]
    topology_type:       str
    ha_enabled:          bool
    reasoning:           list[str]
    warnings:            list[str]
    violations:          list[str]
    valid:               bool
    explanation:         str = ""
    simple_explanation:  str = ""           # plain-English, jargon-free
    plan_status:         str = "ok"         # "ok" | "needs_review"
    plan_status_reason:  str = ""           # why planning was skipped
    data_quality_score:  float = 1.0        # 0.0–1.0, computed before inference
    router_name:         str = ""           # submitted router display name
    similarity_score:    float = 1.0
    similar_to:          str | None = None
    confidence:          ConfidenceScore | None = None
    pattern_name:        str = ""
    pattern_description: str = ""

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)


def plan(
    inference_result: InferenceResult,
    validation_result: ValidationResult,
    graph=None,                          # optional — enables graph-driven pattern matching
) -> DeploymentPlan:
    """
    Build the final deployment plan from validated node selections.

    If graph is provided: queries DeploymentPattern nodes to determine
    topology type, cluster count, and HA setting.
    If graph is None: falls back to Python-based classification.
    """
    selections  = validation_result.adjusted_selections
    reasoning   = list(inference_result.reasoning)
    warnings    = list(validation_result.warnings)
    total_nodes = sum(s.count for s in selections)

    # ── Topology from graph ───────────────────────────────────────────────────
    present_roles = list({s.role for s in selections if s.role != "balanced"})
    pattern       = None

    if graph is not None:
        from graph.queries import get_deployment_pattern
        pattern = get_deployment_pattern(graph, present_roles)

    if pattern:
        topology_type  = pattern["topology_label"]
        ha_enabled     = pattern["ha_enabled"]
        cluster_count  = max(1, pattern["cluster_count"])
        pattern_name   = pattern["name"]
        pattern_desc   = pattern["description"]
        # NOTE: cluster_count here is the pattern's base value.
        # It may be increased below if total_nodes exceeds 8.
        # The [Pattern] reasoning line is written after the override so it
        # always reflects the final cluster_count, not the pattern default.
    else:
        # Fallback — Python classification when graph unavailable
        topology_type  = _classify_topology_fallback(selections)
        ha_enabled     = total_nodes >= 3
        cluster_count  = max(1, -(-total_nodes // 8))
        pattern_name   = "fallback"
        pattern_desc   = "Graph pattern matching unavailable — used Python fallback."

    # Override cluster_count if total nodes exceed the preferred cluster size.
    # This happens when inference produces more nodes than the pattern's max_nodes.
    pattern_cluster_count = cluster_count   # save original for the reasoning trace
    if total_nodes > 8:
        cluster_count = max(cluster_count, -(-total_nodes // 8))

    # Write the [Pattern] reasoning line now, after the override, so it
    # reflects the final cluster_count and explains any split that occurred.
    if pattern:
        reasoning.append(
            f"[Pattern] Matched '{pattern['name']}' "
            f"(required_roles={pattern['required_roles']}): "
            f"topology={topology_type}, clusters={cluster_count}, "
            f"ha={ha_enabled}"
        )
        if cluster_count > pattern_cluster_count:
            reasoning.append(
                f"[Pattern] '{pattern['name']}' base cluster count is "
                f"{pattern_cluster_count}, but total node count ({total_nodes}) "
                f"exceeds the preferred cluster size of 8. "
                f"Planner split the deployment into {cluster_count} cluster(s) "
                f"to keep each cluster at a manageable size."
            )
    else:
        reasoning.append(f"[Pattern] No graph match — fallback topology={topology_type}, clusters={cluster_count}")
        if cluster_count > 1:
            reasoning.append(
                f"[Pattern] Fallback: total node count ({total_nodes}) exceeds "
                f"preferred cluster size of 8. "
                f"Planner split the deployment into {cluster_count} cluster(s)."
            )

    # ── Build clusters ────────────────────────────────────────────────────────
    clusters = [
        ClusterSpec(cluster_id=f"cluster_{i+1}", topology_type=topology_type)
        for i in range(cluster_count)
    ]

    node_counter = 1
    cluster_idx  = 0
    role_order   = ["compute", "network", "memory", "storage", "balanced", "general"]
    sorted_sels  = sorted(
        selections,
        key=lambda s: role_order.index(s.role) if s.role in role_order else 99
    )

    for sel in sorted_sels:
        for _ in range(sel.count):
            node = NodeSpec(
                node_id=f"node_{node_counter}",
                role=sel.role,
                vcpu=sel.vcpu,
                ram_gb=sel.ram_gb,
                ports=sel.ports,
                storage_gb=sel.storage_gb,
                profile_name=sel.profile_name,
            )
            clusters[cluster_idx % cluster_count].nodes.append(node)
            node_counter += 1
            cluster_idx  += 1

    for c in clusters:
        reasoning.append(
            f"[Plan] {c.cluster_id}: {c.node_count} nodes | "
            f"topology={c.topology_type} | "
            f"vCPU={c.total_vcpu} RAM={c.total_ram_gb}GB Ports={c.total_ports}"
        )

    return DeploymentPlan(
        router_id=inference_result.router_id,
        clusters=clusters,
        topology_type=topology_type,
        ha_enabled=ha_enabled,
        reasoning=reasoning,
        warnings=warnings,
        violations=validation_result.violations,
        valid=validation_result.valid,
        # confidence is computed in main.py with full context (profiles + feature names).
        confidence=None,
        pattern_name=pattern_name,
        pattern_description=pattern_desc,
    )


def _classify_topology_fallback(selections: list[NodeSelection]) -> str:
    """Python fallback — only used when graph is unavailable."""
    total = sum(s.count for s in selections)
    roles = {s.role for s in selections}
    if total <= 3:
        return "minimal"
    if "network" in roles and "compute" in roles and "memory" in roles:
        return "high_performance"
    if "compute" in roles and total >= 4:
        return "compute_heavy"
    return "balanced"
