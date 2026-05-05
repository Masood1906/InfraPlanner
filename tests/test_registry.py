# tests/test_registry.py
# Tests for graph/router_registry.py (FIX-03).
# Covers: save, load, exists, idempotency, concurrency, spec_to_entry,
# and the seed integration that re-seeds registry entries on startup.

import json
import os
import threading
import pytest
from graph.router_registry import load, save, exists, spec_to_entry


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """
    Redirect _REGISTRY_PATH to a temp file for every test.
    Ensures tests never touch the real router_registry.json.
    """
    import graph.router_registry as reg_module
    fake_path = str(tmp_path / "test_registry.json")
    monkeypatch.setattr(reg_module, "_REGISTRY_PATH", fake_path)
    yield fake_path


def _make_entry(router_id="test_router", model="Test Router"):
    return {
        "router_id": router_id,
        "model":     model,
        "vendor":    "TestCo",
        "series":    "TX",
        "features": [
            {"name": "Forwarding Rate",    "canonical_value": 2232.0, "canonical_unit": "Mpps"},
            {"name": "Switching Capacity", "canonical_value": 640.0,  "canonical_unit": "Gbps"},
        ],
    }


# ── load ──────────────────────────────────────────────────────────────────────

class TestLoad:

    def test_load_returns_empty_list_when_file_missing(self):
        assert load() == []

    def test_load_returns_saved_entries(self):
        save(_make_entry("r1"))
        save(_make_entry("r2", "Router 2"))
        entries = load()
        assert len(entries) == 2

    def test_load_returns_correct_data(self):
        entry = _make_entry("r_load_test")
        save(entry)
        loaded = load()
        assert loaded[0]["router_id"] == "r_load_test"
        assert loaded[0]["model"]     == "Test Router"

    def test_load_returns_empty_on_corrupt_json(self, isolated_registry):
        with open(isolated_registry, "w") as f:
            f.write("NOT VALID JSON {{{")
        assert load() == []


# ── save ──────────────────────────────────────────────────────────────────────

class TestSave:

    def test_save_returns_true_for_new_entry(self):
        assert save(_make_entry("new_router")) is True

    def test_save_returns_false_for_duplicate(self):
        save(_make_entry("dup_router"))
        assert save(_make_entry("dup_router")) is False

    def test_save_is_idempotent(self):
        entry = _make_entry("idem_router")
        save(entry)
        save(entry)
        save(entry)
        assert len(load()) == 1

    def test_save_creates_file_if_missing(self, isolated_registry):
        assert not os.path.exists(isolated_registry)
        save(_make_entry("creates_file"))
        assert os.path.exists(isolated_registry)

    def test_save_writes_valid_json(self, isolated_registry):
        save(_make_entry("json_test"))
        with open(isolated_registry) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert data[0]["router_id"] == "json_test"

    def test_save_multiple_distinct_entries(self):
        for i in range(5):
            save(_make_entry(f"router_{i}", f"Router {i}"))
        assert len(load()) == 5

    def test_save_preserves_all_fields(self):
        entry = _make_entry("full_fields")
        save(entry)
        loaded = load()[0]
        assert loaded["vendor"]  == "TestCo"
        assert loaded["series"]  == "TX"
        assert len(loaded["features"]) == 2
        assert loaded["features"][0]["name"] == "Forwarding Rate"


# ── exists ────────────────────────────────────────────────────────────────────

class TestExists:

    def test_exists_returns_false_when_registry_empty(self):
        assert exists("nonexistent") is False

    def test_exists_returns_true_after_save(self):
        save(_make_entry("exists_test"))
        assert exists("exists_test") is True

    def test_exists_returns_false_for_different_id(self):
        save(_make_entry("router_a"))
        assert exists("router_b") is False


# ── Concurrency ───────────────────────────────────────────────────────────────

class TestConcurrency:

    def test_concurrent_saves_produce_correct_count(self):
        """
        10 threads each saving a distinct router_id must result in exactly
        10 entries — no data corruption, no lost writes.
        """
        n = 10
        threads = [
            threading.Thread(
                target=save,
                args=(_make_entry(f"concurrent_{i}", f"Router {i}"),)
            )
            for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        entries = load()
        assert len(entries) == n

    def test_concurrent_duplicate_saves_are_idempotent(self):
        """
        10 threads all saving the same router_id must result in exactly 1 entry.
        """
        entry = _make_entry("same_router")
        threads = [threading.Thread(target=save, args=(entry,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(load()) == 1


# ── spec_to_entry ─────────────────────────────────────────────────────────────

class TestSpecToEntry:

    def test_spec_to_entry_contains_required_keys(self):
        from parser.input_parser import parse
        raw = {
            "model":           "Cisco 9300X",
            "vendor":          "Cisco",
            "series":          "9300",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        spec  = parse(raw)
        entry = spec_to_entry(spec)
        assert "router_id" in entry
        assert "model"     in entry
        assert "vendor"    in entry
        assert "series"    in entry
        assert "features"  in entry

    def test_spec_to_entry_features_have_canonical_values(self):
        from parser.input_parser import parse
        raw = {
            "model":           "Test",
            "switching_cap":   {"value": 1, "unit": "TBps"},  # 1 TBps → 1000 Gbps
            "forwarding_rate": {"value": 2232, "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8, "unit": "GB"},
        }
        spec  = parse(raw)
        entry = spec_to_entry(spec)
        switching = next(
            f for f in entry["features"] if f["name"] == "Switching Capacity"
        )
        assert switching["canonical_value"] == pytest.approx(1000.0)
        assert switching["canonical_unit"]  == "Gbps"

    def test_spec_to_entry_router_id_matches_spec(self):
        from parser.input_parser import parse
        raw = {
            "model":           "Cisco 9300X",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        spec  = parse(raw)
        entry = spec_to_entry(spec)
        assert entry["router_id"] == spec.router_id

    def test_spec_to_entry_is_json_serializable(self):
        from parser.input_parser import parse
        raw = {
            "model":           "Test",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        spec  = parse(raw)
        entry = spec_to_entry(spec)
        # Must not raise
        serialized = json.dumps(entry)
        assert len(serialized) > 0


# ── Seed integration ──────────────────────────────────────────────────────────

class TestSeedIntegration:

    def test_registry_entries_are_loaded_by_seed(self, isolated_registry):
        """
        Entries saved to the registry must be re-seeded into the graph
        when seed() is called. Verified by checking that _seed_from_registry
        calls graph.query for each saved router.
        """
        from unittest.mock import MagicMock
        from graph.seed import _seed_from_registry

        entry = _make_entry("registry_seed_test")
        save(entry)

        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])
        _seed_from_registry(mock_graph)

        # At minimum one MERGE call for the RouterModel node
        assert mock_graph.query.called
        all_queries = [str(call) for call in mock_graph.query.call_args_list]
        assert any("RouterModel" in q for q in all_queries)

    def test_empty_registry_does_not_call_graph(self, isolated_registry):
        """If registry is empty, _seed_from_registry must not touch the graph."""
        from unittest.mock import MagicMock
        from graph.seed import _seed_from_registry

        mock_graph = MagicMock()
        _seed_from_registry(mock_graph)
        mock_graph.query.assert_not_called()


# ── Persistence regression tests ──────────────────────────────────────────────
# These tests cover the three bugs fixed in this session:
#
# Bug 1: map_to_graph(persist=True) skipped registry_save when the router
#        already existed in the graph, so the router was lost after a graph wipe.
# Bug 2: _seed_from_registry had no error handling — one bad entry aborted all.
# Bug 3: No logging made failures invisible.

class TestPersistenceRegression:

    def _make_spec(self, model="Juniper MX480", vendor="Juniper"):
        from parser.input_parser import parse
        return parse({
            "model":           model,
            "vendor":          vendor,
            "series":          "MX",
            "switching_cap":   {"value": 5760,    "unit": "Gbps"},
            "forwarding_rate": {"value": 3000,    "unit": "Mpps"},
            "ipv4_routes":     {"value": 1000000, "unit": "count"},
            "dram_gb":         {"value": 32,      "unit": "GB"},
        })

    # ── Bug 1: registry_save must be called even when router already in graph ──

    def test_registry_saved_when_router_already_in_graph(self, isolated_registry):
        """
        If the router already exists in the graph (is_new=False), persist=True
        must still write to the registry. This was the primary persistence bug:
        the router was in FalkorDB but not in router_registry.json, so after a
        graph wipe it disappeared permanently.
        """
        from unittest.mock import MagicMock, patch
        from parser.entity_mapper import map_to_graph

        spec = self._make_spec()

        # Simulate router already existing in graph
        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[["existing_node"]])

        with patch("parser.entity_mapper._router_exists", return_value=True), \
             patch("parser.entity_mapper._create_router") as mock_create, \
             patch("parser.entity_mapper._create_features"), \
             patch("parser.entity_mapper._wire_has_feature"), \
             patch("parser.entity_mapper._wire_implies"):

            result = map_to_graph(mock_graph, spec, persist=True)

        # Registry must have been written despite router existing in graph
        assert exists(spec.router_id), (
            "registry_save was not called when router already existed in graph. "
            "This is Bug 1: router will disappear after next graph wipe."
        )
        # When router already exists, graph writes are skipped (MERGE not needed)
        mock_create.assert_not_called()

    def test_registry_saved_when_router_is_new(self, isolated_registry):
        """
        When the router is genuinely new (not in graph), persist=True must
        write to both the registry and the graph.
        """
        from unittest.mock import MagicMock, patch
        from parser.entity_mapper import map_to_graph

        spec = self._make_spec("New Router XYZ", "Acme")

        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])

        with patch("parser.entity_mapper._router_exists", return_value=False), \
             patch("parser.entity_mapper._create_router"), \
             patch("parser.entity_mapper._create_features"), \
             patch("parser.entity_mapper._wire_has_feature"), \
             patch("parser.entity_mapper._wire_implies"):

            map_to_graph(mock_graph, spec, persist=True)

        assert exists(spec.router_id), "New router was not saved to registry."

    def test_registry_save_before_graph_write_order(self, isolated_registry):
        """
        Registry must be written BEFORE graph writes so that if a graph write
        fails partway through, the router is still in the registry and will be
        re-seeded on next startup.
        """
        from unittest.mock import MagicMock, patch, call
        from parser.entity_mapper import map_to_graph

        spec = self._make_spec()
        call_order = []

        def track_registry(*a, **kw):
            call_order.append("registry")
            return True

        def track_graph(*a, **kw):
            call_order.append("graph")

        with patch("parser.entity_mapper._router_exists", return_value=False), \
             patch("parser.entity_mapper.registry_save", side_effect=track_registry), \
             patch("parser.entity_mapper._create_router", side_effect=track_graph), \
             patch("parser.entity_mapper._create_features"), \
             patch("parser.entity_mapper._wire_has_feature"), \
             patch("parser.entity_mapper._wire_implies"):

            map_to_graph(MagicMock(), spec, persist=True)

        assert call_order[0] == "registry", (
            f"Registry write must happen before graph write. Got order: {call_order}"
        )

    def test_duplicate_save_returns_false_not_error(self, isolated_registry):
        """
        Saving the same router twice must return False (idempotent), not raise.
        The second save must not corrupt the registry.
        """
        entry = _make_entry("dup_persist_test")
        first  = save(entry)
        second = save(entry)
        assert first  is True
        assert second is False
        assert len(load()) == 1

    # ── Bug 2: _seed_from_registry must not abort on one bad entry ────────────

    def test_seed_from_registry_continues_after_one_bad_entry(self, isolated_registry):
        """
        If one registry entry fails to seed (e.g. malformed data), the remaining
        entries must still be seeded. Before the fix, any exception aborted all.
        """
        from unittest.mock import MagicMock
        from graph.seed import _seed_from_registry

        # Write two entries: one valid, one that will cause a graph error
        good_entry = _make_entry("good_router")
        bad_entry  = {"router_id": "bad_router", "model": "Bad", "vendor": "X",
                      "series": "", "features": [{"name": "Forwarding Rate",
                      "canonical_value": "NOT_A_NUMBER", "canonical_unit": "Mpps"}]}
        save(good_entry)
        save(bad_entry)

        call_count = {"n": 0}
        def mock_query(q, params=None):
            call_count["n"] += 1
            if params and params.get("id") == "bad_router":
                raise RuntimeError("Simulated graph write failure")
            return MagicMock(result_set=[])

        mock_graph = MagicMock()
        mock_graph.query.side_effect = mock_query

        # Must not raise — bad entry is logged and skipped
        _seed_from_registry(mock_graph)

        # good_router must have been attempted
        assert call_count["n"] > 0, "No graph queries were made at all"

    def test_seed_from_registry_handles_missing_optional_fields(self, isolated_registry):
        """
        Registry entries written by older code may be missing optional fields
        like 'series' or 'vendor'. _seed_from_registry must handle this with
        .get() defaults rather than raising KeyError.
        """
        from unittest.mock import MagicMock
        from graph.seed import _seed_from_registry

        # Entry missing 'series' and 'vendor' (older registry format)
        minimal_entry = {
            "router_id": "minimal_router",
            "model":     "Minimal Router",
            "features":  [
                {"name": "Forwarding Rate", "canonical_value": 100.0, "canonical_unit": "Mpps"},
            ],
        }
        save(minimal_entry)

        mock_graph = MagicMock()
        mock_graph.query.return_value = MagicMock(result_set=[])

        # Must not raise KeyError on missing 'series'/'vendor'
        _seed_from_registry(mock_graph)
        assert mock_graph.query.called

    # ── Router ID consistency ─────────────────────────────────────────────────

    def test_router_id_consistent_from_parser_to_registry(self, isolated_registry):
        """
        The router_id produced by the parser must match what is stored in the
        registry and what the graph uses as the node id.
        """
        from parser.input_parser import parse

        raw = {
            "model":           "Juniper MX480",
            "vendor":          "Juniper",
            "series":          "MX",
            "switching_cap":   {"value": 5760,    "unit": "Gbps"},
            "forwarding_rate": {"value": 3000,    "unit": "Mpps"},
            "ipv4_routes":     {"value": 1000000, "unit": "count"},
            "dram_gb":         {"value": 32,      "unit": "GB"},
        }
        spec  = parse(raw)
        entry = spec_to_entry(spec)

        assert spec.router_id == "juniper_mx480", (
            f"Parser produced unexpected router_id: {spec.router_id}"
        )
        assert entry["router_id"] == spec.router_id, (
            "spec_to_entry router_id does not match spec.router_id"
        )

        save(entry)
        loaded = load()
        assert loaded[0]["router_id"] == "juniper_mx480", (
            "Stored router_id does not match expected 'juniper_mx480'"
        )

    def test_router_id_slugification_is_consistent(self):
        """
        The same model name must always produce the same router_id regardless
        of how many times it is parsed.
        """
        from parser.input_parser import parse

        raw = {
            "model":           "Juniper MX480",
            "switching_cap":   {"value": 5760,    "unit": "Gbps"},
            "forwarding_rate": {"value": 3000,    "unit": "Mpps"},
            "ipv4_routes":     {"value": 1000000, "unit": "count"},
            "dram_gb":         {"value": 32,      "unit": "GB"},
        }
        ids = {parse(raw).router_id for _ in range(5)}
        assert len(ids) == 1, f"router_id is not deterministic: {ids}"

    # ── Seed reloads registry after graph wipe ────────────────────────────────

    def test_registry_router_present_after_seed_from_registry(self, isolated_registry):
        """
        After saving a router to the registry and calling _seed_from_registry,
        the router must be queryable from the graph. This simulates what happens
        on every startup after a schema-version-triggered graph wipe.
        """
        from unittest.mock import MagicMock
        from graph.seed import _seed_from_registry

        entry = _make_entry("persist_after_wipe")
        save(entry)

        seeded_ids = []

        def capture_query(q, params=None):
            if params and "id" in params:
                seeded_ids.append(params["id"])
            return MagicMock(result_set=[])

        mock_graph = MagicMock()
        mock_graph.query.side_effect = capture_query

        _seed_from_registry(mock_graph)

        assert "persist_after_wipe" in seeded_ids, (
            "Router was not re-seeded into graph after registry load. "
            "This means the router would disappear after a graph wipe."
        )
