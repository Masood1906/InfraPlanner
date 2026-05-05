# tests/test_data_quality.py
# Tests for the data quality gate in main.py.
# Covers _compute_data_quality and the full pipeline short-circuit.
# No graph dependency — mapping dicts are constructed directly.

import pytest
from parser.input_parser import parse


def _mapping(similarity: float, similar_to: str | None = "cisco_9300x") -> dict:
    """Build a minimal mapping dict as returned by map_to_graph."""
    return {
        "router_id":        "test_router",
        "is_new":           True,
        "is_similar":       similar_to is not None,
        "similar_to":       similar_to,
        "similarity_score": similarity,
        "implied_weights":  {},
        "warnings":         [],
    }


def _spec(switching_cap=640, forwarding_rate=2232, ipv4_routes=32000, dram_gb=8,
          model="Test Router"):
    return parse({
        "model":           model,
        "vendor":          "TestCo",
        "series":          "TX",
        "switching_cap":   {"value": switching_cap,   "unit": "Gbps"},
        "forwarding_rate": {"value": forwarding_rate, "unit": "Mpps"},
        "ipv4_routes":     {"value": ipv4_routes,     "unit": "count"},
        "dram_gb":         {"value": dram_gb,         "unit": "GB"},
    })


# Import the gate functions directly
from main import _compute_data_quality, _DATA_QUALITY_THRESHOLD


class TestComputeDataQuality:

    # ── Score calculation ─────────────────────────────────────────────────────

    def test_known_router_all_in_range_scores_high(self):
        score, reason = _compute_data_quality(_mapping(1.0, None), _spec())
        assert score >= 0.90
        assert reason == ""

    def test_unknown_router_zero_similarity_all_in_range_scores_half(self):
        # sim=0.0 → sim_score=0.0, feature_quality=1.0 → score=0.5
        score, reason = _compute_data_quality(_mapping(0.0, None), _spec())
        assert score == pytest.approx(0.5, abs=0.01)

    def test_unknown_router_zero_similarity_all_below_min_scores_zero(self):
        # sim=0.0, all 4 features below reference min → feature_quality=0.0 → score=0.0
        # dram_gb=3 is below the reference minimum of 4.0
        spec = _spec(switching_cap=1, forwarding_rate=2, ipv4_routes=6, dram_gb=3)
        score, reason = _compute_data_quality(_mapping(0.0, None), spec)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_partial_similarity_partial_features_scores_midrange(self):
        # sim=0.22, 2/4 features in range → score = 0.5*0.22 + 0.5*0.5 = 0.36
        # ipv4_routes=6 < 8000 min, dram_gb=3 < 4.0 min → 2 below, 2 in range
        spec = _spec(switching_cap=640, forwarding_rate=2232,
                     ipv4_routes=6, dram_gb=3)
        score, _ = _compute_data_quality(_mapping(0.22), spec)
        assert 0.30 <= score <= 0.45

    def test_score_is_between_zero_and_one(self):
        for sim in [0.0, 0.22, 0.5, 0.75, 1.0]:
            score, _ = _compute_data_quality(_mapping(sim), _spec())
            assert 0.0 <= score <= 1.0

    # ── Threshold gate ────────────────────────────────────────────────────────

    def test_known_cisco_passes_gate(self):
        score, reason = _compute_data_quality(_mapping(1.0, None), _spec())
        assert score >= _DATA_QUALITY_THRESHOLD
        assert reason == ""

    def test_juniper_mx480_realistic_passes_gate(self):
        """Unknown router with realistic specs and some similarity must pass."""
        spec = _spec(switching_cap=5760, forwarding_rate=3000,
                     ipv4_routes=1000000, dram_gb=32, model="Juniper MX480")
        # Juniper gets ~0.75 similarity after vendor penalty
        score, reason = _compute_data_quality(_mapping(0.75), spec)
        assert score >= _DATA_QUALITY_THRESHOLD, (
            f"Juniper MX480 with realistic specs should pass gate. score={score}"
        )

    def test_samsung_zero_similarity_fails_gate(self):
        """0% similarity with all features below min → score=0.0, fails gate."""
        spec = _spec(switching_cap=1, forwarding_rate=2,
                     ipv4_routes=6, dram_gb=3, model="Test Router")
        score, reason = _compute_data_quality(_mapping(0.0, None), spec)
        assert score < _DATA_QUALITY_THRESHOLD
        assert reason != ""

    def test_all_features_below_min_fails_gate(self):
        spec = _spec(switching_cap=1, forwarding_rate=2, ipv4_routes=6, dram_gb=3)
        score, reason = _compute_data_quality(_mapping(0.22), spec)
        assert score < _DATA_QUALITY_THRESHOLD

    def test_zero_similarity_zero_features_fails_gate(self):
        spec = _spec(switching_cap=1, forwarding_rate=2, ipv4_routes=6, dram_gb=3)
        score, reason = _compute_data_quality(_mapping(0.0, None), spec)
        assert score < _DATA_QUALITY_THRESHOLD

    # ── Reason message quality ────────────────────────────────────────────────

    def test_reason_mentions_zero_similarity(self):
        # Use all-below-min spec so score < threshold and reason is populated
        spec = _spec(switching_cap=1, forwarding_rate=2, ipv4_routes=6, dram_gb=3)
        _, reason = _compute_data_quality(_mapping(0.0, None), spec)
        assert "0%" in reason or "no similar" in reason.lower()

    def test_reason_mentions_below_minimum_features(self):
        spec = _spec(switching_cap=1, forwarding_rate=2, ipv4_routes=6, dram_gb=3)
        _, reason = _compute_data_quality(_mapping(0.22), spec)
        assert "below" in reason.lower() or "minimum" in reason.lower()

    def test_reason_is_empty_when_gate_passes(self):
        score, reason = _compute_data_quality(_mapping(1.0, None), _spec())
        assert score >= _DATA_QUALITY_THRESHOLD
        assert reason == ""


class TestPipelineShortCircuit:
    """
    Integration tests: verify that run_pipeline returns an empty plan
    (needs_review) for low-quality inputs without running inference.
    Uses a mock graph so no FalkorDB connection is needed.
    """

    def _mock_graph(self):
        from unittest.mock import MagicMock
        g = MagicMock()
        # _router_exists → False (unknown router)
        g.query.return_value = MagicMock(result_set=[])
        return g

    def test_samsung_zero_similarity_returns_needs_review(self):
        from unittest.mock import patch, MagicMock
        from main import run_pipeline
        from parser.agentic_validator import AgenticVerdict

        raw = {
            "model":           "Test Router XYZ",
            "vendor":          "TestCo",
            "series":          "",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }

        with patch("main.validate_spec"), \
             patch("main.check_router", return_value=AgenticVerdict.passthrough()), \
             patch("main.map_to_graph", return_value={
                 "router_id": "test_router_xyz", "is_new": True, "is_similar": False,
                 "similar_to": None, "similarity_score": 0.0,
                 "implied_weights": {}, "warnings": [],
             }):
            # With similarity=0.0 and all features in range, score=0.5 passes gate.
            # To force needs_review we need feature_quality=0 too.
            # Patch _compute_data_quality directly to return below-threshold score.
            with patch("main._compute_data_quality", return_value=(0.1, "test reason")):
                dp = run_pipeline(self._mock_graph(), raw)

        assert dp.plan_status == "needs_review"
        assert dp.cluster_count == 0
        assert dp.clusters == []
        assert dp.ha_enabled is False
        assert dp.topology_type == ""
        assert dp.plan_status_reason != ""

    def test_known_cisco_returns_ok_status(self):
        from unittest.mock import patch, MagicMock
        from main import run_pipeline

        raw = {
            "model":           "Cisco 9300X",
            "vendor":          "Cisco",
            "series":          "9300",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }

        # Known router: similarity=1.0, all features in range → gate passes
        with patch("main.validate_spec"), \
             patch("main.map_to_graph", return_value={
                 "router_id": "cisco_9300x", "is_new": False, "is_similar": False,
                 "similar_to": None, "similarity_score": 1.0,
                 "implied_weights": {}, "warnings": [],
             }), \
             patch("main.get_implications_for_router", return_value=[]), \
             patch("main.build_implications_from_weights", return_value=[]), \
             patch("main.get_requirements_for_implications", return_value=[]), \
             patch("main.get_node_profiles_for_requirements", return_value=[]), \
             patch("main.infer") as mock_infer, \
             patch("main.validate") as mock_validate, \
             patch("main.plan") as mock_plan, \
             patch("main.explain", return_value=""), \
             patch("main.explain_simple", return_value=""):

            from engine.inference import InferenceResult
            from engine.constraint_validator import ValidationResult
            from engine.deployment_planner import DeploymentPlan, ClusterSpec

            mock_infer.return_value = InferenceResult(
                router_id="cisco_9300x",
                resource_targets=[], node_selections=[], reasoning=[],
            )
            mock_validate.return_value = ValidationResult(
                valid=True, violations=[], warnings=[], adjusted_selections=[],
            )
            dp_mock = DeploymentPlan(
                router_id="cisco_9300x", clusters=[
                    ClusterSpec(cluster_id="cluster_1", topology_type="high_performance")
                ],
                topology_type="high_performance", ha_enabled=True,
                reasoning=[], warnings=[], violations=[], valid=True,
            )
            mock_plan.return_value = dp_mock

            dp = run_pipeline(self._mock_graph(), raw)

        assert dp.plan_status == "ok"
        assert dp.cluster_count >= 1

    def test_juniper_mx480_realistic_returns_ok_status(self):
        """Unknown but realistic router with sufficient similarity must pass gate."""
        from unittest.mock import patch, MagicMock
        from main import run_pipeline

        raw = {
            "model":           "Juniper MX480",
            "vendor":          "Juniper",
            "series":          "MX",
            "switching_cap":   {"value": 5760,    "unit": "Gbps"},
            "forwarding_rate": {"value": 3000,    "unit": "Mpps"},
            "ipv4_routes":     {"value": 1000000, "unit": "count"},
            "dram_gb":         {"value": 32,      "unit": "GB"},
        }

        with patch("main.validate_spec"), \
             patch("main.map_to_graph", return_value={
                 "router_id": "juniper_mx480", "is_new": True, "is_similar": True,
                 "similar_to": "cisco_9500", "similarity_score": 0.75,
                 "implied_weights": {}, "warnings": [],
             }), \
             patch("main.get_implications_for_router", return_value=[]), \
             patch("main.build_implications_from_weights", return_value=[]), \
             patch("main.get_requirements_for_implications", return_value=[]), \
             patch("main.get_node_profiles_for_requirements", return_value=[]), \
             patch("main.infer") as mock_infer, \
             patch("main.validate") as mock_validate, \
             patch("main.plan") as mock_plan, \
             patch("main.explain", return_value=""), \
             patch("main.explain_simple", return_value=""):

            from engine.inference import InferenceResult
            from engine.constraint_validator import ValidationResult
            from engine.deployment_planner import DeploymentPlan, ClusterSpec

            mock_infer.return_value = InferenceResult(
                router_id="juniper_mx480",
                resource_targets=[], node_selections=[], reasoning=[],
            )
            mock_validate.return_value = ValidationResult(
                valid=True, violations=[], warnings=[], adjusted_selections=[],
            )
            dp_mock = DeploymentPlan(
                router_id="juniper_mx480", clusters=[
                    ClusterSpec(cluster_id="cluster_1", topology_type="high_performance")
                ],
                topology_type="high_performance", ha_enabled=True,
                reasoning=[], warnings=[], violations=[], valid=True,
            )
            mock_plan.return_value = dp_mock

            dp = run_pipeline(self._mock_graph(), raw)

        assert dp.plan_status == "ok", (
            f"Juniper MX480 with realistic specs should produce a plan. "
            f"Got plan_status={dp.plan_status}, reason={dp.plan_status_reason}"
        )

    def test_needs_review_plan_has_empty_clusters(self):
        """A needs_review plan must always have cluster_count=0 and clusters=[]."""
        from unittest.mock import patch
        from main import run_pipeline
        from parser.agentic_validator import AgenticVerdict

        raw = {
            "model":           "Test Router XYZ",
            "vendor":          "TestCo",
            "series":          "",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }

        with patch("main.validate_spec"), \
             patch("main.check_router", return_value=AgenticVerdict.passthrough()), \
             patch("main.map_to_graph", return_value={
                 "router_id": "test_router_xyz", "is_new": True, "is_similar": False,
                 "similar_to": None, "similarity_score": 0.0,
                 "implied_weights": {}, "warnings": [],
             }), \
             patch("main._compute_data_quality", return_value=(0.1, "test reason")):
            dp = run_pipeline(self._mock_graph(), raw)

        assert dp.plan_status == "needs_review"
        assert dp.clusters == []
        assert dp.cluster_count == 0
        assert dp.valid is False
