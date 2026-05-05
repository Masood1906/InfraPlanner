# graph/queries.py
# Core Cypher traversal patterns.
# All queries are READ-ONLY — no writes happen here.
#
# Key distinction:
#   base_weight  — stored on IMPLIES edges in graph (structural ontology)
#   total_weight — passed in from inference engine (instance weights from mapper)
# Queries return base_weight so the reasoning trace can show both values.
#
# SECURITY: All user-supplied values are passed as $params — never interpolated
# into query strings. This prevents Cypher injection.

def get_implications_for_router(graph, router_id: str) -> list[dict]:
    """
    Traverse L1→L2: Return all operational implications for a router
    with their base_weight (structural) from the graph.
    Returns empty list for unknown routers — inference falls back
    entirely to instance_weights computed from submitted feature values.
    """
    result = graph.query(
        """
        MATCH (m:RouterModel {id: $router_id})
              -[:HAS_FEATURE]->(f:RouterFeature)
              -[i:IMPLIES]->(o:OperationalImplication)
        RETURN o.id               AS id,
               o.name             AS name,
               o.severity         AS severity,
               sum(i.base_weight) AS total_base_weight,
               collect(f.name)    AS feature_names
        ORDER BY total_base_weight DESC
        """,
        {"router_id": router_id},
    )
    return [
        {
            "id":            r[0],
            "name":          r[1],
            "severity":      r[2],
            "total_weight":  r[3],
            "feature_names": r[4],
        }
        for r in result.result_set
    ]


def build_implications_from_weights(instance_weights: dict[str, float]) -> list[dict]:
    """
    For unknown routers with no graph subgraph, synthesise implication
    dicts directly from instance_weights so the inference engine has
    something to work with without touching the graph.
    """
    IMPL_META = {
        "oi_high_pkt":   {"name": "High Packet Processing Demand", "severity": 5},
        "oi_high_net":   {"name": "High Network Throughput Demand", "severity": 4},
        "oi_high_route": {"name": "High Routing Scale",            "severity": 4},
        "oi_high_mem":   {"name": "High Memory Demand",            "severity": 3},
        "oi_port_dense": {"name": "High Port Density",             "severity": 3},
    }
    return [
        {
            "id":            impl_id,
            "name":          IMPL_META[impl_id]["name"],
            "severity":      IMPL_META[impl_id]["severity"],
            "total_weight":  weight,
            "feature_names": [],
        }
        for impl_id, weight in instance_weights.items()
        if impl_id in IMPL_META and weight > 0
    ]


def get_requirements_for_implications(graph, implication_ids: list[str]) -> list[dict]:
    """
    Traverse L2→L3: Return infrastructure requirements driven by implications,
    ranked by priority and driver count.
    Uses $ids list parameter — no string interpolation.
    """
    if not implication_ids:
        return []
    result = graph.query(
        """
        MATCH (o:OperationalImplication)-[r:REQUIRES]->(req:InfraRequirement)
        WHERE o.id IN $ids
        RETURN req.id            AS id,
               req.name          AS name,
               req.resource_type AS resource_type,
               req.min_value     AS min_value,
               req.unit          AS unit,
               min(r.priority)   AS top_priority,
               count(o)          AS driver_count
        ORDER BY top_priority ASC, driver_count DESC
        """,
        {"ids": implication_ids},
    )
    return [
        {
            "id":            r[0],
            "name":          r[1],
            "resource_type": r[2],
            "min_value":     r[3],
            "unit":          r[4],
            "top_priority":  r[5],
            "driver_count":  r[6],
        }
        for r in result.result_set
    ]


def get_node_profiles_for_requirements(graph, requirement_ids: list[str]) -> list[dict]:
    """
    Traverse L3→L4: Return node profiles ranked by cumulative fit_score
    across all requirements they satisfy. Returns per-requirement fit scores
    so the inference engine can do per-resource profile selection.
    Uses $ids list parameter — no string interpolation.
    """
    if not requirement_ids:
        return []
    result = graph.query(
        """
        MATCH (req:InfraRequirement)-[s:SATISFIED_BY]->(n:NodeProfile)
        WHERE req.id IN $ids
        RETURN n.id              AS id,
               n.name            AS name,
               n.vcpu            AS vcpu,
               n.ram_gb          AS ram_gb,
               n.ports           AS ports,
               n.storage_gb      AS storage_gb,
               n.role            AS role,
               sum(s.fit_score)  AS total_fit,
               count(req)        AS reqs_satisfied,
               collect(req.resource_type + ':' + toString(s.fit_score)) AS fit_breakdown
        ORDER BY total_fit DESC
        """,
        {"ids": requirement_ids},
    )
    return [
        {
            "id":             r[0],
            "name":           r[1],
            "vcpu":           r[2],
            "ram_gb":         r[3],
            "ports":          r[4],
            "storage_gb":     r[5],
            "role":           r[6],
            "total_fit":      r[7],
            "reqs_satisfied": r[8],
            "fit_breakdown":  r[9],
        }
        for r in result.result_set
    ]


def get_deployment_pattern(graph, roles: list[str]) -> dict | None:
    """
    Traverse L4→L4b: Given the set of node roles selected by the inference
    engine, find the best-matching DeploymentPattern from the graph.

    Matching logic:
      1. Find all patterns whose required_roles are a subset of present roles.
      2. Among those, pick the one with the most required_roles matched
         (most specific pattern wins).
      3. Fall back to dp_minimal if nothing matches.
    """
    result = graph.query(
        """
        MATCH (p:DeploymentPattern)
        RETURN p.id             AS id,
               p.name           AS name,
               p.required_roles AS required_roles,
               p.optional_roles AS optional_roles,
               p.min_nodes      AS min_nodes,
               p.max_nodes      AS max_nodes,
               p.topology_label AS topology_label,
               p.ha_enabled     AS ha_enabled,
               p.cluster_count  AS cluster_count,
               p.description    AS description
        """
    )

    if not result.result_set:
        return None

    role_set = set(roles)
    best_pattern = None
    best_match_count = -1

    for row in result.result_set:
        pid, name, req_str, opt_str, mn, mx, topo, ha, cc, desc = row
        required = {r for r in req_str.split(",") if r} if req_str else set()

        if not required.issubset(role_set):
            continue

        match_count = len(required)
        if match_count > best_match_count:
            best_match_count = match_count
            best_pattern = {
                "id":              pid,
                "name":            name,
                "required_roles":  list(required),
                "min_nodes":       mn,
                "max_nodes":       mx,
                "topology_label":  topo,
                "ha_enabled":      ha == "true" or ha is True,
                "cluster_count":   int(cc),
                "description":     desc,
            }

    return best_pattern
