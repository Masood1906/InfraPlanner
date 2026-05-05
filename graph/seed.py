# graph/seed.py
# Populates FalkorDB with the full knowledge graph.
# Routers: 9300X, 9200, 9500, 8500, ASR1001-X, ASR1006-X
#
# SCHEMA VERSIONING
# -----------------
# seed() is called on every startup but uses MERGE, which is a no-op for
# existing nodes/edges. This means changes to SATISFIED_BY fit_scores,
# deployment patterns, or implication weights never take effect on a live
# graph that was seeded with an older version.
#
# To force a full re-seed, bump GRAPH_SCHEMA_VERSION below. The lifespan
# handler in api/dependencies.py compares this value against what is stored
# in the graph. If they differ, it deletes the graph and calls seed() fresh.
# This is safe because all router data is re-seeded from seed.py +
# router_registry.json on every startup.

import logging

logger = logging.getLogger(__name__)

# Bump this string whenever SATISFIED_BY edges, deployment patterns,
# implication weights, or any other graph structure changes.
# Format: "YYYY-MM-DD.N" where N is a sequence number for same-day changes.
GRAPH_SCHEMA_VERSION = "2024-01-03.3"


def seed(graph):
    _seed_routers(graph)
    _seed_implications(graph)
    _seed_requirements(graph)
    _seed_node_profiles(graph)
    _seed_deployment_patterns(graph)
    _seed_edges(graph)
    _seed_from_registry(graph)
    logger.info("Knowledge graph populated.")


# ── Layer 1: Router Models & Features ─────────────────────────────────────────

ROUTER_CATALOG = [
    ("cisco_9300x",   "Cisco Catalyst 9300X",  "9300",    "Cisco"),
    ("cisco_9200",    "Cisco Catalyst 9200",   "9200",    "Cisco"),
    ("cisco_9500",    "Cisco Catalyst 9500",   "9500",    "Cisco"),
    ("cisco_8500",    "Cisco Catalyst 8500",   "8500",    "Cisco"),
    ("cisco_asr1001", "Cisco ASR 1001-X",      "ASR1000", "Cisco"),
    ("cisco_asr1006", "Cisco ASR 1006-X",      "ASR1000", "Cisco"),
]

# (router_id, feature_id, name, category, value, unit)
ROUTER_FEATURES = [
    ("cisco_9300x", "f_9300x_stack_bw",   "Stacking Bandwidth", "networking", 1000,    "Gbps"),
    ("cisco_9300x", "f_9300x_switch_cap", "Switching Capacity", "networking", 640,     "Gbps"),
    ("cisco_9300x", "f_9300x_fwd_rate",   "Forwarding Rate",    "processing", 2232,    "Mpps"),
    ("cisco_9300x", "f_9300x_vlan",       "VLAN IDs",           "routing",    1200,    "count"),
    ("cisco_9300x", "f_9300x_mac",        "MAC Addresses",      "routing",    16000,   "count"),
    ("cisco_9300x", "f_9300x_ipv4",       "IPv4 Routes",        "routing",    32000,   "count"),
    ("cisco_9300x", "f_9300x_dram",       "DRAM",               "memory",     8,       "GB"),

    ("cisco_9200",  "f_9200_switch_cap",  "Switching Capacity", "networking", 176,     "Gbps"),
    ("cisco_9200",  "f_9200_fwd_rate",    "Forwarding Rate",    "processing", 130,     "Mpps"),
    ("cisco_9200",  "f_9200_vlan",        "VLAN IDs",           "routing",    1024,    "count"),
    ("cisco_9200",  "f_9200_mac",         "MAC Addresses",      "routing",    8000,    "count"),
    ("cisco_9200",  "f_9200_ipv4",        "IPv4 Routes",        "routing",    8000,    "count"),
    ("cisco_9200",  "f_9200_dram",        "DRAM",               "memory",     4,       "GB"),

    ("cisco_9500",  "f_9500_switch_cap",  "Switching Capacity", "networking", 6400,    "Gbps"),
    ("cisco_9500",  "f_9500_fwd_rate",    "Forwarding Rate",    "processing", 4800,    "Mpps"),
    ("cisco_9500",  "f_9500_vlan",        "VLAN IDs",           "routing",    4000,    "count"),
    ("cisco_9500",  "f_9500_mac",         "MAC Addresses",      "routing",    64000,   "count"),
    ("cisco_9500",  "f_9500_ipv4",        "IPv4 Routes",        "routing",    128000,  "count"),
    ("cisco_9500",  "f_9500_dram",        "DRAM",               "memory",     32,      "GB"),

    ("cisco_8500",  "f_8500_switch_cap",  "Switching Capacity", "networking", 400,     "Gbps"),
    ("cisco_8500",  "f_8500_fwd_rate",    "Forwarding Rate",    "processing", 300,     "Mpps"),
    ("cisco_8500",  "f_8500_vlan",        "VLAN IDs",           "routing",    4094,    "count"),
    ("cisco_8500",  "f_8500_mac",         "MAC Addresses",      "routing",    32000,   "count"),
    ("cisco_8500",  "f_8500_ipv4",        "IPv4 Routes",        "routing",    512000,  "count"),
    ("cisco_8500",  "f_8500_dram",        "DRAM",               "memory",     16,      "GB"),

    ("cisco_asr1001", "f_asr1001_switch_cap", "Switching Capacity", "networking", 20,      "Gbps"),
    ("cisco_asr1001", "f_asr1001_fwd_rate",   "Forwarding Rate",    "processing", 15,      "Mpps"),
    ("cisco_asr1001", "f_asr1001_ipv4",       "IPv4 Routes",        "routing",    2000000, "count"),
    ("cisco_asr1001", "f_asr1001_dram",       "DRAM",               "memory",     8,       "GB"),

    ("cisco_asr1006", "f_asr1006_switch_cap", "Switching Capacity", "networking", 200,     "Gbps"),
    ("cisco_asr1006", "f_asr1006_fwd_rate",   "Forwarding Rate",    "processing", 200,     "Mpps"),
    ("cisco_asr1006", "f_asr1006_ipv4",       "IPv4 Routes",        "routing",    4000000, "count"),
    ("cisco_asr1006", "f_asr1006_dram",       "DRAM",               "memory",     64,      "GB"),
]

# (router_id, feature_id, implication_id, base_weight)
ROUTER_FEATURE_IMPLICATIONS = [
    ("cisco_9300x", "f_9300x_fwd_rate",   "oi_high_pkt",   1.0),
    ("cisco_9300x", "f_9300x_switch_cap", "oi_high_net",   0.9),
    ("cisco_9300x", "f_9300x_stack_bw",   "oi_high_net",   0.8),
    ("cisco_9300x", "f_9300x_ipv4",       "oi_high_route", 1.0),
    ("cisco_9300x", "f_9300x_mac",        "oi_high_route", 0.7),
    ("cisco_9300x", "f_9300x_vlan",       "oi_high_route", 0.6),
    ("cisco_9300x", "f_9300x_dram",       "oi_high_mem",   1.0),
    ("cisco_9300x", "f_9300x_ipv4",       "oi_high_mem",   0.8),
    ("cisco_9300x", "f_9300x_switch_cap", "oi_port_dense", 0.9),

    ("cisco_9200",  "f_9200_fwd_rate",    "oi_high_pkt",   0.3),
    ("cisco_9200",  "f_9200_switch_cap",  "oi_high_net",   0.4),
    ("cisco_9200",  "f_9200_ipv4",        "oi_high_route", 0.3),
    ("cisco_9200",  "f_9200_dram",        "oi_high_mem",   0.2),
    ("cisco_9200",  "f_9200_switch_cap",  "oi_port_dense", 0.3),

    ("cisco_9500",  "f_9500_fwd_rate",    "oi_high_pkt",   0.9),
    ("cisco_9500",  "f_9500_switch_cap",  "oi_high_net",   1.0),
    ("cisco_9500",  "f_9500_ipv4",        "oi_high_route", 1.0),
    ("cisco_9500",  "f_9500_mac",         "oi_high_route", 0.8),
    ("cisco_9500",  "f_9500_dram",        "oi_high_mem",   0.9),
    ("cisco_9500",  "f_9500_switch_cap",  "oi_port_dense", 1.0),

    ("cisco_8500",  "f_8500_fwd_rate",    "oi_high_pkt",   0.5),
    ("cisco_8500",  "f_8500_switch_cap",  "oi_high_net",   0.6),
    ("cisco_8500",  "f_8500_ipv4",        "oi_high_route", 0.9),
    ("cisco_8500",  "f_8500_dram",        "oi_high_mem",   0.7),
    ("cisco_8500",  "f_8500_switch_cap",  "oi_port_dense", 0.5),

    ("cisco_asr1001", "f_asr1001_fwd_rate",   "oi_high_pkt",   0.2),
    ("cisco_asr1001", "f_asr1001_switch_cap", "oi_high_net",   0.3),
    ("cisco_asr1001", "f_asr1001_ipv4",       "oi_high_route", 0.8),
    ("cisco_asr1001", "f_asr1001_dram",       "oi_high_mem",   0.5),

    ("cisco_asr1006", "f_asr1006_fwd_rate",   "oi_high_pkt",   0.5),
    ("cisco_asr1006", "f_asr1006_switch_cap", "oi_high_net",   0.7),
    ("cisco_asr1006", "f_asr1006_ipv4",       "oi_high_route", 1.0),
    ("cisco_asr1006", "f_asr1006_dram",       "oi_high_mem",   1.0),
]


def _seed_from_registry(graph):
    """
    Load user-submitted routers from router_registry.json and seed them
    into the graph. Uses MERGE so it is safe to call on every startup.
    All queries are parameterized.
    """
    from graph.router_registry import load as load_registry
    from graph.weight_engine import compute_edge_weight, FEATURE_IMPLICATION_MAP, PHYSICAL_CEILINGS
    from parser.entity_mapper import FEATURE_CATEGORIES

    entries = load_registry()
    if not entries:
        logger.info("Registry: router_registry.json is empty — no user-submitted routers to seed.")
        return

    logger.info("Registry: seeding %d user-submitted router(s) from router_registry.json", len(entries))

    for entry in entries:
        rid = entry.get("router_id")
        if not rid:
            logger.warning("Registry: skipping entry with missing router_id: %s", entry)
            continue
        try:
            graph.query(
                "MERGE (:RouterModel {id: $id, name: $name, series: $series, "
                "vendor: $vendor, source: 'user_submitted'})",
                {"id": rid, "name": entry.get("model", rid),
                 "series": entry.get("series", ""), "vendor": entry.get("vendor", "Unknown")},
            )
            for feat in entry.get("features", []):
                fid = f"f_{rid}_{feat['name'].lower().replace(' ', '_')}"
                cat = FEATURE_CATEGORIES.get(feat["name"], "general")
                graph.query(
                    "MERGE (:RouterFeature {id: $fid, name: $name, "
                    "category: $category, value: $value, unit: $unit})",
                    {"fid": fid, "name": feat["name"], "category": cat,
                     "value": feat["canonical_value"], "unit": feat["canonical_unit"]},
                )
                graph.query(
                    "MATCH (m:RouterModel {id: $rid}), (f:RouterFeature {id: $fid}) "
                    "MERGE (m)-[:HAS_FEATURE]->(f)",
                    {"rid": rid, "fid": fid},
                )
                if feat["name"] in PHYSICAL_CEILINGS:
                    weight = compute_edge_weight(feat["canonical_value"], PHYSICAL_CEILINGS[feat["name"]])
                    for feat_name, impl_id in FEATURE_IMPLICATION_MAP:
                        if feat["name"] == feat_name:
                            graph.query(
                                "MATCH (f:RouterFeature {id: $fid}), "
                                "(o:OperationalImplication {id: $impl_id}) "
                                "MERGE (f)-[i:IMPLIES]->(o) "
                                "ON CREATE SET i.base_weight = $weight",
                                {"fid": fid, "impl_id": impl_id, "weight": weight},
                            )
            logger.info("Registry: seeded router '%s' (%s) into graph", rid, entry.get("model", rid))
        except Exception as exc:
            logger.error(
                "Registry: failed to seed router '%s' into graph: %s",
                rid, exc, exc_info=True,
            )


def _seed_routers(graph):
    for rid, name, series, vendor in ROUTER_CATALOG:
        graph.query(
            "MERGE (:RouterModel {id: $id, name: $name, series: $series, vendor: $vendor})",
            {"id": rid, "name": name, "series": series, "vendor": vendor},
        )
    for rid, fid, fname, cat, val, unit in ROUTER_FEATURES:
        graph.query(
            "MERGE (:RouterFeature {id: $fid, name: $name, "
            "category: $cat, value: $val, unit: $unit})",
            {"fid": fid, "name": fname, "cat": cat, "val": val, "unit": unit},
        )


# ── Layer 2: Operational Implications ─────────────────────────────────────────

def _seed_implications(graph):
    implications = [
        ("oi_high_pkt",   "High Packet Processing Demand",
         "Forwarding rate >1000 Mpps requires high vCPU allocation",           5),
        ("oi_high_net",   "High Network Throughput Demand",
         "Switching capacity >500 Gbps requires high-bandwidth NICs",          4),
        ("oi_high_route", "High Routing Scale",
         "Large IPv4/MAC/VLAN tables require significant memory for FIB/RIB",  4),
        ("oi_high_mem",   "High Memory Demand",
         "Large routing tables and DRAM requirements drive RAM allocation",     3),
        ("oi_port_dense", "High Port Density",
         "High switching capacity implies many physical/virtual ports needed",  3),
    ]
    for oid, name, desc, severity in implications:
        graph.query(
            "MERGE (:OperationalImplication {id: $id, name: $name, "
            "description: $desc, severity: $severity})",
            {"id": oid, "name": name, "desc": desc, "severity": severity},
        )


# ── Layer 3: Infrastructure Requirements ──────────────────────────────────────

def _seed_requirements(graph):
    requirements = [
        ("ir_cpu",     "Processing Capacity", "cpu",        32,      "vCPU"),
        ("ir_ram",     "Memory Capacity",     "memory",     256,     "GB"),
        ("ir_net",     "Networking Capacity", "networking", 100,     "Gbps"),
        ("ir_routing", "Routing Capacity",    "routing",    32000,   "routes"),
        ("ir_storage", "Storage Capacity",    "storage",    500,     "GB"),
        ("ir_ports",   "Port Capacity",       "ports",      32,      "count"),
    ]
    for rid, name, rtype, min_val, unit in requirements:
        graph.query(
            "MERGE (:InfraRequirement {id: $id, name: $name, "
            "resource_type: $rtype, min_value: $min_val, unit: $unit})",
            {"id": rid, "name": name, "rtype": rtype, "min_val": min_val, "unit": unit},
        )


# ── Layer 4: Node Profiles ────────────────────────────────────────────────────

def _seed_node_profiles(graph):
    profiles = [
        ("np_compute_xl",  "Compute-XL",  64,  512,  48, 2000, "compute"),
        ("np_compute_l",   "Compute-L",   32,  256,  32, 1000, "compute"),
        ("np_compute_s",   "Compute-S",   16,  128,  16,  500, "compute"),
        ("np_network_xl",  "Network-XL",  32,  128,  64,  500, "network"),
        ("np_network_l",   "Network-L",   16,   64,  32,  250, "network"),
        ("np_memory_xl",   "Memory-XL",  128, 1024,  32, 4000, "memory"),
        ("np_memory_l",    "Memory-L",    16,  512,  16, 1000, "memory"),
        ("np_storage_l",   "Storage-L",   32,  256,  16, 8000, "storage"),
        ("np_balanced",    "Balanced",    32,  256,  32, 1000, "balanced"),
    ]
    for pid, name, vcpu, ram, ports, storage, role in profiles:
        graph.query(
            "MERGE (:NodeProfile {id: $id, name: $name, vcpu: $vcpu, "
            "ram_gb: $ram, ports: $ports, storage_gb: $storage, role: $role})",
            {"id": pid, "name": name, "vcpu": vcpu, "ram": ram,
             "ports": ports, "storage": storage, "role": role},
        )


# ── Layer 4b: Deployment Patterns ─────────────────────────────────────────────

def _seed_deployment_patterns(graph):
    patterns = [
        (
            "dp_high_perf", "High Performance",
            "compute,network,memory", "",
            4, 8, "high_performance", "true", 1,
            "Full heterogeneous cluster: compute + network + memory nodes. "
            "For high-end campus and core WAN routers.",
        ),
        (
            "dp_compute_heavy", "Compute Heavy",
            "compute", "memory",
            3, 8, "compute_heavy", "true", 1,
            "Compute-dominant cluster with optional memory nodes. "
            "For packet-processing-heavy routers.",
        ),
        (
            "dp_memory_routing", "Memory Routing",
            "memory", "network",
            3, 6, "memory_routing", "true", 1,
            "Memory-dominant cluster for large routing table routers (WAN/SP). "
            "FIB/RIB scale drives memory node selection.",
        ),
        (
            "dp_network_heavy", "Network Heavy",
            "network", "compute",
            3, 6, "network_heavy", "true", 1,
            "Network-dominant cluster for high port density routers.",
        ),
        (
            "dp_minimal", "Minimal",
            "", "balanced",
            3, 3, "minimal", "true", 1,
            "Minimal 3-node HA cluster for low-end or branch routers.",
        ),
        (
            "dp_balanced", "Balanced",
            "balanced", "",
            3, 4, "balanced", "true", 1,
            "Balanced 3-4 node cluster for access/campus switches with "
            "moderate compute and networking needs.",
        ),
        (
            "dp_dual_cluster", "Dual Cluster",
            "compute,network", "memory",
            6, 16, "dual_cluster", "true", 2,
            "Two-cluster topology for very high scale deployments. "
            "Compute and network workloads split across clusters.",
        ),
    ]
    for pid, name, req_roles, opt_roles, mn, mx, topo, ha, cc, desc in patterns:
        graph.query(
            "MERGE (:DeploymentPattern {id: $id, name: $name, "
            "required_roles: $req_roles, optional_roles: $opt_roles, "
            "min_nodes: $mn, max_nodes: $mx, topology_label: $topo, "
            "ha_enabled: $ha, cluster_count: $cc, description: $desc})",
            {"id": pid, "name": name, "req_roles": req_roles,
             "opt_roles": opt_roles, "mn": mn, "mx": mx, "topo": topo,
             "ha": ha, "cc": cc, "desc": desc},
        )

    profile_patterns = [
        ("np_compute_xl",  "dp_high_perf"),
        ("np_compute_xl",  "dp_compute_heavy"),
        ("np_compute_xl",  "dp_dual_cluster"),
        ("np_compute_l",   "dp_compute_heavy"),
        ("np_compute_s",   "dp_minimal"),
        ("np_network_xl",  "dp_high_perf"),
        ("np_network_xl",  "dp_network_heavy"),
        ("np_network_xl",  "dp_dual_cluster"),
        ("np_network_l",   "dp_network_heavy"),
        ("np_network_l",   "dp_minimal"),
        ("np_memory_xl",   "dp_high_perf"),
        ("np_memory_xl",   "dp_memory_routing"),
        ("np_memory_xl",   "dp_dual_cluster"),
        ("np_memory_l",    "dp_memory_routing"),
        ("np_memory_l",    "dp_high_perf"),
        ("np_storage_l",   "dp_memory_routing"),
        ("np_balanced",    "dp_minimal"),
        ("np_balanced",    "dp_balanced"),
    ]
    for pid, dpid in profile_patterns:
        graph.query(
            "MATCH (n:NodeProfile {id: $pid}), (p:DeploymentPattern {id: $dpid}) "
            "MERGE (n)-[:FITS_PATTERN]->(p)",
            {"pid": pid, "dpid": dpid},
        )


# ── Edges ──────────────────────────────────────────────────────────────────────

def _seed_edges(graph):
    # RouterModel HAS_FEATURE RouterFeature
    for rid, fid, *_ in ROUTER_FEATURES:
        graph.query(
            "MATCH (m:RouterModel {id: $rid}), (f:RouterFeature {id: $fid}) "
            "MERGE (m)-[:HAS_FEATURE]->(f)",
            {"rid": rid, "fid": fid},
        )

    # RouterFeature IMPLIES OperationalImplication {base_weight}
    for rid, fid, oid, base_weight in ROUTER_FEATURE_IMPLICATIONS:
        graph.query(
            "MATCH (f:RouterFeature {id: $fid}), "
            "(o:OperationalImplication {id: $oid}) "
            "MERGE (f)-[i:IMPLIES]->(o) "
            "ON CREATE SET i.base_weight = $w",
            {"fid": fid, "oid": oid, "w": base_weight},
        )

    # OperationalImplication REQUIRES InfraRequirement {priority}
    impl_reqs = [
        ("oi_high_pkt",   "ir_cpu",     1),
        ("oi_high_net",   "ir_net",     1),
        ("oi_high_net",   "ir_ports",   2),
        ("oi_high_route", "ir_routing", 1),
        ("oi_high_route", "ir_ram",     2),
        ("oi_high_mem",   "ir_ram",     1),
        ("oi_port_dense", "ir_ports",   1),
        ("oi_high_pkt",   "ir_storage", 3),
    ]
    for oid, rid, priority in impl_reqs:
        graph.query(
            "MATCH (o:OperationalImplication {id: $oid}), "
            "(r:InfraRequirement {id: $rid}) "
            "MERGE (o)-[:REQUIRES {priority: $p}]->(r)",
            {"oid": oid, "rid": rid, "p": priority},
        )

    # InfraRequirement SATISFIED_BY NodeProfile {fit_score}
    #
    # Design rules enforced here:
    #   1. ir_cpu   → ONLY compute-role profiles. Memory/network profiles
    #      must NOT appear here — they would win cpu via fit_breakdown fallback.
    #   2. ir_ram   → memory-role profiles primary; compute secondary at lower score.
    #   3. ir_net   → network-role profiles primary; balanced secondary.
    #   4. ir_routing → memory-role profiles only (RIB/FIB is memory-bound).
    #   5. ir_ports → network-role profiles primary; balanced secondary.
    #   6. ir_storage → storage-role primary; compute secondary.
    #   7. np_balanced gets explicit entries for cpu/net/ports at moderate scores
    #      so it can win those types for low-signal access routers (9200).
    #      Score 0.5 is below specialist profiles but above 0.0 (invisible).
    req_profiles = [
        # cpu → compute only
        ("ir_cpu",     "np_compute_xl",  1.0),
        ("ir_cpu",     "np_compute_l",   0.8),
        ("ir_cpu",     "np_compute_s",   0.5),
        ("ir_cpu",     "np_balanced",    0.5),
        # memory → memory primary, compute secondary
        ("ir_ram",     "np_memory_xl",   1.0),
        ("ir_ram",     "np_memory_l",    0.9),
        ("ir_ram",     "np_compute_xl",  0.5),
        ("ir_ram",     "np_balanced",    0.4),
        # networking → network primary, balanced secondary
        ("ir_net",     "np_network_xl",  1.0),
        ("ir_net",     "np_network_l",   0.7),
        ("ir_net",     "np_balanced",    0.5),
        # routing → memory only (RIB/FIB)
        ("ir_routing", "np_memory_xl",   1.0),
        ("ir_routing", "np_memory_l",    0.9),
        # ports → network primary, balanced secondary
        ("ir_ports",   "np_network_xl",  1.0),
        ("ir_ports",   "np_network_l",   0.8),
        ("ir_ports",   "np_balanced",    0.5),
        # storage → storage primary, compute secondary
        ("ir_storage", "np_storage_l",   1.0),
        ("ir_storage", "np_compute_xl",  0.8),
        ("ir_storage", "np_balanced",    0.4),
    ]
    for rid, pid, fit in req_profiles:
        graph.query(
            "MATCH (r:InfraRequirement {id: $rid}), (n:NodeProfile {id: $pid}) "
            "MERGE (r)-[:SATISFIED_BY {fit_score: $fit}]->(n)",
            {"rid": rid, "pid": pid, "fit": fit},
        )


