# engine/inference.py
# Inference engine: transforms graph traversal output into concrete
# resource targets and a ranked node selection.
#
# Reasoning flow:
#   1. Scale each InfraRequirement's min_value by the implication signal
#      strength → demand_target (what the router actually needs, not just
#      the seed floor).
#   2. For each resource type, pick the best-fit NodeProfile.
#   3. Determine how many instances of each profile are needed so that
#      the aggregate capacity meets every demand_target.
#
# No hard-coded thresholds. All scaling comes from graph weights.

from dataclasses import dataclass, field


# ── Implication → resource type influence map ─────────────────────────────────
# These are INTENTIONAL domain knowledge — not stale hardcoding.
# They answer: "how much does this implication type amplify this resource?"
# This cannot be auto-derived from router specs because it encodes
# infrastructure engineering knowledge, not hardware measurements.
#
# Example: oi_high_pkt amplifies cpu by 2.5x because packet processing
# is CPU-bound by nature — that's a networking engineering fact, not
# something derivable from a forwarding rate number alone.
#
# Weights (base_weight on IMPLIES edges) are auto-computed in weight_engine.py.
# Influence coefficients here are fixed domain knowledge and owned by engineers.

# Influence coefficients encode infrastructure engineering knowledge.
# These answer: "how much does this implication type amplify this resource?"
#
# cpu raised to 3.0 (was 2.5 originally, briefly 4.0):
#   4.0 over-provisioned small routers (9200 got 3 Compute-XL).
#   3.0 combined with the log-compressed scaling formula below gives
#   correct progression: 9200=1 node, 9300X=2, 9500=2, MX480=2.
#
# oi_high_route routing=3.0, memory=1.5 (raised from 2.0/1.0):
#   1M+ IPv4 routes (ASR, MX480) need more RIB/FIB nodes than campus switches.
#   The log-compressed formula keeps small-route routers (9200: 8K routes)
#   from being over-provisioned while still scaling up for WAN/SP routers.
#
# All other coefficients unchanged — they were already well-calibrated.
IMPLICATION_RESOURCE_INFLUENCE: dict[str, dict[str, float]] = {
    "oi_high_pkt":   {"cpu":        3.0, "storage":   0.5},
    "oi_high_net":   {"networking": 2.0, "ports":     1.5},
    "oi_high_route": {"routing":    3.0, "memory":    1.5},
    "oi_high_mem":   {"memory":     2.5},
    "oi_port_dense": {"ports":      2.0},
}


@dataclass
class ResourceTarget:
    resource_type: str
    seed_min: float
    unit: str
    demand_target: float      # scaled by implication signal
    signal_strength: float    # total implication weight driving this resource


@dataclass
class NodeSelection:
    profile_id: str
    profile_name: str
    role: str
    vcpu: int
    ram_gb: int
    ports: int
    storage_gb: int
    count: int                # how many nodes of this profile
    fit_score: float
    satisfies: list[str]      # resource_types this profile covers


@dataclass
class InferenceResult:
    router_id: str
    resource_targets: list[ResourceTarget]
    node_selections: list[NodeSelection]
    reasoning: list[str]      # human-readable reasoning trace


def infer(
    router_id: str,
    implications: list[dict],       # from get_implications_for_router
    requirements: list[dict],       # from get_requirements_for_implications
    profiles: list[dict],           # from get_node_profiles_for_requirements
    instance_weights: dict[str, float] | None = None,  # from entity_mapper
) -> InferenceResult:
    """
    Core inference pipeline.
    instance_weights override graph base_weights for demand scaling.
    If not provided, falls back to graph base_weights (known routers).
    """
    reasoning: list[str] = []
    targets    = _compute_targets(implications, requirements, reasoning, instance_weights)
    selections = _select_profiles(targets, profiles, reasoning)
    return InferenceResult(
        router_id=router_id,
        resource_targets=targets,
        node_selections=selections,
        reasoning=reasoning,
    )


# ── Step 1: Demand-scaled resource targets ────────────────────────────────────

def _compute_targets(
    implications: list[dict],
    requirements: list[dict],
    reasoning: list[str],
    instance_weights: dict[str, float] | None = None,
) -> list[ResourceTarget]:
    """
    Compute demand_target = seed_min * (1 + signal)
    Uses instance_weights if provided (unknown/similar routers),
    otherwise uses base_weights from graph (known routers).
    Reasoning trace shows both values when they differ.
    """
    # Effective weights: instance overrides base when available
    base_weights = {i["id"]: float(i["total_weight"]) for i in implications}
    effective    = instance_weights if instance_weights else base_weights

    targets = []
    for req in requirements:
        rtype    = req["resource_type"]
        seed_min = float(req["min_value"])
        unit     = req["unit"]

        signal  = 0.0
        drivers = []
        for impl_id, influences in IMPLICATION_RESOURCE_INFLUENCE.items():
            if rtype in influences and impl_id in effective:
                contribution = influences[rtype] * effective[impl_id]
                signal += contribution
                base_w = base_weights.get(impl_id, 0.0)
                inst_w = effective[impl_id]
                note   = f"{impl_id}(×{influences[rtype]}×{inst_w:.3f}"
                if instance_weights and abs(inst_w - base_w) > 0.001:
                    note += f"|base={base_w:.3f}"
                note += ")"
                drivers.append(note)

        # Scaling formula: demand_target = seed_min * (1 + signal * ln(1 + signal))
        #
        # This is a log-compressed super-linear curve. It behaves correctly
        # across all router classes without per-class tuning:
        #
        #   signal=0.0 (no demand)    → multiplier = 1.0   (seed floor only)
        #   signal=0.7 (access/edge)  → multiplier ≈ 1.39  (gentle uplift)
        #   signal=1.4 (campus)       → multiplier ≈ 2.22  (moderate)
        #   signal=2.1 (core/WAN)     → multiplier ≈ 3.35  (significant)
        #   signal=3.5 (high-end SP)  → multiplier ≈ 5.74  (strong)
        #
        # Why not (1+signal)^1.4:
        #   The power formula amplifies even weak signals super-linearly.
        #   A 9200 with cpu signal=1.69 got (2.69)^1.4 = 4.43× → 141 vCPU → 3 nodes.
        #   The log-compressed formula gives 1 + 1.69*ln(2.69) = 2.98× → 95 vCPU → 2 nodes.
        #   For MX480 with signal=2.09: 1 + 2.09*ln(3.09) = 3.35× → 107 vCPU → 2 nodes.
        #   The gap between access and core is preserved without over-provisioning either.
        import math as _math
        multiplier    = 1.0 + signal * _math.log(1.0 + signal) if signal > 0 else 1.0
        demand_target = round(seed_min * multiplier, 2)
        reasoning.append(
            f"[Target] {req['name']}: seed_min={seed_min} {unit}, "
            f"signal={signal:.4f} → demand_target={demand_target} {unit}"
            + (f"  drivers=[{', '.join(drivers)}]" if drivers else "")
        )
        targets.append(ResourceTarget(
            resource_type=rtype,
            seed_min=seed_min,
            unit=unit,
            demand_target=demand_target,
            signal_strength=signal,
        ))
    return targets


# ── Step 2: Profile selection ─────────────────────────────────────────────────

# Maps NodeProfile resource fields to resource_type keys
PROFILE_CAPACITY: dict[str, str] = {
    "vcpu":       "cpu",
    "ram_gb":     "memory",
    "ports":      "ports",
    "storage_gb": "storage",
}

# Maps resource_type → preferred node role
# Used to break ties when two profiles have equal fit for a resource type.
RESOURCE_ROLE_PREFERENCE: dict[str, str] = {
    "cpu":        "compute",
    "memory":     "memory",
    "networking": "network",
    "ports":      "network",
    "routing":    "memory",
    "storage":    "storage",
}


def _select_profiles(
    targets: list[ResourceTarget],
    profiles: list[dict],
    reasoning: list[str],
) -> list[NodeSelection]:
    """
    Per-resource profile selection.

    For each resource type, pick the profile with the highest per-resource
    fit score from fit_breakdown. A profile that has no fit_breakdown entry
    for a resource type scores 0.0 for that type — it is never a candidate.

    This prevents high-total_fit profiles (e.g. Memory-XL with total_fit=2.0)
    from winning resource types they were never designed for (e.g. cpu, ports)
    simply because their aggregate score exceeds a specialist profile's
    per-resource score.

    Role preference is used only to break exact ties between two profiles
    that both have an explicit fit_breakdown entry for the same resource type.

    Deduplication: if the same profile wins for multiple resource types,
    it is selected once with count = max across all types it covers.
    """
    target_map = {t.resource_type: t for t in targets}

    # Parse fit_breakdown into per-profile per-resource scores.
    # fit_breakdown format from graph query: ["cpu:1.0", "memory:0.8", ...]
    # A missing entry means the profile has NO SATISFIED_BY edge for that
    # resource type — score is 0.0, not total_fit.
    profile_resource_fit: dict[str, dict[str, float]] = {}
    for p in profiles:
        pid = p["id"]
        profile_resource_fit[pid] = {}
        for entry in (p.get("fit_breakdown") or []):
            if ":" in str(entry):
                rtype, score = str(entry).rsplit(":", 1)
                try:
                    profile_resource_fit[pid][rtype.strip()] = float(score)
                except ValueError:
                    pass

    # For each resource type, pick the best profile by per-resource fit score.
    # Profiles with no fit_breakdown entry for this resource type score 0.0
    # and are excluded unless no other profile has a positive score.
    resource_winner: dict[str, dict] = {}   # {resource_type: profile_dict}
    for rtype, target in target_map.items():
        best_profile = None
        best_score   = -1.0
        preferred_role = RESOURCE_ROLE_PREFERENCE.get(rtype, "")

        # Capacity field for this resource type (needed to verify the profile
        # can actually provide this resource, not just that it has a fit score).
        capacity_field = next(
            (f for f, r in PROFILE_CAPACITY.items() if r == rtype), None
        )

        for p in profiles:
            pid = p["id"]

            # Only consider profiles that have physical capacity for this resource.
            if capacity_field:
                capacity = float(p.get(capacity_field, 0))
                if capacity <= 0:
                    continue

            # Score = explicit per-resource fit score from fit_breakdown.
            # 0.0 if the profile has no SATISFIED_BY edge for this resource type.
            # Never fall back to total_fit — that caused Memory-XL to win cpu/ports.
            score = profile_resource_fit.get(pid, {}).get(rtype, 0.0)

            if score <= 0.0:
                continue   # profile does not satisfy this resource type at all

            # Prefer role-matched profiles on exact tie.
            if score > best_score or (
                abs(score - best_score) < 0.001 and p["role"] == preferred_role
            ):
                best_score   = score
                best_profile = p

        if best_profile:
            resource_winner[rtype] = best_profile

    # Deduplicate: group resource types by winning profile.
    profile_to_rtypes: dict[str, list[str]] = {}
    for rtype, p in resource_winner.items():
        pid = p["id"]
        profile_to_rtypes.setdefault(pid, []).append(rtype)

    # Order by total_fit descending so primary profiles come first.
    ordered = sorted(
        profile_to_rtypes.items(),
        key=lambda x: next(p["total_fit"] for p in profiles if p["id"] == x[0]),
        reverse=True,
    )

    selections: list[NodeSelection] = []
    for pid, rtypes in ordered:
        p     = next(pr for pr in profiles if pr["id"] == pid)
        count = _compute_node_count(p, rtypes, target_map)

        sel = NodeSelection(
            profile_id=pid,
            profile_name=p["name"],
            role=p["role"],
            vcpu=int(p["vcpu"]),
            ram_gb=int(p["ram_gb"]),
            ports=int(p["ports"]),
            storage_gb=int(p["storage_gb"]),
            count=count,
            fit_score=float(p["total_fit"]),
            satisfies=rtypes,
        )
        selections.append(sel)
        reasoning.append(
            f"[Select] {p['name']} (fit={p['total_fit']:.4f}, role={p['role']}): "
            f"count={count}, covers={rtypes}"
        )

    return selections


def _compute_node_count(
    profile: dict,
    satisfies: list[str],
    target_map: dict[str, ResourceTarget],
) -> int:
    """
    count = ceil(demand_target / profile_capacity)
    Most constraining resource type wins.
    Minimum 1. No upper cap here — the constraint validator enforces
    per-role max_count and emits the correct warning. (FIX-05)
    """
    import math
    counts = []
    for rtype in satisfies:
        target = target_map[rtype].demand_target
        capacity = next(
            (float(profile[f]) for f, r in PROFILE_CAPACITY.items()
             if r == rtype and float(profile.get(f, 0)) > 0),
            None,
        )
        if capacity and capacity > 0:
            counts.append(max(1, math.ceil(target / capacity)))
            # Upper cap removed — constraint_validator.py owns that policy
    return max(counts) if counts else 1
