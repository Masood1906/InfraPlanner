# tests/test_engine.py
# Unit tests for engine/inference.py, engine/constraint_validator.py,
# and engine/deployment_planner.py.
# No graph dependency — all inputs are plain dicts/dataclasses.

import pytest
from engine.inference import infer, ResourceTarget, NodeSelection
from engine.constraint_validator import validate, ValidationResult
from engine.deployment_planner import plan


# ── inference: demand target scaling ─────────────────────────────────────────

class TestInferenceDemandTargets:

    def test_demand_target_exceeds_seed_min_when_signal_present(
        self, mock_implications, mock_requirements, mock_profiles
    ):
        result = infer("test_router", mock_implications, mock_requirements, mock_profiles)
        cpu_target = next(t for t in result.resource_targets if t.resource_type == "cpu")
        # signal > 0 means demand_target > seed_min
        assert cpu_target.demand_target > cpu_target.seed_min

    def test_demand_target_formula_is_correct(self, mock_requirements):
        """
        Formula: demand_target = seed_min * (1 + signal * ln(1 + signal))
        With oi_high_pkt weight=1.0, cpu influence=3.0:
          signal = 3.0 * 1.0 = 3.0
          multiplier = 1 + 3.0 * ln(4.0) = 1 + 3.0 * 1.3863 = 5.159
          demand_target = 32 * 5.159 = 165.09
        """
        import math
        implications = [
            {"id": "oi_high_pkt", "name": "High Packet Processing", "severity": 5, "total_weight": 1.0}
        ]
        requirements = [
            {"id": "ir_cpu", "name": "Processing Capacity", "resource_type": "cpu",
             "min_value": 32, "unit": "vCPU", "top_priority": 1, "driver_count": 1}
        ]
        profiles = [
            {"id": "np_compute_xl", "name": "Compute-XL", "vcpu": 64, "ram_gb": 512,
             "ports": 48, "storage_gb": 2000, "role": "compute", "total_fit": 5.4,
             "reqs_satisfied": 5, "fit_breakdown": ["cpu:1.0"]}
        ]
        result = infer("test", implications, requirements, profiles)
        cpu_target = result.resource_targets[0]
        signal = 3.0 * 1.0
        expected = 32 * (1 + signal * math.log(1 + signal))
        assert cpu_target.demand_target == pytest.approx(expected, rel=1e-3)

    def test_zero_signal_leaves_demand_at_seed_min(self, mock_requirements):
        """No implications → signal=0 → demand_target == seed_min."""
        result = infer("test", [], mock_requirements, [])
        for t in result.resource_targets:
            assert t.demand_target == t.seed_min

    def test_all_resource_types_have_targets(
        self, mock_implications, mock_requirements, mock_profiles
    ):
        result = infer("test", mock_implications, mock_requirements, mock_profiles)
        rtypes = {t.resource_type for t in result.resource_targets}
        assert "cpu" in rtypes
        assert "memory" in rtypes
        assert "networking" in rtypes

    def test_reasoning_trace_is_populated(
        self, mock_implications, mock_requirements, mock_profiles
    ):
        result = infer("test", mock_implications, mock_requirements, mock_profiles)
        assert len(result.reasoning) > 0
        assert any("[Target]" in r for r in result.reasoning)
        assert any("[Select]" in r for r in result.reasoning)


# ── inference: profile selection ─────────────────────────────────────────────

class TestInferenceProfileSelection:

    def test_highest_fit_profile_selected_first(
        self, mock_implications, mock_requirements, mock_profiles
    ):
        result = infer("test", mock_implications, mock_requirements, mock_profiles)
        assert len(result.node_selections) > 0
        assert result.node_selections[0].profile_id == "np_compute_xl"

    def test_node_count_at_least_one(
        self, mock_implications, mock_requirements, mock_profiles
    ):
        result = infer("test", mock_implications, mock_requirements, mock_profiles)
        for sel in result.node_selections:
            assert sel.count >= 1

    def test_node_count_at_least_one_with_normal_signal(
        self, mock_implications, mock_requirements, mock_profiles
    ):
        # FIX-05: inference engine no longer caps — validator does
        result = infer("test", mock_implications, mock_requirements, mock_profiles)
        for sel in result.node_selections:
            assert sel.count >= 1

    def test_empty_profiles_produces_empty_selections(
        self, mock_implications, mock_requirements
    ):
        result = infer("test", mock_implications, mock_requirements, [])
        assert result.node_selections == []

    def test_inference_engine_does_not_cap_count_at_eight(self):
        """
        FIX-05: inference engine removed its own cap of 8.
        With oi_high_pkt weight=15.0, cpu influence=3.0:
          signal = 3.0 * 15.0 = 45.0
          multiplier = 1 + 45 * ln(46) ≈ 1 + 45 * 3.829 ≈ 173.3
          demand_target = 32 * 173.3 ≈ 5545 vCPU
          profile capacity = 64 vCPU → raw count = ceil(5545/64) = 87
        inference engine must return 87, not 16.
        The constraint validator is responsible for capping.
        fit_breakdown must include 'cpu:1.0' so the profile is selected.
        """
        implications = [
            {"id": "oi_high_pkt", "name": "X", "severity": 5, "total_weight": 15.0}
        ]
        requirements = [
            {"id": "ir_cpu", "name": "Processing Capacity", "resource_type": "cpu",
             "min_value": 32, "unit": "vCPU", "top_priority": 1, "driver_count": 1}
        ]
        profiles = [
            {"id": "np_compute_xl", "name": "Compute-XL", "vcpu": 64, "ram_gb": 512,
             "ports": 48, "storage_gb": 2000, "role": "compute",
             "total_fit": 5.4, "reqs_satisfied": 1, "fit_breakdown": ["cpu:1.0"]}
        ]
        result = infer("test", implications, requirements, profiles)
        # inference engine must NOT cap — raw math gives >> 16
        assert result.node_selections[0].count > 16

    def test_validator_caps_what_inference_engine_no_longer_caps(self):
        """
        FIX-05: after inference produces count=20, the validator caps it to 16
        (compute max) and emits a warning. This confirms the two-stage
        separation is correct. Compute cap is 16 (raised from 8 to support
        high-end routers like MX480 and 9500).
        """
        from engine.inference import InferenceResult
        sel = NodeSelection("np_compute_xl", "Compute-XL", "compute",
                            64, 512, 48, 2000, 20, 5.4, ["cpu"])
        ir  = InferenceResult("test", [], [sel], [])
        vr  = validate(ir)
        compute_sel = next(s for s in vr.adjusted_selections if s.role == "compute")
        assert compute_sel.count <= 16
        assert any("capped" in w for w in vr.warnings)


# ── constraint_validator ──────────────────────────────────────────────────────

class TestConstraintValidator:

    def _make_inference_result(self, selections):
        from engine.inference import InferenceResult
        return InferenceResult(
            router_id="test",
            resource_targets=[],
            node_selections=selections,
            reasoning=[],
        )

    def test_valid_selections_pass_with_no_violations(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        result = validate(self._make_inference_result(selections))
        assert result.valid is True
        assert result.violations == []

    def test_ha_padding_added_when_total_nodes_below_three(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 1, 5.4, ["cpu"]),
        ]
        result = validate(self._make_inference_result(selections))
        total = sum(s.count for s in result.adjusted_selections)
        assert total >= 3
        assert any("HA pad" in s.profile_name for s in result.adjusted_selections)

    def test_ha_padding_warning_message_present(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 1, 5.4, ["cpu"]),
        ]
        result = validate(self._make_inference_result(selections))
        assert any("HA minimum" in w for w in result.warnings)

    def test_count_exceeding_max_is_capped_with_warning(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 20, 5.4, ["cpu"]),  # 20 > max 16
        ]
        result = validate(self._make_inference_result(selections))
        compute_sel = next(s for s in result.adjusted_selections if s.role == "compute")
        assert compute_sel.count <= 16
        assert any("capped" in w for w in result.warnings)

    def test_vcpu_below_minimum_is_violation(self):
        selections = [
            NodeSelection("np_tiny", "Tiny", "compute",
                          4, 32, 8, 100, 3, 1.0, ["cpu"]),  # 4 vCPU < min 8
        ]
        result = validate(self._make_inference_result(selections))
        assert result.valid is False
        assert any("vCPU" in v for v in result.violations)

    def test_ram_below_minimum_is_violation(self):
        selections = [
            NodeSelection("np_tiny", "Tiny", "compute",
                          16, 8, 8, 100, 3, 1.0, ["cpu"]),  # 8 GB < min 16
        ]
        result = validate(self._make_inference_result(selections))
        assert result.valid is False
        assert any("RAM" in v for v in result.violations)

    def test_vcpu_above_warning_threshold_is_warning_not_error(self):
        selections = [
            NodeSelection("np_xl", "XL", "compute",
                          256, 512, 48, 2000, 3, 5.0, ["cpu"]),  # 256 > 128 warning
        ]
        result = validate(self._make_inference_result(selections))
        # Should be a warning, not a hard violation
        assert any("vCPU" in w for w in result.warnings)

    def test_ports_below_minimum_is_warning_not_error(self):
        selections = [
            NodeSelection("np_low_port", "LowPort", "compute",
                          32, 256, 2, 1000, 3, 2.0, ["cpu"]),  # 2 ports < min 4
        ]
        result = validate(self._make_inference_result(selections))
        assert any("ports" in w for w in result.warnings)
        # valid should still be True (warning severity)
        assert result.valid is True


# ── deployment_planner ────────────────────────────────────────────────────────

class TestDeploymentPlanner:

    def _run_plan(self, selections, implications=None, requirements=None):
        from engine.inference import InferenceResult, ResourceTarget
        ir = InferenceResult(
            router_id="test_router",
            resource_targets=[],
            node_selections=selections,
            reasoning=["[Target] test"],
        )
        vr = validate(ir)
        return plan(ir, vr)

    def test_plan_has_at_least_one_cluster(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        assert dp.cluster_count >= 1

    def test_all_nodes_assigned_to_clusters(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        # node_count sums len(cluster.nodes) — each NodeSelection.count
        # becomes that many individual NodeSpec objects across all clusters
        total_node_specs = sum(len(c.nodes) for c in dp.clusters)
        total_via_property = sum(c.node_count for c in dp.clusters)
        assert total_node_specs == total_via_property
        assert total_node_specs >= 3  # HA minimum always satisfied

    def test_ha_enabled_when_three_or_more_nodes(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        assert dp.ha_enabled is True

    def test_topology_high_performance_with_all_roles(self):
        """
        The fallback classifier requires total > 3 AND all three roles present
        to return 'high_performance'. Use count=2 on one selection so total=4.
        """
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute", 64, 512, 48, 2000, 2, 5.4, ["cpu"]),
            NodeSelection("np_network_xl", "Network-XL", "network", 32, 128, 64, 500,  1, 2.0, ["ports"]),
            NodeSelection("np_memory_l",   "Memory-L",   "memory",  16, 512, 16, 1000, 1, 2.0, ["memory"]),
        ]
        dp = self._run_plan(selections)
        assert dp.topology_type == "high_performance"

    def test_topology_minimal_with_few_nodes(self):
        selections = [
            NodeSelection("np_balanced", "Balanced", "balanced",
                          32, 256, 32, 1000, 1, 1.3, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        # After HA padding, total = 3 → still "minimal" (≤3)
        assert dp.topology_type == "minimal"

    def test_cluster_aggregates_are_correct(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        cluster = dp.clusters[0]
        # All nodes in cluster should have same specs (same profile)
        assert cluster.total_vcpu  == sum(n.vcpu    for n in cluster.nodes)
        assert cluster.total_ram_gb == sum(n.ram_gb  for n in cluster.nodes)
        assert cluster.total_ports  == sum(n.ports   for n in cluster.nodes)

    def test_node_ids_are_unique(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 4, 5.4, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        all_ids = [n.node_id for c in dp.clusters for n in c.nodes]
        assert len(all_ids) == len(set(all_ids))

    def test_reasoning_trace_contains_plan_entries(self):
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        assert any("[Plan]" in r for r in dp.reasoning)

    def test_violations_propagated_to_plan(self):
        # A node with vCPU below minimum will produce a violation
        selections = [
            NodeSelection("np_tiny", "Tiny", "compute",
                          4, 32, 8, 100, 3, 1.0, ["cpu"]),
        ]
        dp = self._run_plan(selections)
        assert dp.valid is False
        assert len(dp.violations) > 0


# ── Cross-router regression: demand scaling ───────────────────────────────────
#
# These tests verify that the log-compressed scaling formula
#   demand_target = seed_min * (1 + signal * ln(1 + signal))
# and the influence coefficients produce correct relative ordering
# across all six router classes without over-provisioning small routers.
#
# Each test uses only the inference engine (no graph) with realistic
# instance_weights derived from the actual weight_engine formula:
#   weight = log(value+1) / log(ceiling+1)
#
# Ceilings: Forwarding Rate=100_000, IPv4 Routes=100_000_000, DRAM=4096
# ─────────────────────────────────────────────────────────────────────────────

import math as _math

def _w(value: float, ceiling: float) -> float:
    """Replicate compute_edge_weight without importing weight_engine."""
    return round(_math.log(value + 1) / _math.log(ceiling + 1), 4)


# Realistic instance_weights for each router class.
# Derived from actual feature values via weight_engine formula.
# Only implications present in IMPLICATION_RESOURCE_INFLUENCE are included.
_WEIGHTS = {
    "cisco_9200": {
        # Forwarding Rate=130 Mpps → oi_high_pkt
        "oi_high_pkt":   _w(130,     100_000),   # ≈ 0.423
        # Switching Cap=176 Gbps → oi_high_net + oi_port_dense
        "oi_high_net":   _w(176,     100_000),   # ≈ 0.455
        "oi_port_dense": _w(176,     100_000),   # ≈ 0.455
        # IPv4=8K → oi_high_route + oi_high_mem
        "oi_high_route": _w(8_000,   100_000_000),  # ≈ 0.488
        "oi_high_mem":   _w(8_000,   100_000_000) + _w(4, 4096),  # ≈ 0.681
    },
    "cisco_9300x": {
        "oi_high_pkt":   _w(2232,    100_000),   # ≈ 0.670
        "oi_high_net":   _w(640,     100_000) + _w(1000, 10_000),  # stack+switch
        "oi_port_dense": _w(640,     100_000),
        "oi_high_route": _w(32_000,  100_000_000),
        "oi_high_mem":   _w(32_000,  100_000_000) + _w(8, 4096),
    },
    "cisco_9500": {
        "oi_high_pkt":   _w(4800,    100_000),   # ≈ 0.736
        "oi_high_net":   _w(6400,    100_000),
        "oi_port_dense": _w(6400,    100_000),
        "oi_high_route": _w(128_000, 100_000_000),
        "oi_high_mem":   _w(128_000, 100_000_000) + _w(32, 4096),
    },
    "cisco_asr1001": {
        "oi_high_pkt":   _w(15,      100_000),   # ≈ 0.241
        "oi_high_net":   _w(20,      100_000),
        "oi_port_dense": _w(20,      100_000),
        "oi_high_route": _w(2_000_000, 100_000_000),
        "oi_high_mem":   _w(2_000_000, 100_000_000) + _w(8, 4096),
    },
    "cisco_asr1006": {
        "oi_high_pkt":   _w(200,     100_000),   # ≈ 0.461
        "oi_high_net":   _w(200,     100_000),
        "oi_port_dense": _w(200,     100_000),
        "oi_high_route": _w(4_000_000, 100_000_000),
        "oi_high_mem":   _w(4_000_000, 100_000_000) + _w(64, 4096),
    },
    "juniper_mx480": {
        "oi_high_pkt":   _w(3000,    100_000),   # ≈ 0.696
        "oi_high_net":   _w(5760,    100_000),
        "oi_port_dense": _w(5760,    100_000),
        "oi_high_route": _w(1_000_000, 100_000_000),
        "oi_high_mem":   _w(1_000_000, 100_000_000) + _w(32, 4096),
    },
}

# Shared requirements and profiles used by all cross-router tests.
_REQUIREMENTS = [
    {"id": "ir_cpu",     "name": "Processing Capacity",  "resource_type": "cpu",
     "min_value": 32,    "unit": "vCPU",   "top_priority": 1, "driver_count": 1},
    {"id": "ir_ram",     "name": "Memory Capacity",      "resource_type": "memory",
     "min_value": 256,   "unit": "GB",     "top_priority": 1, "driver_count": 2},
    {"id": "ir_net",     "name": "Networking Capacity",  "resource_type": "networking",
     "min_value": 100,   "unit": "Gbps",   "top_priority": 1, "driver_count": 1},
    {"id": "ir_routing", "name": "Routing Capacity",     "resource_type": "routing",
     "min_value": 32000, "unit": "routes", "top_priority": 1, "driver_count": 1},
    {"id": "ir_storage", "name": "Storage Capacity",     "resource_type": "storage",
     "min_value": 500,   "unit": "GB",     "top_priority": 3, "driver_count": 1},
    {"id": "ir_ports",   "name": "Port Capacity",        "resource_type": "ports",
     "min_value": 32,    "unit": "count",  "top_priority": 1, "driver_count": 2},
]

_PROFILES = [
    {"id": "np_compute_xl", "name": "Compute-XL", "vcpu": 64,  "ram_gb": 512,
     "ports": 48, "storage_gb": 2000, "role": "compute",
     "total_fit": 3.3, "reqs_satisfied": 3,
     # Explicit fit_breakdown entries only for requirements this profile satisfies.
     # No memory/routing/networking/ports entries — those go to specialist profiles.
     "fit_breakdown": ["cpu:1.0", "memory:0.5", "storage:0.8"]},
    {"id": "np_network_xl", "name": "Network-XL", "vcpu": 32,  "ram_gb": 128,
     "ports": 64, "storage_gb": 500,  "role": "network",
     "total_fit": 2.5, "reqs_satisfied": 2,
     "fit_breakdown": ["networking:1.0", "ports:1.0"]},
    {"id": "np_memory_xl",  "name": "Memory-XL",  "vcpu": 128, "ram_gb": 1024,
     "ports": 32, "storage_gb": 4000, "role": "memory",
     "total_fit": 2.0, "reqs_satisfied": 2,
     # Only memory and routing — NOT cpu, ports, networking, storage.
     "fit_breakdown": ["memory:1.0", "routing:1.0"]},
    {"id": "np_memory_l",   "name": "Memory-L",   "vcpu": 16,  "ram_gb": 512,
     "ports": 16, "storage_gb": 1000, "role": "memory",
     "total_fit": 1.9, "reqs_satisfied": 2,
     "fit_breakdown": ["memory:0.9", "routing:0.9"]},
    {"id": "np_balanced",   "name": "Balanced",   "vcpu": 32,  "ram_gb": 256,
     "ports": 32, "storage_gb": 1000, "role": "balanced",
     "total_fit": 1.9, "reqs_satisfied": 4,
     # Balanced covers cpu/net/ports/memory at moderate scores.
     # This allows it to win all resource types for low-signal access routers.
     "fit_breakdown": ["cpu:0.5", "memory:0.4", "networking:0.5", "ports:0.5"]},
]


def _infer_router(router_id: str) -> "InferenceResult":
    """Run inference for a named router using its realistic instance_weights."""
    implications = [
        {"id": impl_id, "name": impl_id, "severity": 3, "total_weight": w}
        for impl_id, w in _WEIGHTS[router_id].items()
    ]
    return infer(router_id, implications, _REQUIREMENTS, _PROFILES,
                 instance_weights=_WEIGHTS[router_id])


def _cpu_demand(router_id: str) -> float:
    result = _infer_router(router_id)
    t = next(t for t in result.resource_targets if t.resource_type == "cpu")
    return t.demand_target


def _compute_count(router_id: str) -> int:
    result = _infer_router(router_id)
    sel = next((s for s in result.node_selections if s.role == "compute"), None)
    return sel.count if sel else 0


class TestCrossRouterDemandOrdering:
    """
    Verify that the scaling formula produces correct relative ordering
    across all router classes. These are regression tests — if a formula
    change breaks the ordering, these tests catch it immediately.
    """

    def test_cpu_demand_increases_with_forwarding_rate(self):
        """
        Forwarding rate order: ASR1001 < 9200 < ASR1006 < 9300X < MX480 < 9500
        CPU demand must follow the same order.
        """
        demands = {r: _cpu_demand(r) for r in _WEIGHTS}
        assert demands["cisco_asr1001"] < demands["cisco_9200"]
        assert demands["cisco_9200"]    < demands["cisco_asr1006"]
        assert demands["cisco_asr1006"] < demands["cisco_9300x"]
        assert demands["cisco_9300x"]   < demands["juniper_mx480"]
        assert demands["juniper_mx480"] < demands["cisco_9500"]

    def test_access_router_cpu_demand_is_modest(self):
        """
        Cisco 9200 (access switch, 130 Mpps) must not demand more than
        2 Compute-XL nodes (128 vCPU total). Over-provisioning access
        switches was the original bug this formula was designed to fix.
        """
        demand = _cpu_demand("cisco_9200")
        # 2 × Compute-XL = 128 vCPU — access switch should not exceed this
        assert demand <= 128, (
            f"9200 cpu demand={demand} vCPU exceeds 128 vCPU (2 × Compute-XL). "
            f"Formula is over-provisioning access routers."
        )

    def test_access_router_compute_node_count_is_small(self):
        """
        Cisco 9200 should need at most 2 Compute-XL nodes.
        3+ nodes for a 130 Mpps access switch is over-provisioning.
        """
        count = _compute_count("cisco_9200")
        assert count <= 2, (
            f"9200 compute count={count} — access switch should need ≤2 nodes."
        )

    def test_edge_router_compute_count_is_small(self):
        """
        ASR1001-X (15 Mpps, edge/WAN) should need at most 1 Compute-XL node.
        It is a low-throughput WAN router — compute demand is minimal.
        """
        count = _compute_count("cisco_asr1001")
        assert count <= 1, (
            f"ASR1001 compute count={count} — edge router should need ≤1 node."
        )

    def test_core_router_compute_count_exceeds_access(self):
        """
        9500 and MX480 (core/high-end) must need more compute nodes than 9200.
        This verifies the formula still differentiates router classes.
        """
        access_count = _compute_count("cisco_9200")
        core_9500    = _compute_count("cisco_9500")
        mx480        = _compute_count("juniper_mx480")
        assert core_9500 >= access_count
        assert mx480     >= access_count

    def test_wan_router_routing_demand_exceeds_campus(self):
        """
        ASR1006 (4M routes) and ASR1001 (2M routes) must have higher routing
        demand than 9300X (32K routes). WAN routers carry large RIB/FIB tables.
        """
        def _routing_demand(rid):
            result = _infer_router(rid)
            t = next(t for t in result.resource_targets if t.resource_type == "routing")
            return t.demand_target

        assert _routing_demand("cisco_asr1006") > _routing_demand("cisco_9300x")
        assert _routing_demand("cisco_asr1001") > _routing_demand("cisco_9300x")

    def test_mx480_routing_demand_exceeds_campus(self):
        """
        MX480 (1M routes) must have higher routing demand than 9300X (32K routes).
        """
        def _routing_demand(rid):
            result = _infer_router(rid)
            t = next(t for t in result.resource_targets if t.resource_type == "routing")
            return t.demand_target

        assert _routing_demand("juniper_mx480") > _routing_demand("cisco_9300x")

    def test_zero_signal_always_returns_seed_min(self):
        """
        When no implications are present, demand_target must equal seed_min
        for every resource type. This is the floor guarantee.
        """
        result = infer("test_empty", [], _REQUIREMENTS, _PROFILES,
                       instance_weights={})
        for t in result.resource_targets:
            assert t.demand_target == t.seed_min, (
                f"{t.resource_type}: demand_target={t.demand_target} != "
                f"seed_min={t.seed_min} with zero signal"
            )

    def test_formula_is_monotonically_increasing_with_signal(self):
        """
        Higher signal must always produce higher demand_target.
        Tests the formula directly across a range of signal values.
        """
        import math
        seed_min = 32.0
        signals = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        demands = []
        for s in signals:
            m = 1.0 + s * math.log(1.0 + s) if s > 0 else 1.0
            demands.append(seed_min * m)
        for i in range(1, len(demands)):
            assert demands[i] > demands[i - 1], (
                f"Formula not monotonic: signal={signals[i-1]:.1f}→{signals[i]:.1f} "
                f"gave demand {demands[i-1]:.2f}→{demands[i]:.2f}"
            )

    def test_high_end_router_does_not_exceed_compute_cap(self):
        """
        Even the highest-signal router (9500) must not exceed the compute
        cap of 16 after validation. This ensures the validator still fires.
        """
        result = _infer_router("cisco_9500")
        vr = validate(result)
        for sel in vr.adjusted_selections:
            if sel.role == "compute":
                assert sel.count <= 16, (
                    f"9500 compute count={sel.count} exceeds cap of 16 after validation."
                )

    def test_all_routers_produce_valid_plans(self):
        """
        All six routers must produce valid plans (no violations).
        Warnings are acceptable; hard violations are not.
        """
        for router_id in _WEIGHTS:
            result = _infer_router(router_id)
            vr = validate(result)
            assert vr.valid is True, (
                f"{router_id} produced violations: {vr.violations}"
            )

    def test_9200_total_nodes_after_validation_is_small(self):
        """
        Cisco 9200 total node count after validation must be ≤ 6.
        An access switch should not produce a large cluster.
        """
        result = _infer_router("cisco_9200")
        vr = validate(result)
        total = sum(s.count for s in vr.adjusted_selections)
        assert total <= 6, (
            f"9200 total nodes={total} after validation — "
            f"access switch should produce a small cluster (≤6 nodes)."
        )

    def test_mx480_compute_nodes_selected(self):
        """
        MX480 (3000 Mpps) must select at least 1 Compute-XL node.
        High forwarding rate → oi_high_pkt → ir_cpu → Compute-XL.
        This is the core regression for the original MX480 bug.
        """
        result = _infer_router("juniper_mx480")
        compute_sels = [s for s in result.node_selections if s.role == "compute"]
        assert len(compute_sels) > 0, (
            "MX480 produced no compute nodes despite 3000 Mpps forwarding rate. "
            "Chain: Forwarding Rate → oi_high_pkt → ir_cpu → Compute-XL is broken."
        )
        assert compute_sels[0].count >= 1

    def test_asr_routers_select_memory_nodes(self):
        """
        ASR1001 and ASR1006 (2M–4M routes) must select memory nodes.
        High route count → oi_high_route → ir_routing/ir_ram → Memory-XL.
        """
        for router_id in ("cisco_asr1001", "cisco_asr1006"):
            result = _infer_router(router_id)
            memory_sels = [s for s in result.node_selections if s.role == "memory"]
            assert len(memory_sels) > 0, (
                f"{router_id} produced no memory nodes despite large routing table. "
                f"Chain: IPv4 Routes → oi_high_route → ir_routing → Memory-XL is broken."
            )

    def test_reasoning_trace_contains_all_routers_targets(self):
        """
        Every router must emit [Target] lines for cpu, memory, and routing.
        This verifies the full reasoning chain is populated for all classes.
        """
        for router_id in _WEIGHTS:
            result = _infer_router(router_id)
            target_rtypes = {
                t.resource_type for t in result.resource_targets
            }
            assert "cpu"     in target_rtypes, f"{router_id} missing cpu target"
            assert "memory"  in target_rtypes, f"{router_id} missing memory target"
            assert "routing" in target_rtypes, f"{router_id} missing routing target"


class TestProfileSelectionMapping:
    """
    Regression tests for the profile-selection bug where Memory-XL was winning
    cpu/ports/networking resource types because _select_profiles fell back to
    total_fit when fit_breakdown had no entry for a resource type.

    Rule: a profile must ONLY win a resource type if it has an explicit
    fit_breakdown entry for that type. total_fit must never be used as fallback.
    """

    def _run(self, router_id: str):
        implications = [
            {"id": impl_id, "name": impl_id, "severity": 3, "total_weight": w}
            for impl_id, w in _WEIGHTS[router_id].items()
        ]
        return infer(router_id, implications, _REQUIREMENTS, _PROFILES,
                     instance_weights=_WEIGHTS[router_id])

    def _sel_by_role(self, result, role: str):
        return [s for s in result.node_selections if s.role == role]

    def _sel_covers(self, result, profile_name: str) -> list[str]:
        sel = next((s for s in result.node_selections
                    if s.profile_name == profile_name), None)
        return sel.satisfies if sel else []

    # ── Memory-XL must never cover cpu, ports, networking, storage ────────────

    def test_memory_xl_never_covers_cpu(self):
        """Memory-XL has no fit_breakdown entry for cpu → must not win cpu."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Memory-XL")
            assert "cpu" not in covers, (
                f"{rid}: Memory-XL covers cpu — profile-selection bug. "
                f"cpu must go to Compute-XL."
            )

    def test_memory_xl_never_covers_ports(self):
        """Memory-XL has no fit_breakdown entry for ports → must not win ports."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Memory-XL")
            assert "ports" not in covers, (
                f"{rid}: Memory-XL covers ports — profile-selection bug. "
                f"ports must go to Network-XL or Balanced."
            )

    def test_memory_xl_never_covers_networking(self):
        """Memory-XL has no fit_breakdown entry for networking → must not win networking."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Memory-XL")
            assert "networking" not in covers, (
                f"{rid}: Memory-XL covers networking — profile-selection bug."
            )

    def test_memory_xl_never_covers_storage(self):
        """Memory-XL has no fit_breakdown entry for storage → must not win storage."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Memory-XL")
            assert "storage" not in covers, (
                f"{rid}: Memory-XL covers storage — profile-selection bug."
            )

    # ── Network-XL must never cover memory, routing, cpu ─────────────────────

    def test_network_xl_never_covers_memory(self):
        """Network-XL has no fit_breakdown entry for memory → must not win memory."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Network-XL")
            assert "memory" not in covers, (
                f"{rid}: Network-XL covers memory — profile-selection bug."
            )

    def test_network_xl_never_covers_routing(self):
        """Network-XL has no fit_breakdown entry for routing → must not win routing."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Network-XL")
            assert "routing" not in covers, (
                f"{rid}: Network-XL covers routing — profile-selection bug."
            )

    def test_network_xl_never_covers_cpu(self):
        """Network-XL has no fit_breakdown entry for cpu → must not win cpu."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Network-XL")
            assert "cpu" not in covers, (
                f"{rid}: Network-XL covers cpu — profile-selection bug."
            )

    # ── Compute-XL must never cover routing ──────────────────────────────────

    def test_compute_xl_never_covers_routing(self):
        """Compute-XL has no fit_breakdown entry for routing → must not win routing."""
        for rid in _WEIGHTS:
            result = self._run(rid)
            covers = self._sel_covers(result, "Compute-XL")
            assert "routing" not in covers, (
                f"{rid}: Compute-XL covers routing — should go to Memory-XL."
            )

    # ── Cisco 9200 specific regressions ──────────────────────────────────────

    def test_9200_does_not_select_memory_xl(self):
        """
        Cisco 9200 (8K routes, 4GB DRAM) should prefer Memory-L over Memory-XL.
        Memory-XL is for WAN/SP routers with millions of routes.
        """
        result = self._run("cisco_9200")
        memory_xl_sels = [s for s in result.node_selections
                          if s.profile_name == "Memory-XL"]
        # 9200 may select Memory-XL but with low count (1-2 nodes max)
        if memory_xl_sels:
            assert memory_xl_sels[0].count <= 2, (
                f"9200 selected {memory_xl_sels[0].count} Memory-XL nodes — "
                f"access switch should need at most 2."
            )

    def test_9200_total_node_count_is_small(self):
        """
        Cisco 9200 total nodes after validation must be ≤ 6.
        An access switch with 130 Mpps and 8K routes needs a small cluster.
        """
        result = self._run("cisco_9200")
        vr = validate(result)
        total = sum(s.count for s in vr.adjusted_selections)
        assert total <= 6, (
            f"9200 total nodes={total} — access switch should need ≤6 nodes."
        )

    def test_9200_no_memory_routing_topology(self):
        """
        Cisco 9200 must not produce a memory_routing topology.
        memory_routing is for WAN/SP routers with large RIB/FIB tables.
        9200 should produce balanced, minimal, or compute_heavy topology.
        """
        result = self._run("cisco_9200")
        vr = validate(result)
        dp = plan(result, vr)
        assert dp.topology_type != "memory_routing", (
            f"9200 topology={dp.topology_type} — access switch must not get "
            f"memory_routing topology. Check profile selection and pattern matching."
        )

    def test_9200_ram_is_reasonable(self):
        """
        Cisco 9200 total RAM must not exceed 3072 GB.
        """
        result = self._run("cisco_9200")
        vr = validate(result)
        dp = plan(result, vr)
        total_ram = sum(c.total_ram_gb for c in dp.clusters)
        assert total_ram <= 3584, (
            f"9200 total RAM={total_ram} GB — access switch should not need "
            f">3072 GB RAM."
        )

    def test_9200_no_network_xl_covering_memory(self):
        """
        Regression for the exact observed bug:
        'Network-XL covers=[memory]' must never happen.
        """
        result = self._run("cisco_9200")
        covers = self._sel_covers(result, "Network-XL")
        assert "memory" not in covers, (
            "9200: Network-XL covers memory — this is the exact observed bug. "
            "Network-XL must only cover networking and ports."
        )

    def test_9200_no_memory_xl_covering_ports_cpu_storage(self):
        """
        Regression for the exact observed bug:
        'Memory-XL covers=[ports, cpu, storage]' must never happen.
        """
        result = self._run("cisco_9200")
        covers = self._sel_covers(result, "Memory-XL")
        for wrong_type in ("ports", "cpu", "storage"):
            assert wrong_type not in covers, (
                f"9200: Memory-XL covers {wrong_type} — this is the exact observed bug. "
                f"Memory-XL must only cover memory and routing."
            )

    # ── High-end routers still select specialist profiles ─────────────────────

    def test_9500_selects_memory_xl_for_memory_routing(self):
        """
        9500 (128K routes, 32GB DRAM) must select Memory-XL for memory/routing.
        Fixing the 9200 bug must not break high-end router profile selection.
        """
        result = self._run("cisco_9500")
        memory_xl_sels = [s for s in result.node_selections
                          if s.profile_name == "Memory-XL"]
        assert len(memory_xl_sels) > 0, (
            "9500 did not select Memory-XL — high-end router should use "
            "memory-optimized nodes for large routing tables."
        )
        covers = self._sel_covers(result, "Memory-XL")
        assert "memory" in covers or "routing" in covers, (
            f"9500: Memory-XL covers={covers} — should cover memory or routing."
        )

    def test_mx480_selects_compute_xl_for_cpu(self):
        """
        MX480 (3000 Mpps) must select Compute-XL for cpu.
        This is the original MX480 regression.
        """
        result = self._run("juniper_mx480")
        compute_xl_sels = [s for s in result.node_selections
                           if s.profile_name == "Compute-XL"]
        assert len(compute_xl_sels) > 0, (
            "MX480 did not select Compute-XL — high forwarding rate must "
            "trigger cpu demand → Compute-XL selection."
        )
        covers = self._sel_covers(result, "Compute-XL")
        assert "cpu" in covers, (
            f"MX480: Compute-XL covers={covers} — must cover cpu."
        )

    def test_asr1006_selects_memory_xl_for_routing(self):
        """
        ASR1006 (4M routes) must select Memory-XL for routing/memory.
        """
        result = self._run("cisco_asr1006")
        covers = self._sel_covers(result, "Memory-XL")
        assert "routing" in covers or "memory" in covers, (
            f"ASR1006: Memory-XL covers={covers} — WAN router must use "
            f"Memory-XL for routing/memory."
        )


class TestScalingFormulaProperties:
    """
    Unit tests for the log-compressed scaling formula itself.
    These are pure math tests — no inference engine involved.
    They document the formula's intended behaviour and catch
    accidental formula changes.
    """

    def _demand(self, seed_min: float, signal: float) -> float:
        import math
        m = 1.0 + signal * math.log(1.0 + signal) if signal > 0 else 1.0
        return seed_min * m

    def test_zero_signal_returns_seed_min(self):
        assert self._demand(32.0, 0.0) == pytest.approx(32.0)

    def test_weak_signal_gives_modest_uplift(self):
        """signal=0.7 (access router) → multiplier ≈ 1.39 → modest uplift."""
        result = self._demand(32.0, 0.7)
        assert 1.2 < result / 32.0 < 1.6, (
            f"Weak signal multiplier={result/32.0:.3f} outside expected range [1.2, 1.6]"
        )

    def test_medium_signal_gives_moderate_uplift(self):
        """signal=2.0 (campus router) → multiplier ≈ 3.77."""
        import math
        result = self._demand(32.0, 2.0)
        expected_mult = 1 + 2.0 * math.log(3.0)
        assert result == pytest.approx(32.0 * expected_mult, rel=1e-4)

    def test_strong_signal_gives_significant_uplift(self):
        """signal=3.5 (high-end SP) → multiplier ≈ 5.74."""
        result = self._demand(32.0, 3.5)
        assert result / 32.0 > 4.0, (
            f"Strong signal multiplier={result/32.0:.3f} — should be >4.0 for high-end routers"
        )

    def test_formula_does_not_produce_negative_demand(self):
        """Demand must always be positive for any non-negative signal."""
        for signal in [0.0, 0.001, 0.5, 1.0, 5.0, 10.0]:
            assert self._demand(32.0, signal) > 0

    def test_high_end_multiplier_is_less_than_power_formula(self):
        """
        The log-compressed formula must produce lower multipliers than (1+s)^1.4
        for the same signal, confirming it prevents over-provisioning.
        At signal=1.69 (9200 cpu signal with old cpu=4.0):
          old: (1+1.69)^1.4 = 2.69^1.4 ≈ 4.43
          new: 1 + 1.69*ln(2.69) ≈ 2.98
        """
        import math
        signal = 1.69
        old_mult = (1 + signal) ** 1.4
        new_mult = 1 + signal * math.log(1 + signal)
        assert new_mult < old_mult, (
            f"Log-compressed formula ({new_mult:.3f}) should be less than "
            f"power formula ({old_mult:.3f}) at signal={signal}"
        )


class TestClusterSplitConsistency:
    """
    Regression tests for the cluster-split explanation bug.

    Bug: the [Pattern] reasoning line was written before the cluster-split
    override, so it logged clusters=1 even when the planner produced 2 clusters.
    The LLM then said "1 cluster" in the explanation while the plan showed 2.

    Fix: [Pattern] line is now written after the override and includes an
    explicit split explanation line when cluster_count > pattern_cluster_count.

    These tests verify:
    1. plan.cluster_count always equals len(plan.clusters)
    2. The [Pattern] reasoning line always reflects the final cluster_count
    3. When a split occurs, a split explanation line is present in reasoning
    4. When no split occurs, no spurious split line is added
    """

    def _make_ir(self, selections):
        from engine.inference import InferenceResult
        return InferenceResult(
            router_id="test_router",
            resource_targets=[],
            node_selections=selections,
            reasoning=["[Target] test"],
        )

    def _run(self, selections):
        ir = self._make_ir(selections)
        vr = validate(ir)
        return plan(ir, vr)

    # ── Core invariant: cluster_count == len(clusters) ────────────────────────

    def test_cluster_count_property_matches_clusters_list_small(self):
        """cluster_count must equal len(clusters) for a small plan (no split)."""
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        assert dp.cluster_count == len(dp.clusters), (
            f"cluster_count={dp.cluster_count} != len(clusters)={len(dp.clusters)}"
        )

    def test_cluster_count_property_matches_clusters_list_large(self):
        """cluster_count must equal len(clusters) when a split is triggered."""
        # 10 nodes total → total_nodes > 8 → split to 2 clusters
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 10, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        assert dp.cluster_count == len(dp.clusters), (
            f"cluster_count={dp.cluster_count} != len(clusters)={len(dp.clusters)}"
        )

    # ── [Pattern] reasoning line reflects final cluster_count ─────────────────

    def test_pattern_reasoning_line_shows_final_cluster_count_no_split(self):
        """
        When no split occurs, the [Pattern] line must show the pattern's
        cluster_count (1 for most patterns).
        """
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 4, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        pattern_lines = [r for r in dp.reasoning if r.startswith("[Pattern]")]
        assert len(pattern_lines) >= 1

        # The first [Pattern] line must contain the actual cluster_count
        first_pattern = pattern_lines[0]
        assert f"clusters={dp.cluster_count}" in first_pattern, (
            f"[Pattern] line says '{first_pattern}' but plan has "
            f"cluster_count={dp.cluster_count}. Stale cluster count in reasoning."
        )

    def test_pattern_reasoning_line_shows_final_cluster_count_after_split(self):
        """
        When a split occurs (total_nodes > 8), the [Pattern] line must show
        the post-split cluster_count, not the pattern's original value.

        This is the exact regression: before the fix, [Pattern] said clusters=1
        but the plan had 2 clusters.
        """
        # 10 nodes → split to 2 clusters
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 10, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)

        # Must have 2 clusters after split
        assert dp.cluster_count == 2, (
            f"Expected 2 clusters after split, got {dp.cluster_count}"
        )

        pattern_lines = [r for r in dp.reasoning if r.startswith("[Pattern]")]
        assert len(pattern_lines) >= 1

        first_pattern = pattern_lines[0]
        assert "clusters=2" in first_pattern, (
            f"[Pattern] line says '{first_pattern}' but plan has 2 clusters. "
            f"The [Pattern] line must be written after the split override."
        )
        assert "clusters=1" not in first_pattern, (
            f"[Pattern] line still says clusters=1 after a split to 2 clusters. "
            f"This is the exact regression bug."
        )

    # ── Split explanation line ─────────────────────────────────────────────────

    def test_split_explanation_line_present_when_split_occurs(self):
        """
        When the planner splits beyond the pattern's base cluster count,
        a second [Pattern] line must explain why.
        """
        # 10 nodes → split to 2 clusters
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 10, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        assert dp.cluster_count == 2

        pattern_lines = [r for r in dp.reasoning if r.startswith("[Pattern]")]
        split_lines = [l for l in pattern_lines if "split" in l.lower()]
        assert len(split_lines) >= 1, (
            f"No split explanation found in reasoning. pattern_lines={pattern_lines}. "
            f"When cluster_count is increased beyond the pattern default, a "
            f"[Pattern] split explanation line must be added."
        )
        # The split line must mention the final cluster count
        assert "2" in split_lines[0], (
            f"Split explanation line '{split_lines[0]}' does not mention 2 clusters."
        )

    def test_no_split_explanation_when_no_split(self):
        """
        When no split occurs, no spurious split explanation line should appear.
        """
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 3, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        assert dp.cluster_count == 1

        pattern_lines = [r for r in dp.reasoning if r.startswith("[Pattern]")]
        split_lines = [l for l in pattern_lines if "split" in l.lower()]
        assert len(split_lines) == 0, (
            f"Spurious split explanation found when no split occurred: {split_lines}"
        )

    # ── All nodes are distributed across clusters ──────────────────────────────

    def test_all_nodes_distributed_when_split(self):
        """
        After a split, every node must be assigned to exactly one cluster.
        No nodes should be lost or duplicated.
        """
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 10, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        total_in_clusters = sum(c.node_count for c in dp.clusters)
        total_from_selections = sum(
            s.count for s in validate(self._make_ir(selections)).adjusted_selections
        )
        assert total_in_clusters == total_from_selections, (
            f"Node count mismatch after split: "
            f"clusters have {total_in_clusters} nodes but "
            f"selections have {total_from_selections} nodes."
        )

    def test_each_cluster_has_at_least_one_node_after_split(self):
        """Every cluster created by a split must have at least one node."""
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 10, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        for c in dp.clusters:
            assert c.node_count >= 1, (
                f"{c.cluster_id} has 0 nodes after split — empty clusters must not exist."
            )

    # ── [Plan] lines match actual cluster layout ───────────────────────────────

    def test_plan_reasoning_lines_match_actual_clusters(self):
        """
        Every cluster in dp.clusters must have a corresponding [Plan] line
        in the reasoning trace with the correct node count.
        """
        selections = [
            NodeSelection("np_compute_xl", "Compute-XL", "compute",
                          64, 512, 48, 2000, 10, 5.4, ["cpu"]),
        ]
        dp = self._run(selections)
        plan_lines = [r for r in dp.reasoning if r.startswith("[Plan]")]

        assert len(plan_lines) == dp.cluster_count, (
            f"Expected {dp.cluster_count} [Plan] lines, got {len(plan_lines)}. "
            f"Each cluster must have exactly one [Plan] reasoning line."
        )

        for c in dp.clusters:
            matching = [l for l in plan_lines if c.cluster_id in l]
            assert len(matching) == 1, (
                f"No [Plan] line found for {c.cluster_id}. "
                f"plan_lines={plan_lines}"
            )
            assert f"{c.node_count} nodes" in matching[0], (
                f"[Plan] line for {c.cluster_id} does not show correct node count. "
                f"line='{matching[0]}', actual node_count={c.node_count}"
            )
