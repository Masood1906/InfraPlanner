# api/routes.py
# Route handlers. Business logic lives in main.run_pipeline.
# Routes are pure transport adapters.
#
# POST /api/v1/plan          → inference only, graph read-only
# POST /api/v1/admin/routers → persist a new router to the graph permanently

import logging
from fastapi import APIRouter, Depends, HTTPException
from api.schemas import (
    RouterSpecRequest, DeploymentPlanResponse,
    ClusterSpecResponse, NodeSpecResponse, ErrorResponse,
    ConfidenceResponse, ExplainRequest,
)
from api.dependencies import get_graph
from api.auth import verify_api_key
from engine.deployment_planner import DeploymentPlan

logger = logging.getLogger(__name__)
router = APIRouter()


# Minimum confidence score to return a plan.
# Aligned with the VERY LOW / LOW boundary in confidence.py CONFIDENCE_LABELS.
# A plan scoring below 0.40 is labelled VERY LOW — it is built on seed-floor
# defaults with no meaningful signal. Returning it would mislead the user.
_MIN_CONFIDENCE_TO_PLAN = 0.40


@router.post(
    "/plan",
    response_model=DeploymentPlanResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Generate a Kubernetes deployment plan for a router spec",
)
def generate_plan(body: RouterSpecRequest, graph=Depends(get_graph)):
    from main import run_pipeline
    try:
        dp: DeploymentPlan = run_pipeline(graph, body.to_raw(), persist=False)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Pipeline error for router '%s'", body.model)
        raise HTTPException(status_code=500, detail="Internal pipeline error.")

    # Layer 2: reject plans with confidence too low to be useful
    conf = dp.confidence.score if dp.confidence else 1.0
    if conf < _MIN_CONFIDENCE_TO_PLAN:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The submitted specifications do not represent a recognisable router. "
                f"Confidence score is {conf:.0%} — too low to generate a reliable plan. "
                f"Please check that Switching Capacity, Forwarding Rate, IPv4 Routes, "
                f"and DRAM are realistic values for a real network device."
            ),
        )
    return _serialize(dp)


@router.post(
    "/admin/routers",
    response_model=DeploymentPlanResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Persist a new router to the knowledge graph and generate its plan",
)
def persist_router(
    body: RouterSpecRequest,
    graph=Depends(get_graph),
    _key: str = Depends(verify_api_key),
):
    """
    Admin endpoint — permanently adds a new router to the knowledge graph.
    Use this only after verifying the router spec is correct.
    Regular /plan requests never write to the graph.
    """
    from main import run_pipeline
    try:
        dp: DeploymentPlan = run_pipeline(graph, body.to_raw(), persist=True)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Admin pipeline error for router '%s'", body.model)
        raise HTTPException(status_code=500, detail="Internal pipeline error.")
    return _serialize(dp)


@router.get(
    "/health",
    summary="Liveness check — verifies API and graph connection are healthy",
)
def health(graph=Depends(get_graph)):
    try:
        result = graph.query("MATCH (n) RETURN count(n) LIMIT 1")
        node_count = result.result_set[0][0] if result.result_set else 0
        return {"status": "ok", "graph_nodes": node_count}
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Graph unreachable.")


@router.get(
    "/graph/routers",
    summary="Return all RouterModel nodes for the router picker",
)
def graph_routers(graph=Depends(get_graph)):
    """
    Returns a lightweight list of all RouterModel nodes.
    Used by the graph explorer router picker — no edges, no properties.
    """
    try:
        result = graph.query(
            "MATCH (m:RouterModel) "
            "RETURN m.id AS id, m.name AS name, m.vendor AS vendor, m.series AS series"
        )
        return [
            {"id": r[0], "name": r[1], "vendor": r[2], "series": r[3]}
            for r in result.result_set
        ]
    except Exception:
        logger.exception("Failed to fetch routers")
        raise HTTPException(status_code=500, detail="Failed to fetch routers.")


@router.get(
    "/graph/router/{router_id}/chain",
    summary="Return the full reasoning chain for a specific router",
)
def graph_router_chain(router_id: str, graph=Depends(get_graph)):
    """
    Returns the complete reasoning chain for a router as nodes + edges.
    Chain: RouterModel → RouterFeature → OperationalImplication
           → InfraRequirement → NodeProfile → DeploymentPattern

    Each node includes all properties needed for the inspector panel.
    Each edge includes weight, priority, fit_score, and relationship type.
    """
    try:
        # Traverse the full chain in one query
        result = graph.query(
            """
            MATCH (m:RouterModel {id: $router_id})
                  -[:HAS_FEATURE]->(f:RouterFeature)
                  -[i:IMPLIES]->(o:OperationalImplication)
                  -[req:REQUIRES]->(r:InfraRequirement)
                  -[sat:SATISFIED_BY]->(n:NodeProfile)
            OPTIONAL MATCH (n)-[:FITS_PATTERN]->(dp:DeploymentPattern)
            RETURN
              m.id, m.name, m.vendor, m.series,
              f.id, f.name, f.category, f.value, f.unit,
              i.base_weight,
              o.id, o.name, o.severity, o.description,
              req.priority,
              r.id, r.name, r.resource_type, r.min_value, r.unit,
              sat.fit_score,
              n.id, n.name, n.vcpu, n.ram_gb, n.ports, n.storage_gb, n.role,
              dp.id, dp.name, dp.topology_label, dp.description
            """,
            {"router_id": router_id},
        )

        if not result.result_set:
            raise HTTPException(status_code=404, detail=f"Router '{router_id}' not found")

        nodes_map = {}
        edges = []

        def add_node(nid, label, ntype, props):
            if nid and nid not in nodes_map:
                nodes_map[nid] = {"id": nid, "label": label, "type": ntype, **props}

        for row in result.result_set:
            (
                m_id, m_name, m_vendor, m_series,
                f_id, f_name, f_cat, f_val, f_unit,
                i_weight,
                o_id, o_name, o_sev, o_desc,
                req_pri,
                r_id, r_name, r_rtype, r_min, r_unit,
                sat_fit,
                n_id, n_name, n_vcpu, n_ram, n_ports, n_stor, n_role,
                dp_id, dp_name, dp_topo, dp_desc,
            ) = row

            add_node(m_id, m_name, "RouterModel",
                     {"vendor": m_vendor, "series": m_series})
            add_node(f_id, f_name, "RouterFeature",
                     {"category": f_cat, "value": f_val, "unit": f_unit})
            add_node(o_id, o_name, "OperationalImplication",
                     {"severity": o_sev, "description": o_desc})
            add_node(r_id, r_name, "InfraRequirement",
                     {"resource_type": r_rtype, "min_value": r_min, "unit": r_unit})
            add_node(n_id, n_name, "NodeProfile",
                     {"vcpu": n_vcpu, "ram_gb": n_ram, "ports": n_ports,
                      "storage_gb": n_stor, "role": n_role})
            if dp_id:
                add_node(dp_id, dp_name, "DeploymentPattern",
                         {"topology_label": dp_topo, "description": dp_desc})

            # Edges — deduplicated by source+target+type
            def edge_key(s, t, et): return f"{s}__{t}__{et}"

            for src, tgt, etype, props in [
                (m_id,  f_id,  "HAS_FEATURE",  {}),
                (f_id,  o_id,  "IMPLIES",      {"base_weight": i_weight}),
                (o_id,  r_id,  "REQUIRES",     {"priority": req_pri}),
                (r_id,  n_id,  "SATISFIED_BY", {"fit_score": sat_fit}),
            ]:
                if src and tgt:
                    ek = edge_key(src, tgt, etype)
                    if not any(e.get("_key") == ek for e in edges):
                        edges.append({"source": src, "target": tgt,
                                      "type": etype, "_key": ek, **props})

            if dp_id and n_id:
                ek = edge_key(n_id, dp_id, "FITS_PATTERN")
                if not any(e.get("_key") == ek for e in edges):
                    edges.append({"source": n_id, "target": dp_id,
                                  "type": "FITS_PATTERN", "_key": ek})

        # Strip internal _key before returning
        for e in edges:
            e.pop("_key", None)

        return {"nodes": list(nodes_map.values()), "edges": edges}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch chain for router '%s'", router_id)
        raise HTTPException(status_code=500, detail="Failed to fetch reasoning chain.")


@router.post(
    "/graph/explain",
    summary="LLM explanation of a graph relationship path",
    responses={401: {"model": ErrorResponse}},
)
def graph_explain(body: ExplainRequest, _key: str = Depends(verify_api_key)):
    """
    Accepts a resolved path (nodes + edges) and returns an LLM-generated
    plain-English explanation using the same model as the deployment explainer.
    Requires API key to prevent unbounded LLM cost from anonymous callers.
    """
    from engine.explainer import explain_relationship
    try:
        text = explain_relationship(
            path_nodes=body.nodes,
            path_edges=body.edges,
        )
        return {"explanation": text}
    except Exception:
        logger.exception("Explain relationship failed")
        raise HTTPException(status_code=500, detail="Explanation generation failed.")


@router.get(
    "/graph/nodes",
    summary="Return all graph nodes with raw IDs for the Relationship Explorer",
)
def graph_nodes(graph=Depends(get_graph)):
    try:
        result = graph.query(
            "MATCH (n) WHERE exists(n.id) "
            "RETURN labels(n)[0], n.id, n.name, "
            "n.vcpu, n.ram_gb, n.ports, n.storage_gb, n.role, "
            "n.severity, n.resource_type, n.min_value, n.unit, "
            "n.vendor, n.series, n.value, n.category "
            "LIMIT 500"
        )
        nodes = []
        seen = set()
        for r in result.result_set:
            ntype, nid, name = r[0], r[1], r[2]
            if not nid or nid in seen:
                continue
            seen.add(nid)
            nodes.append({
                "id":            nid,
                "label":         name or nid,
                "type":          ntype or "Unknown",
                "vcpu":          r[3],
                "ram_gb":        r[4],
                "ports":         r[5],
                "storage_gb":    r[6],
                "role":          r[7],
                "severity":      r[8],
                "resource_type": r[9],
                "min_value":     r[10],
                "unit":          r[11],
                "vendor":        r[12],
                "series":        r[13],
                "value":         r[14],
                "category":      r[15],
            })
        nodes.sort(key=lambda n: (n["type"], n["label"]))
        return nodes
    except Exception:
        logger.exception("Failed to fetch graph nodes")
        raise HTTPException(status_code=500, detail="Failed to fetch graph nodes.")


@router.get(
    "/graph/path",
    summary="Find shortest path between two graph nodes",
)
def graph_path(source_id: str, target_id: str, graph=Depends(get_graph)):
    try:
        result = graph.query(
            "MATCH (src {id: $src}), (tgt {id: $tgt}) "
            "WITH src, tgt "
            "RETURN shortestPath((src)-[*]->(tgt))",
            {"src": source_id, "tgt": target_id},
        )

        if not result.result_set or result.result_set[0][0] is None:
            return {"path": [], "nodes": [], "edges": []}

        path = result.result_set[0][0]
        raw_nodes = path.nodes()
        raw_edges = path.edges()

        nodes_out = []
        for n in raw_nodes:
            p = n.properties
            nodes_out.append({
                "id":            p.get("id") or str(n.id),
                "label":         p.get("name") or p.get("id") or str(n.id),
                "type":          n.labels[0] if n.labels else "Unknown",
                "vcpu":          p.get("vcpu"),
                "ram_gb":        p.get("ram_gb"),
                "ports":         p.get("ports"),
                "storage_gb":    p.get("storage_gb"),
                "role":          p.get("role"),
                "severity":      p.get("severity"),
                "resource_type": p.get("resource_type"),
                "min_value":     p.get("min_value"),
                "unit":          p.get("unit"),
                "vendor":        p.get("vendor"),
                "series":        p.get("series"),
            })

        path_ids = [n["id"] for n in nodes_out]

        edges_out = []
        for i, e in enumerate(raw_edges):
            p = e.properties
            edges_out.append({
                "source":      path_ids[i],
                "target":      path_ids[i + 1],
                "type":        e.relation,
                "base_weight": p.get("base_weight"),
                "fit_score":   p.get("fit_score"),
                "priority":    p.get("priority"),
            })

        return {"path": path_ids, "nodes": nodes_out, "edges": edges_out}
    except Exception:
        logger.exception("Graph path query failed")
        raise HTTPException(status_code=500, detail="Graph path query failed.")


@router.get(
    "/graph/data",
    summary="Return full graph nodes and edges for visualization",
)
def graph_data(graph=Depends(get_graph)):
    try:
        result = graph.query(
            "MATCH (n)-[r]->(m) "
            "RETURN labels(n)[0], n.id, n.name, n.severity, n.resource_type, "
            "n.min_value, n.unit, n.vcpu, n.ram_gb, n.ports, n.storage_gb, n.role, "
            "type(r), r.base_weight, r.priority, r.fit_score, "
            "labels(m)[0], m.id, m.name "
            "LIMIT 500"
        )

        nodes_map = {}
        links = []

        def add_node(label, nid, name, row_slice):
            key = f"{label}_{nid or name}"
            if key not in nodes_map:
                nodes_map[key] = {
                    "id":    key,
                    "label": name or nid or key,
                    "type":  label,
                    "severity":      row_slice[0],
                    "resource_type": row_slice[1],
                    "min_value":     row_slice[2],
                    "unit":          row_slice[3],
                    "vcpu":          row_slice[4],
                    "ram_gb":        row_slice[5],
                    "ports":         row_slice[6],
                    "storage_gb":    row_slice[7],
                    "role":          row_slice[8],
                }
            return key

        for row in result.result_set:
            src_label, src_id, src_name = row[0], row[1], row[2]
            src_props = row[3:12]
            rel_type, base_weight, priority, fit_score = row[12], row[13], row[14], row[15]
            dst_label, dst_id, dst_name = row[16], row[17], row[18]

            src_key = add_node(src_label or "Unknown", src_id, src_name, src_props)
            dst_key = add_node(dst_label or "Unknown", dst_id, dst_name, [None]*9)
            links.append({
                "source":      src_key,
                "target":      dst_key,
                "label":       rel_type,
                "base_weight": base_weight,
                "priority":    priority,
                "fit_score":   fit_score,
            })

        return {"nodes": list(nodes_map.values()), "links": links}
    except Exception:
        logger.exception("Failed to fetch graph data")
        raise HTTPException(status_code=500, detail="Failed to fetch graph data.")


# ── Serialization ─────────────────────────────────────────────────────────────

def _serialize(dp: DeploymentPlan) -> DeploymentPlanResponse:
    clusters = [
        ClusterSpecResponse(
            cluster_id=c.cluster_id,
            topology_type=c.topology_type,
            node_count=c.node_count,
            total_vcpu=c.total_vcpu,
            total_ram_gb=c.total_ram_gb,
            total_ports=c.total_ports,
            nodes=[
                NodeSpecResponse(
                    node_id=n.node_id,
                    role=n.role,
                    vcpu=n.vcpu,
                    ram_gb=n.ram_gb,
                    ports=n.ports,
                    storage_gb=n.storage_gb,
                    profile_name=n.profile_name,
                )
                for n in c.nodes
            ],
        )
        for c in dp.clusters
    ]
    c = dp.confidence
    confidence_resp = ConfidenceResponse(
        score=c.score,
        label=c.label,
        signal_strength=c.signal_strength,
        graph_match=c.graph_match,
        constraint_clean=c.constraint_clean,
        profile_fit=c.profile_fit,
        feature_coverage=c.feature_coverage,
        breakdown=c.breakdown,
    ) if c else None

    # Build graph_ids: the node keys that were part of this plan's reasoning path
    # Key format matches add_node() in graph_data: "{Label}_{id or name}"
    graph_ids: list[str] = []
    graph_ids.append(f"RouterModel_{dp.router_id}")
    for c in dp.clusters:
        for n in c.nodes:
            graph_ids.append(f"NodeProfile_{n.profile_name}")
    if dp.pattern_name and dp.pattern_name not in ("fallback",):
        graph_ids.append(f"DeploymentPattern_{dp.pattern_name}")
    graph_ids = list(dict.fromkeys(graph_ids))  # deduplicate, preserve order

    return DeploymentPlanResponse(
        router_id=dp.router_id,
        router_name=getattr(dp, "router_name", dp.router_id),
        plan_status=getattr(dp, "plan_status", "ok"),
        plan_status_reason=getattr(dp, "plan_status_reason", ""),
        valid=dp.valid,
        cluster_count=dp.cluster_count,
        topology_type=dp.topology_type,
        ha_enabled=dp.ha_enabled,
        clusters=clusters,
        warnings=dp.warnings,
        violations=dp.violations,
        reasoning=dp.reasoning,
        explanation=dp.explanation,
        simple_explanation=getattr(dp, "simple_explanation", ""),
        similarity_score=getattr(dp, "similarity_score", 1.0),
        similar_to=getattr(dp, "similar_to", None),
        confidence=confidence_resp,
        data_quality_score=getattr(dp, "data_quality_score", 1.0),
        pattern_name=getattr(dp, "pattern_name", ""),
        pattern_description=getattr(dp, "pattern_description", ""),
        graph_ids=graph_ids,
    )
