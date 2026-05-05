# graph/weight_engine.py
import math

# Update these ceilings when technology evolves — weights recompute automatically on next seed.
PHYSICAL_CEILINGS = {
    "Forwarding Rate":    100_000,
    "Switching Capacity": 100_000,
    "Stacking Bandwidth":  10_000,
    "IPv4 Routes":       100_000_000,
    "MAC Addresses":      10_000_000,
    "VLAN IDs":               4096,
    "DRAM":                   4096,
}

FEATURE_IMPLICATION_MAP = [
    ("Forwarding Rate",    "oi_high_pkt"),
    ("Switching Capacity", "oi_high_net"),
    ("Stacking Bandwidth", "oi_high_net"),
    ("IPv4 Routes",        "oi_high_route"),
    ("MAC Addresses",      "oi_high_route"),
    ("VLAN IDs",           "oi_high_route"),
    ("DRAM",               "oi_high_mem"),
    ("IPv4 Routes",        "oi_high_mem"),
    ("Switching Capacity", "oi_port_dense"),
]


def compute_edge_weight(value: float, ceiling: float) -> float:
    """Shared log-normalized weight formula used by seed.py and entity_mapper.py."""
    return round(math.log(value + 1) / math.log(ceiling + 1), 2)


def compute_weights(router_features):
    results = []
    for rid, fid, fname, _, val, _ in router_features:
        for feat_name, impl_id in FEATURE_IMPLICATION_MAP:
            if fname == feat_name and fname in PHYSICAL_CEILINGS:
                weight = compute_edge_weight(val, PHYSICAL_CEILINGS[fname])
                results.append((rid, fid, impl_id, weight))
    return results
