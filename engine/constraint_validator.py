# engine/constraint_validator.py
# Enforces hard infrastructure constraints on an InferenceResult.
# Constraints are data, not code — defined in CONSTRAINTS dict.
# Validator adjusts counts where possible; flags violations it cannot fix.

from dataclasses import dataclass, field
from engine.inference import InferenceResult, NodeSelection


@dataclass
class ValidationResult:
    valid: bool
    violations: list[str]
    warnings: list[str]
    adjusted_selections: list[NodeSelection]  # may differ from input if auto-fixed


# ── Constraint definitions ────────────────────────────────────────────────────
# Each constraint is a dict with:
#   type:     "min_count" | "max_count" | "min_vcpu" | "max_vcpu" |
#             "min_ram"   | "max_ram"   | "min_ports" | "max_ports"
#   applies:  "all" | role name (e.g. "compute", "network", "memory")
#   value:    the limit
#   severity: "error" (blocks plan) | "warning" (flags but allows)
#   reason:   human-readable explanation

CONSTRAINTS: list[dict] = [
    # HA: every cluster needs at least 3 nodes total
    {"type": "min_total_nodes", "value": 3,    "severity": "error",
     "reason": "Minimum 3 nodes required for Kubernetes HA (etcd quorum)"},

    # Node count caps per role
    # Compute cap raised to 16 — high forwarding-rate routers (e.g. MX480 at
    # 3000 Mpps) legitimately need more than 8 compute nodes. The old cap of 8
    # was calibrated for access-layer switches, not core routers.
    {"type": "max_count", "applies": "compute", "value": 16, "severity": "warning",
     "reason": "More than 16 compute nodes per cluster is unusual; consider splitting clusters"},
    # Network cap kept at 4 per cluster but downgraded to warning — the
    # constraint validator was silently destroying valid inference results
    # by hard-capping and never surfacing the real demand to the planner.
    {"type": "max_count", "applies": "network", "value": 4, "severity": "warning",
     "reason": "Max 4 network nodes per cluster recommended — beyond this, split into a second cluster"},
    # Memory cap raised to 8 — high-route-scale routers need more RIB/FIB nodes.
    {"type": "max_count", "applies": "memory",  "value": 8, "severity": "warning",
     "reason": "More than 8 memory nodes per cluster is unusual; verify routing table size"},

    # Resource floor per node
    {"type": "min_vcpu",  "applies": "all", "value": 8,   "severity": "error",
     "reason": "Minimum 8 vCPU per node for Kubernetes system overhead"},
    {"type": "min_ram",   "applies": "all", "value": 16,  "severity": "error",
     "reason": "Minimum 16 GB RAM per node"},
    {"type": "min_ports", "applies": "all", "value": 4,   "severity": "warning",
     "reason": "Minimum 4 ports recommended for redundant networking"},

    # Resource ceiling per node
    {"type": "max_vcpu",  "applies": "all", "value": 128, "severity": "warning",
     "reason": "Nodes >128 vCPU are uncommon; verify hardware availability"},
    {"type": "max_ram",   "applies": "all", "value": 1024,"severity": "warning",
     "reason": "Nodes >1 TB RAM are uncommon; verify hardware availability"},
    {"type": "max_ports", "applies": "all", "value": 128, "severity": "error",
     "reason": "Max 128 ports per node — beyond this, add network nodes"},
]


def validate(result: InferenceResult) -> ValidationResult:
    violations: list[str] = []
    warnings:   list[str] = []
    adjusted = [_copy_selection(s) for s in result.node_selections]

    # Per-node constraints
    for sel in adjusted:
        _check_node(sel, violations, warnings)

    # Cluster-level constraints
    _check_cluster(adjusted, violations, warnings)

    return ValidationResult(
        valid=len(violations) == 0,
        violations=violations,
        warnings=warnings,
        adjusted_selections=adjusted,
    )


# ── Per-node checks ───────────────────────────────────────────────────────────

def _check_node(sel: NodeSelection, violations: list, warnings: list):
    role = sel.role

    for c in CONSTRAINTS:
        applies = c.get("applies", "all")
        if applies != "all" and applies != role:
            continue

        ctype = c["type"]
        limit = c["value"]
        sev   = c["severity"]

        if ctype == "min_vcpu" and sel.vcpu < limit:
            _flag(sev, f"{sel.profile_name}: vCPU={sel.vcpu} < min {limit}. {c['reason']}",
                  violations, warnings)

        elif ctype == "max_vcpu" and sel.vcpu > limit:
            _flag(sev, f"{sel.profile_name}: vCPU={sel.vcpu} > max {limit}. {c['reason']}",
                  violations, warnings)

        elif ctype == "min_ram" and sel.ram_gb < limit:
            _flag(sev, f"{sel.profile_name}: RAM={sel.ram_gb}GB < min {limit}GB. {c['reason']}",
                  violations, warnings)

        elif ctype == "max_ram" and sel.ram_gb > limit:
            _flag(sev, f"{sel.profile_name}: RAM={sel.ram_gb}GB > max {limit}GB. {c['reason']}",
                  violations, warnings)

        elif ctype == "min_ports" and sel.ports < limit:
            _flag(sev, f"{sel.profile_name}: ports={sel.ports} < min {limit}. {c['reason']}",
                  violations, warnings)

        elif ctype == "max_ports" and sel.ports > limit:
            _flag(sev, f"{sel.profile_name}: ports={sel.ports} > max {limit}. {c['reason']}",
                  violations, warnings)

        elif ctype == "max_count" and sel.count > limit:
            # Auto-fix: cap count and flag as warning
            warnings.append(
                f"{sel.profile_name}: count={sel.count} capped to {limit}. {c['reason']}"
            )
            sel.count = limit


# ── Cluster-level checks ──────────────────────────────────────────────────────

def _check_cluster(selections: list[NodeSelection], violations: list, warnings: list):
    total_nodes = sum(s.count for s in selections)

    for c in CONSTRAINTS:
        if c["type"] == "min_total_nodes" and total_nodes < c["value"]:
            # Auto-fix: pad with balanced nodes
            shortfall = c["value"] - total_nodes
            warnings.append(
                f"Total nodes={total_nodes} < HA minimum {c['value']}. "
                f"Adding {shortfall} balanced node(s). {c['reason']}"
            )
            selections.append(NodeSelection(
                profile_id="np_balanced",
                profile_name="Balanced (HA pad)",
                role="balanced",
                vcpu=32, ram_gb=256, ports=32, storage_gb=1000,
                count=shortfall,
                fit_score=0.0,
                satisfies=[],
            ))


# ── Utilities ─────────────────────────────────────────────────────────────────

def _flag(severity: str, msg: str, violations: list, warnings: list):
    if severity == "error":
        violations.append(msg)
    else:
        warnings.append(msg)


def _copy_selection(s: NodeSelection) -> NodeSelection:
    return NodeSelection(
        profile_id=s.profile_id, profile_name=s.profile_name,
        role=s.role, vcpu=s.vcpu, ram_gb=s.ram_gb,
        ports=s.ports, storage_gb=s.storage_gb,
        count=s.count, fit_score=s.fit_score,
        satisfies=list(s.satisfies),
    )
