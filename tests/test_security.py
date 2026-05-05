# tests/test_security.py
# Tests for FIX-01 (Cypher injection), FIX-02 (admin auth),
# and FIX-06 (cosine similarity zero-imputation).
# No live graph required for injection and similarity tests.
# Auth tests use FastAPI TestClient with a mock graph.

import math
import pytest
from unittest.mock import MagicMock, patch
from parser.entity_mapper import _cosine_similarity


# ── FIX-01: Cypher injection via _cosine_similarity is not applicable here,
#    but we verify the query functions accept params without raising.
#    Full injection safety is verified in test_pipeline.py (live graph).

class TestCypherParamFunctions:

    def test_get_implications_accepts_clean_router_id(self):
        """Parameterized query must not raise on a normal router_id."""
        from graph.queries import get_implications_for_router
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        result = get_implications_for_router(mock_graph, "cisco_9300x")
        assert result == []
        # Verify params dict was passed, not an f-string
        call_args = mock_graph.query.call_args
        assert call_args[0][1] == {"router_id": "cisco_9300x"}

    def test_get_implications_passes_router_id_as_param_not_fstring(self):
        """The query string must NOT contain the router_id value inline."""
        from graph.queries import get_implications_for_router
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        malicious_id = "x'}) MATCH (n) DETACH DELETE n //"
        get_implications_for_router(mock_graph, malicious_id)
        query_string = mock_graph.query.call_args[0][0]
        assert malicious_id not in query_string

    def test_get_requirements_passes_ids_as_param_list(self):
        """ids must be passed as a list param, not interpolated into the query."""
        from graph.queries import get_requirements_for_implications
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        ids = ["oi_high_pkt", "oi_high_net"]
        get_requirements_for_implications(mock_graph, ids)
        call_args = mock_graph.query.call_args
        assert call_args[0][1] == {"ids": ids}
        query_string = call_args[0][0]
        assert "oi_high_pkt" not in query_string

    def test_get_requirements_returns_empty_for_empty_ids(self):
        """Empty implication_ids must short-circuit without querying the graph."""
        from graph.queries import get_requirements_for_implications
        mock_graph = MagicMock()
        result = get_requirements_for_implications(mock_graph, [])
        assert result == []
        mock_graph.query.assert_not_called()

    def test_get_profiles_returns_empty_for_empty_ids(self):
        """Empty requirement_ids must short-circuit without querying the graph."""
        from graph.queries import get_node_profiles_for_requirements
        mock_graph = MagicMock()
        result = get_node_profiles_for_requirements(mock_graph, [])
        assert result == []
        mock_graph.query.assert_not_called()

    def test_get_profiles_passes_ids_as_param_list(self):
        from graph.queries import get_node_profiles_for_requirements
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        ids = ["ir_cpu", "ir_ram"]
        get_node_profiles_for_requirements(mock_graph, ids)
        call_args = mock_graph.query.call_args
        assert call_args[0][1] == {"ids": ids}

    def test_get_base_weights_passes_router_id_as_param(self):
        # get_base_weights_for_router was removed — this test is no longer applicable
        pass

    def test_router_exists_passes_router_id_as_param(self):
        from parser.entity_mapper import _router_exists
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        _router_exists(mock_graph, "cisco_9300x")
        call_args = mock_graph.query.call_args
        assert call_args[0][1] == {"router_id": "cisco_9300x"}

    def test_router_exists_malicious_id_not_in_query_string(self):
        from parser.entity_mapper import _router_exists
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        malicious = "x'}) DETACH DELETE (n) //"
        _router_exists(mock_graph, malicious)
        query_string = mock_graph.query.call_args[0][0]
        assert malicious not in query_string

    def test_create_router_passes_all_fields_as_params(self):
        from parser.entity_mapper import _create_router
        from parser.input_parser import ParsedSpec
        mock_graph = MagicMock()
        spec = ParsedSpec(
            router_id="test_router",
            model="Test Router",
            vendor="TestCo",
            series="TX",
        )
        _create_router(mock_graph, spec)
        params = mock_graph.query.call_args[0][1]
        assert params["router_id"] == "test_router"
        assert params["name"]      == "Test Router"
        assert params["vendor"]    == "TestCo"
        assert params["series"]    == "TX"
        query_string = mock_graph.query.call_args[0][0]
        assert "Test Router" not in query_string


# ── FIX-02: Admin endpoint authentication ─────────────────────────────────────

class TestAdminAuth:

    def _make_client(self, monkeypatch, api_key="test-secret-key"):
        """Build a TestClient with a mock graph and the given API key set."""
        from fastapi.testclient import TestClient
        from api.app import create_app

        monkeypatch.setenv("API_SECRET_KEY", api_key)

        mock_graph = MagicMock()
        # _router_exists → returns False (unknown router)
        mock_graph.query.return_value = MagicMock(result_set=[])

        app = create_app()
        app.state.graph = mock_graph
        return TestClient(app, raise_server_exceptions=False)

    def _valid_body(self):
        return {
            "model":           "Test Router",
            "vendor":          "TestCo",
            "series":          "TX",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }

    def test_admin_endpoint_rejects_missing_api_key(self, monkeypatch):
        client = self._make_client(monkeypatch)
        resp = client.post("/api/v1/admin/routers", json=self._valid_body())
        assert resp.status_code == 401

    def test_admin_endpoint_rejects_wrong_api_key(self, monkeypatch):
        client = self._make_client(monkeypatch)
        resp = client.post(
            "/api/v1/admin/routers",
            json=self._valid_body(),
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_admin_endpoint_rejects_empty_api_key(self, monkeypatch):
        client = self._make_client(monkeypatch)
        resp = client.post(
            "/api/v1/admin/routers",
            json=self._valid_body(),
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401

    def test_plan_endpoint_does_not_require_api_key(self, monkeypatch):
        """POST /plan must remain publicly accessible."""
        client = self._make_client(monkeypatch)
        resp = client.post("/api/v1/plan", json=self._valid_body())
        # 401 is the only unacceptable status — 200, 422, 500 are all fine here
        assert resp.status_code != 401

    def test_auth_disabled_when_no_key_configured(self, monkeypatch):
        """When API_SECRET_KEY is empty, auth is disabled and admin is open."""
        from fastapi.testclient import TestClient
        from api.app import create_app

        monkeypatch.setenv("API_SECRET_KEY", "")
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        app = create_app()
        app.state.graph = mock_graph
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/admin/routers", json=self._valid_body())
        assert resp.status_code != 401


# ── FIX-06: Cosine similarity zero-imputation ─────────────────────────────────

class TestCosineSimilarity:

    def test_identical_full_vectors_score_one(self):
        vec = {"a": 0.5, "b": 0.7, "c": 0.3}
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_score_zero(self):
        vec_a = {"a": 1.0, "b": 0.0}
        vec_b = {"a": 0.0, "b": 1.0}
        assert _cosine_similarity(vec_a, vec_b) == pytest.approx(0.0, abs=1e-6)

    def test_empty_vectors_return_zero(self):
        assert _cosine_similarity({}, {}) == 0.0

    def test_one_empty_vector_returns_zero(self):
        assert _cosine_similarity({"a": 1.0}, {}) == 0.0
        assert _cosine_similarity({}, {"a": 1.0}) == 0.0

    def test_zero_imputation_penalizes_partial_submission(self):
        """
        FIX-06: A partial vector (missing features) must score LOWER than
        a full vector against the same known router.
        The old intersection-only approach would give both the same score.
        """
        known = {"forwarding_rate": 0.9, "switching_cap": 0.8,
                 "ipv4_routes": 0.7, "dram": 0.6}
        full_input    = {"forwarding_rate": 0.9, "switching_cap": 0.8,
                         "ipv4_routes": 0.7, "dram": 0.6}
        partial_input = {"forwarding_rate": 0.9, "switching_cap": 0.8}

        score_full    = _cosine_similarity(full_input, known)
        score_partial = _cosine_similarity(partial_input, known)

        assert score_full    == pytest.approx(1.0, abs=1e-6)
        assert score_partial <  score_full   # partial must be penalized

    def test_partial_submission_score_is_strictly_less_than_one(self):
        known   = {"a": 0.8, "b": 0.6, "c": 0.9, "d": 0.7}
        partial = {"a": 0.8}
        score   = _cosine_similarity(partial, known)
        assert score < 1.0

    def test_union_includes_dimensions_from_both_vectors(self):
        """
        With union semantics, a dimension present in only one vector
        contributes zero to the dot product but increases the magnitude
        of the vector that has it, reducing the final score.
        """
        vec_a = {"x": 1.0}
        vec_b = {"x": 1.0, "y": 1.0}
        score = _cosine_similarity(vec_a, vec_b)
        # dot=1.0, mag_a=1.0, mag_b=sqrt(2) → score = 1/sqrt(2) ≈ 0.707
        assert score == pytest.approx(1.0 / math.sqrt(2), abs=1e-6)

    def test_score_bounded_between_zero_and_one(self):
        import random
        random.seed(42)
        for _ in range(50):
            keys = ["a", "b", "c", "d", "e"]
            vec_a = {k: random.random() for k in random.sample(keys, 3)}
            vec_b = {k: random.random() for k in random.sample(keys, 3)}
            score = _cosine_similarity(vec_a, vec_b)
            assert 0.0 <= score <= 1.0 + 1e-9

    def test_all_zero_vector_returns_zero(self):
        vec_a = {"a": 0.0, "b": 0.0}
        vec_b = {"a": 0.5, "b": 0.5}
        assert _cosine_similarity(vec_a, vec_b) == 0.0

    def test_symmetry(self):
        vec_a = {"a": 0.3, "b": 0.7}
        vec_b = {"a": 0.9, "c": 0.2}
        assert _cosine_similarity(vec_a, vec_b) == pytest.approx(
            _cosine_similarity(vec_b, vec_a), abs=1e-9
        )
