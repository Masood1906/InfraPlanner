# tests/conftest.py
# Shared pytest fixtures used across all test modules.

import pytest


# ── Router spec fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def spec_9300x():
    """Exact example from the project brief."""
    return {
        "model":           "Cisco 9300X",
        "vendor":          "Cisco",
        "series":          "9300",
        "stacking_bw":     {"value": 1,     "unit": "TBps"},
        "switching_cap":   {"value": 640,   "unit": "Gbps"},
        "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
        "vlan_ids":        {"value": 1200,  "unit": "count"},
        "mac_addresses":   {"value": 16000, "unit": "count"},
        "ipv4_routes":     {"value": 32000, "unit": "count"},
        "dram_gb":         {"value": 8,     "unit": "GB"},
    }


@pytest.fixture
def spec_minimal():
    """Only required fields, no optional ones."""
    return {
        "model":           "Cisco 9200",
        "vendor":          "Cisco",
        "switching_cap":   {"value": 24,   "unit": "Gbps"},
        "forwarding_rate": {"value": 18,   "unit": "Mpps"},
        "ipv4_routes":     {"value": 8000, "unit": "count"},
        "dram_gb":         {"value": 4,    "unit": "GB"},
    }


@pytest.fixture
def spec_juniper_mx480():
    """Juniper MX480 — unknown router, cross-vendor, high forwarding rate."""
    return {
        "model":           "Juniper MX480",
        "vendor":          "Juniper",
        "series":          "MX",
        "stacking_bw":     {"value": 0,       "unit": "Gbps"},   # not applicable
        "switching_cap":   {"value": 5760,    "unit": "Gbps"},
        "forwarding_rate": {"value": 3000,    "unit": "Mpps"},
        "vlan_ids":        {"value": 4094,    "unit": "count"},
        "mac_addresses":   {"value": 64000,   "unit": "count"},
        "ipv4_routes":     {"value": 1000000, "unit": "count"},
        "dram_gb":         {"value": 32,      "unit": "GB"},
    }


@pytest.fixture
def spec_high_end():
    """Hypothetical high-end router — should produce larger node counts."""
    return {
        "model":           "Cisco 8800",
        "vendor":          "Cisco",
        "series":          "8800",
        "stacking_bw":     {"value": 16,      "unit": "TBps"},
        "switching_cap":   {"value": 25600,   "unit": "Gbps"},
        "forwarding_rate": {"value": 166000,  "unit": "Mpps"},
        "ipv4_routes":     {"value": 4000000, "unit": "count"},
        "dram_gb":         {"value": 2048,    "unit": "GB"},
    }


# ── Inference input fixtures (no graph needed) ────────────────────────────────

@pytest.fixture
def mock_implications():
    """Simulates get_implications_for_router output for a mid-range router."""
    return [
        {"id": "oi_high_pkt",   "name": "High Packet Processing Demand", "severity": 5, "total_weight": 0.5},
        {"id": "oi_high_net",   "name": "High Network Throughput Demand","severity": 4, "total_weight": 0.8},
        {"id": "oi_high_route", "name": "High Routing Scale",            "severity": 4, "total_weight": 0.4},
        {"id": "oi_high_mem",   "name": "High Memory Demand",            "severity": 3, "total_weight": 0.3},
        {"id": "oi_port_dense", "name": "High Port Density",             "severity": 3, "total_weight": 0.6},
    ]


@pytest.fixture
def mock_requirements():
    """Simulates get_requirements_for_implications output."""
    return [
        {"id": "ir_cpu",     "name": "Processing Capacity",  "resource_type": "cpu",        "min_value": 32,    "unit": "vCPU",  "top_priority": 1, "driver_count": 1},
        {"id": "ir_ram",     "name": "Memory Capacity",      "resource_type": "memory",     "min_value": 256,   "unit": "GB",    "top_priority": 1, "driver_count": 2},
        {"id": "ir_net",     "name": "Networking Capacity",  "resource_type": "networking", "min_value": 100,   "unit": "Gbps",  "top_priority": 1, "driver_count": 1},
        {"id": "ir_routing", "name": "Routing Capacity",     "resource_type": "routing",    "min_value": 32000, "unit": "routes","top_priority": 1, "driver_count": 1},
        {"id": "ir_storage", "name": "Storage Capacity",     "resource_type": "storage",    "min_value": 500,   "unit": "GB",    "top_priority": 3, "driver_count": 1},
        {"id": "ir_ports",   "name": "Port Capacity",        "resource_type": "ports",      "min_value": 32,    "unit": "count", "top_priority": 1, "driver_count": 2},
    ]


@pytest.fixture
def mock_profiles():
    """Simulates get_node_profiles_for_requirements output, pre-ranked by fit."""
    return [
        {"id": "np_compute_xl", "name": "Compute-XL",  "vcpu": 64,  "ram_gb": 512, "ports": 48, "storage_gb": 2000, "role": "compute",
         "total_fit": 3.3,  "reqs_satisfied": 3,
         "fit_breakdown": ["cpu:1.0", "memory:0.5", "storage:0.8"]},
        {"id": "np_network_xl", "name": "Network-XL",  "vcpu": 32,  "ram_gb": 128, "ports": 64, "storage_gb": 500,  "role": "network",
         "total_fit": 2.0,  "reqs_satisfied": 2,
         "fit_breakdown": ["networking:1.0", "ports:1.0"]},
        {"id": "np_memory_l",   "name": "Memory-L",    "vcpu": 16,  "ram_gb": 512, "ports": 16, "storage_gb": 1000, "role": "memory",
         "total_fit": 1.9,  "reqs_satisfied": 2,
         "fit_breakdown": ["memory:0.9", "routing:0.9"]},
        {"id": "np_compute_l",  "name": "Compute-L",   "vcpu": 32,  "ram_gb": 256, "ports": 32, "storage_gb": 1000, "role": "compute",
         "total_fit": 1.4,  "reqs_satisfied": 2,
         "fit_breakdown": ["cpu:0.8"]},
        {"id": "np_balanced",   "name": "Balanced",    "vcpu": 32,  "ram_gb": 256, "ports": 32, "storage_gb": 1000, "role": "balanced",
         "total_fit": 1.9,  "reqs_satisfied": 4,
         "fit_breakdown": ["cpu:0.5", "memory:0.4", "networking:0.5", "ports:0.5"]},
    ]


# ── Live graph fixture (skipped if FalkorDB not running) ──────────────────────

@pytest.fixture(scope="session")
def live_graph():
    """
    Connects to a real FalkorDB instance, seeds it, and returns the graph.
    Tests using this fixture are skipped automatically if FalkorDB is unreachable.
    Mark tests with @pytest.mark.integration to make the dependency explicit.
    """
    import os
    pytest.importorskip("falkordb", reason="falkordb package not installed")

    try:
        from falkordb import FalkorDB
        from graph.schema import INDEX_STATEMENTS
        from graph.seed import seed

        host = os.getenv("FALKOR_HOST", "localhost")
        port = int(os.getenv("FALKOR_PORT", 6379))
        db    = FalkorDB(host=host, port=port)
        graph = db.select_graph("infra_planner_test")

        for stmt in INDEX_STATEMENTS:
            try:
                graph.query(stmt)
            except Exception:
                pass
        seed(graph)
        return graph

    except Exception as e:
        pytest.skip(f"FalkorDB not available: {e}")
