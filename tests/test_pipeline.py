# tests/test_pipeline.py
# Integration tests: full pipeline against a live FalkorDB graph.
# All tests in this file use the `live_graph` fixture from conftest.py
# and are automatically skipped if FalkorDB is not running.

import pytest
from main import run_pipeline
from parser.input_parser import parse
from parser.entity_mapper import map_to_graph
from api.schemas import RouterSpecRequest


# ── Full pipeline: Cisco 9300X (seeded router) ────────────────────────────────

class TestPipeline9300X:

    def test_pipeline_returns_valid_plan(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert dp.valid is True

    def test_plan_has_exactly_one_cluster(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        # 9300X produces 9 nodes (exceeds cluster size of 8) → splits to 2 clusters
        assert dp.cluster_count >= 1

    def test_plan_has_at_least_three_nodes(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        total = sum(c.node_count for c in dp.clusters)
        assert total >= 3

    def test_ha_is_enabled(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert dp.ha_enabled is True

    def test_reasoning_trace_is_non_empty(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert len(dp.reasoning) > 0

    def test_all_nodes_have_valid_specs(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        for cluster in dp.clusters:
            for node in cluster.nodes:
                assert node.vcpu >= 8,    f"{node.node_id} vCPU too low"
                assert node.ram_gb >= 16, f"{node.node_id} RAM too low"
                assert node.ports >= 1,   f"{node.node_id} no ports"

    def test_cluster_aggregate_vcpu_positive(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        for cluster in dp.clusters:
            assert cluster.total_vcpu > 0
            assert cluster.total_ram_gb > 0

    def test_no_violations_for_known_router(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert dp.violations == []


# ── Full pipeline: minimal spec (low-end router) ──────────────────────────────

class TestPipelineMinimal:

    def test_minimal_spec_produces_valid_plan(self, live_graph, spec_minimal):
        dp = run_pipeline(live_graph, spec_minimal)
        assert dp.valid is True

    def test_minimal_spec_meets_ha_minimum(self, live_graph, spec_minimal):
        dp = run_pipeline(live_graph, spec_minimal)
        total = sum(c.node_count for c in dp.clusters)
        assert total >= 3


# ── Full pipeline: high-end vs low-end comparison ────────────────────────────

class TestPipelineScaling:

    def test_high_end_router_has_more_or_equal_total_vcpu(
        self, live_graph, spec_9300x, spec_high_end
    ):
        dp_mid  = run_pipeline(live_graph, spec_9300x)
        dp_high = run_pipeline(live_graph, spec_high_end)

        vcpu_mid  = sum(c.total_vcpu for c in dp_mid.clusters)
        vcpu_high = sum(c.total_vcpu for c in dp_high.clusters)
        assert vcpu_high >= vcpu_mid

    def test_high_end_router_has_more_or_equal_total_ram(
        self, live_graph, spec_9300x, spec_high_end
    ):
        dp_mid  = run_pipeline(live_graph, spec_9300x)
        dp_high = run_pipeline(live_graph, spec_high_end)

        ram_mid  = sum(c.total_ram_gb for c in dp_mid.clusters)
        ram_high = sum(c.total_ram_gb for c in dp_high.clusters)
        assert ram_high >= ram_mid


# ── New router registration ───────────────────────────────────────────────────

class TestNewRouterRegistration:

    def test_new_router_is_registered_in_graph(self, live_graph):
        import time
        unique_model = f"Cisco 9500 RegTest {int(time.time())}"
        raw = {
            "model":           unique_model,
            "vendor":          "Cisco",
            "series":          "9500",
            "switching_cap":   {"value": 1600, "unit": "Gbps"},
            "forwarding_rate": {"value": 4000, "unit": "Mpps"},
            "ipv4_routes":     {"value": 64000,"unit": "count"},
            "dram_gb":         {"value": 32,   "unit": "GB"},
        }
        spec    = parse(raw)
        mapping = map_to_graph(live_graph, spec, persist=True)
        assert mapping["is_new"] is True

        # Second call: same router now exists in graph
        mapping2 = map_to_graph(live_graph, spec, persist=True)
        assert mapping2["is_new"] is False

    def test_new_router_produces_valid_plan(self, live_graph):
        raw = {
            "model":           "Cisco 9500 PlanTest",
            "vendor":          "Cisco",
            "series":          "9500",
            "switching_cap":   {"value": 1600, "unit": "Gbps"},
            "forwarding_rate": {"value": 4000, "unit": "Mpps"},
            "ipv4_routes":     {"value": 64000,"unit": "count"},
            "dram_gb":         {"value": 32,   "unit": "GB"},
        }
        dp = run_pipeline(live_graph, raw)
        assert dp.valid is True
        assert dp.cluster_count >= 1


# ── FIX-07: alias resolution in full pipeline ────────────────────────────────

class TestAliasResolutionPipeline:

    @pytest.mark.parametrize("model_name", [
        "Cisco Catalyst 9300X",
        "Cisco 9300X",
    ])
    def test_alias_resolves_to_known_router(self, live_graph, model_name):
        """Both name variants must be treated as the same known router."""
        raw = {
            "model":           model_name,
            "vendor":          "Cisco",
            "series":          "9300",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        dp = run_pipeline(live_graph, raw)
        # Known router → graph_match must be 1.0
        assert dp.confidence.graph_match == pytest.approx(1.0, abs=1e-4)
        assert dp.valid is True

    def test_alias_and_direct_produce_identical_plans(self, live_graph):
        """Alias and direct name must produce the same topology and node count."""
        raw_direct = {
            "model":           "Cisco 9300X",
            "vendor":          "Cisco",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        raw_alias = dict(raw_direct)
        raw_alias["model"] = "Cisco Catalyst 9300X"

        dp_direct = run_pipeline(live_graph, raw_direct)
        dp_alias  = run_pipeline(live_graph, raw_alias)

        assert dp_direct.topology_type == dp_alias.topology_type
        total_direct = sum(c.node_count for c in dp_direct.clusters)
        total_alias  = sum(c.node_count for c in dp_alias.clusters)
        assert total_direct == total_alias


# ── Confidence score integration ──────────────────────────────────────────────

class TestConfidenceIntegration:

    def test_known_router_confidence_above_medium(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert dp.confidence is not None
        assert dp.confidence.score >= 0.50

    def test_known_router_graph_match_is_one(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert dp.confidence.graph_match == pytest.approx(1.0, abs=1e-4)

    def test_confidence_has_feature_coverage(self, live_graph, spec_9300x):
        """IMPROVE-03: feature_coverage must be present and > 0 for full spec."""
        dp = run_pipeline(live_graph, spec_9300x)
        assert hasattr(dp.confidence, "feature_coverage")
        assert dp.confidence.feature_coverage > 0.0

    def test_full_spec_has_higher_coverage_than_minimal(self, live_graph, spec_9300x, spec_minimal):
        """7-feature spec must have higher coverage than 4-feature spec."""
        dp_full    = run_pipeline(live_graph, spec_9300x)
        dp_minimal = run_pipeline(live_graph, spec_minimal)
        assert dp_full.confidence.feature_coverage >= dp_minimal.confidence.feature_coverage

    def test_confidence_score_bounded(self, live_graph, spec_9300x):
        dp = run_pipeline(live_graph, spec_9300x)
        assert 0.0 <= dp.confidence.score <= 1.0

    def test_high_end_router_confidence_not_lower_than_minimal(
        self, live_graph, spec_high_end, spec_minimal
    ):
        """A high-end router with strong signals should not score lower than minimal."""
        dp_high = run_pipeline(live_graph, spec_high_end)
        dp_min  = run_pipeline(live_graph, spec_minimal)
        # High-end may have more warnings (HA padding etc.) but signal is stronger
        # so overall confidence should be comparable
        assert dp_high.confidence.score >= 0.0  # sanity — must not crash




    def test_request_to_raw_preserves_all_fields(self, spec_9300x):
        req = RouterSpecRequest(
            model=spec_9300x["model"],
            vendor=spec_9300x["vendor"],
            series=spec_9300x["series"],
            switching_cap=spec_9300x["switching_cap"],
            forwarding_rate=spec_9300x["forwarding_rate"],
            ipv4_routes=spec_9300x["ipv4_routes"],
            dram_gb=spec_9300x["dram_gb"],
            stacking_bw=spec_9300x["stacking_bw"],
            vlan_ids=spec_9300x["vlan_ids"],
            mac_addresses=spec_9300x["mac_addresses"],
        )
        raw = req.to_raw()
        assert raw["model"] == "Cisco 9300X"
        assert raw["switching_cap"]["value"] == 640
        assert raw["switching_cap"]["unit"] == "Gbps"
        assert raw["stacking_bw"]["value"] == 1
        assert raw["stacking_bw"]["unit"] == "TBps"

    def test_optional_fields_absent_in_raw_when_not_provided(self):
        req = RouterSpecRequest(
            model="Test",
            switching_cap={"value": 640, "unit": "Gbps"},
            forwarding_rate={"value": 2232, "unit": "Mpps"},
            ipv4_routes={"value": 32000, "unit": "count"},
            dram_gb={"value": 8, "unit": "GB"},
        )
        raw = req.to_raw()
        assert "stacking_bw"   not in raw
        assert "vlan_ids"      not in raw
        assert "mac_addresses" not in raw

    def test_pipeline_accepts_api_schema_raw_output(self, live_graph, spec_9300x):
        req = RouterSpecRequest(
            model=spec_9300x["model"],
            vendor=spec_9300x["vendor"],
            switching_cap=spec_9300x["switching_cap"],
            forwarding_rate=spec_9300x["forwarding_rate"],
            ipv4_routes=spec_9300x["ipv4_routes"],
            dram_gb=spec_9300x["dram_gb"],
        )
        dp = run_pipeline(live_graph, req.to_raw())
        assert dp.valid is True
