# parser/entity_mapper.py
# Graph is READ-ONLY during normal inference.
#
# Three paths:
#   A) Known router   → compute instance weights from own feature values.
#   B) Unknown router → compute implications directly from own feature values
#                       via weight_engine (no subgraph borrowing).
#                       Similarity match used ONLY to hint deployment pattern.
#   C) Persist mode   → explicit admin call only. Creates permanent nodes.
#
# The graph is NEVER written to during a normal POST /plan request.
# Every router — known or unknown — is reasoned about using its OWN values.
#
# SECURITY: All graph writes use parameterized queries — no f-string interpolation
# of user-supplied values into Cypher strings.
#
# FIX-06: Cosine similarity uses union of all feature dimensions (zero-imputation)
# so partial submissions are penalized for missing features instead of being
# artificially inflated by the intersection-only approach.

import logging
import math
from parser.input_parser import ParsedSpec, ParsedFeature
from parser.normalizer import normalize, FEATURE_RANGES
from graph.weight_engine import FEATURE_IMPLICATION_MAP as _FIM, PHYSICAL_CEILINGS, compute_edge_weight
from graph.router_registry import save as registry_save, spec_to_entry

logger = logging.getLogger(__name__)

FEATURE_IMPLICATION_MAP: list[tuple[str, str]] = _FIM

FEATURE_CATEGORIES: dict[str, str] = {
    "Forwarding Rate":    "processing",
    "Switching Capacity": "networking",
    "Stacking Bandwidth": "networking",
    "VLAN IDs":           "routing",
    "MAC Addresses":      "routing",
    "IPv4 Routes":        "routing",
    "DRAM":               "memory",
}

SIMILARITY_THRESHOLD = 0.6

# Vendor penalty applied when submitted vendor does not match the known router's vendor.
# Prevents a Juniper router from scoring 1.0 similarity against a Cisco router.
# The penalty multiplies the raw cosine score: score *= (1 - VENDOR_PENALTY).
VENDOR_PENALTY = 0.25

# Scale penalty: applied when the submitted router's feature magnitudes differ
# significantly from the matched router. Computed as the ratio of L2 norms.
# Prevents a router with 10x the forwarding rate from scoring 1.0 against a
# smaller router just because the normalized direction vectors are similar.
SCALE_PENALTY_WEIGHT = 0.15


def map_to_graph(graph, spec: ParsedSpec, persist: bool = False) -> dict:
    """
    Map a router spec to graph knowledge.

    persist=False (default): read-only. Unknown routers use similarity matching.
    persist=True: admin mode. Creates permanent nodes for unknown routers.

    Returns:
        router_id        — effective router id used for graph traversal
        is_new           — True if router was not in graph
        is_similar       — True if an unknown router matched a known one
        similar_to       — id of the matched known router (if applicable)
        similarity_score — cosine similarity to matched router (0-1)
        implied_weights  — {implication_id: instance_weight}
        warnings         — list of data quality warnings
    """
    warnings = []
    is_new = not _router_exists(graph, spec.router_id)

    if not is_new:
        if persist:
            registry_saved = registry_save(spec_to_entry(spec))
            if registry_saved:
                logger.info("Registry: saved router '%s' to router_registry.json", spec.router_id)
        return {
            "router_id":        spec.router_id,
            "is_new":           False,
            "is_similar":       False,
            "similar_to":       None,
            "similarity_score": 1.0,
            "implied_weights":  _compute_instance_weights(spec),
            "warnings":         warnings,
        }

    if persist:
        # Always write to registry first — before touching the graph.
        # This ensures the router survives a graph wipe even if the graph
        # write partially fails. registry_save is idempotent (no-op if
        # already present), so calling it when the router already exists
        # in the graph is safe and correct.
        registry_saved = registry_save(spec_to_entry(spec))
        if registry_saved:
            logger.info("Registry: saved router '%s' to router_registry.json", spec.router_id)
        else:
            logger.info("Registry: router '%s' already in router_registry.json (no-op)", spec.router_id)

        # Write to graph regardless of whether registry_save was a no-op.
        # The router may already be in the graph (from a previous session)
        # but we still need to ensure all nodes and edges exist (MERGE is safe).
        _create_router(graph, spec)
        _create_features(graph, spec)
        _wire_has_feature(graph, spec)
        _wire_implies(graph, spec)
        logger.info("Graph: persisted router '%s' nodes and edges", spec.router_id)
        return {
            "router_id":        spec.router_id,
            "is_new":           True,
            "is_similar":       False,
            "similar_to":       None,
            "similarity_score": 1.0,
            "implied_weights":  _compute_instance_weights(spec),
            "warnings":         warnings,
        }

    match = _find_similar_router(graph, spec)
    similar_id, score = match if match else (None, 0.0)

    if similar_id is None:
        warnings.append(
            f"Router '{spec.model}' is unknown and no similar router found. "
            f"Inferring entirely from submitted feature values."
        )
    elif score < SIMILARITY_THRESHOLD:
        warnings.append(
            f"Router '{spec.model}' loosely resembles '{similar_id}' "
            f"({score:.2f} similarity) but inference uses its own feature values."
        )
    else:
        warnings.append(
            f"Router '{spec.model}' is unknown. "
            f"Closest known router is '{similar_id}' ({score:.2f} similarity) — "
            f"used only as topology hint. Inference driven by submitted values."
        )

    return {
        "router_id":        spec.router_id,
        "is_new":           True,
        "is_similar":       similar_id is not None,
        "similar_to":       similar_id,
        "similarity_score": score,
        "implied_weights":  _compute_instance_weights(spec),
        "warnings":         warnings,
    }


# ── Similarity matching ────────────────────────────────────────────────────────

def _find_similar_router(graph, spec: ParsedSpec) -> tuple[str, float] | None:
    result = graph.query(
        """
        MATCH (m:RouterModel)-[:HAS_FEATURE]->(f:RouterFeature)
        RETURN m.id AS router_id, m.vendor AS vendor,
               f.name AS feature_name, f.value AS value
        """
    )
    if not result.result_set:
        return None

    known_vectors: dict[str, dict[str, float]] = {}
    known_vendors: dict[str, str] = {}
    known_raw: dict[str, dict[str, float]] = {}   # un-normalized for scale comparison

    for row in result.result_set:
        rid, vendor, fname, fval = row[0], row[1], row[2], float(row[3])
        known_vectors.setdefault(rid, {})[fname] = normalize(fname, fval)
        known_vendors[rid] = (vendor or "").lower().strip()
        known_raw.setdefault(rid, {})[fname] = fval

    input_vector = {
        f.name: normalize(f.name, f.canonical_value)
        for f in spec.features
    }
    input_raw = {f.name: f.canonical_value for f in spec.features}
    submitted_vendor = (spec.vendor or "").lower().strip()

    best_id, best_score = None, -1.0
    for rid, known_vec in known_vectors.items():
        raw_cosine = _cosine_similarity(input_vector, known_vec)

        # Vendor penalty: different vendor → multiply by (1 - VENDOR_PENALTY)
        known_vendor = known_vendors.get(rid, "")
        same_vendor = (
            submitted_vendor and known_vendor and
            (submitted_vendor == known_vendor or
             submitted_vendor.startswith(known_vendor) or
             known_vendor.startswith(submitted_vendor))
        )
        vendor_factor = 1.0 if same_vendor else (1.0 - VENDOR_PENALTY)

        # Scale penalty: penalise when L2 norm ratio is far from 1.0
        # Uses shared feature dimensions only (intersection)
        shared_keys = set(input_raw.keys()) & set(known_raw.get(rid, {}).keys())
        if shared_keys:
            norm_input = sum(input_raw[k] ** 2 for k in shared_keys) ** 0.5
            norm_known = sum(known_raw[rid][k] ** 2 for k in shared_keys) ** 0.5
            if norm_known > 0:
                ratio = norm_input / norm_known
                # ratio=1.0 → no penalty; ratio=10 or 0.1 → max penalty
                scale_divergence = abs(1.0 - min(ratio, 1.0 / ratio if ratio > 0 else 1.0))
                scale_factor = 1.0 - (SCALE_PENALTY_WEIGHT * min(scale_divergence, 1.0))
            else:
                scale_factor = 1.0
        else:
            scale_factor = 1.0

        score = round(raw_cosine * vendor_factor * scale_factor, 4)
        if score > best_score:
            best_score = score
            best_id = rid

    return (best_id, round(best_score, 4)) if best_id is not None else None


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """
    Cosine similarity using the UNION of all feature dimensions.
    Missing features are zero-imputed so partial submissions are penalized
    rather than artificially inflated by the old intersection-only approach.
    (FIX-06)
    """
    all_keys = set(vec_a.keys()) | set(vec_b.keys())
    if not all_keys:
        return 0.0

    a = [vec_a.get(k, 0.0) for k in all_keys]
    b = [vec_b.get(k, 0.0) for k in all_keys]

    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x ** 2 for x in a))
    mag_b = math.sqrt(sum(x ** 2 for x in b))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Instance weight computation ────────────────────────────────────────────────

def _compute_instance_weights(spec: ParsedSpec) -> dict[str, float]:
    """
    Compute instance_weight = log(value+1)/log(ceiling+1) for every
    feature → implication pair. Aggregates by implication_id.
    Never writes to the graph.
    """
    feat_lookup = {f.name: f for f in spec.features}
    totals: dict[str, float] = {}

    for feat_name, impl_id in FEATURE_IMPLICATION_MAP:
        if feat_name not in feat_lookup or feat_name not in PHYSICAL_CEILINGS:
            continue
        feat    = feat_lookup[feat_name]
        ceiling = PHYSICAL_CEILINGS[feat_name]
        weight  = round(math.log(feat.canonical_value + 1) / math.log(ceiling + 1), 4)
        totals[impl_id] = round(totals.get(impl_id, 0.0) + weight, 4)

    return totals


# ── Admin: persist new router to graph (parameterized writes) ─────────────────

def _router_exists(graph, router_id: str) -> bool:
    result = graph.query(
        "MATCH (m:RouterModel {id: $router_id}) RETURN m LIMIT 1",
        {"router_id": router_id},
    )
    return len(result.result_set) > 0


def _create_router(graph, spec: ParsedSpec):
    graph.query(
        """
        MERGE (:RouterModel {
            id:     $router_id,
            name:   $name,
            series: $series,
            vendor: $vendor,
            source: 'user_submitted'
        })
        """,
        {
            "router_id": spec.router_id,
            "name":      spec.model,
            "series":    spec.series,
            "vendor":    spec.vendor,
        },
    )


def _create_features(graph, spec: ParsedSpec):
    for feat in spec.features:
        fid = f"f_{spec.router_id}_{feat.name.lower().replace(' ', '_')}"
        cat = FEATURE_CATEGORIES.get(feat.name, "general")
        graph.query(
            """
            MERGE (:RouterFeature {
                id:       $fid,
                name:     $name,
                category: $category,
                value:    $value,
                unit:     $unit
            })
            """,
            {
                "fid":      fid,
                "name":     feat.name,
                "category": cat,
                "value":    feat.canonical_value,
                "unit":     feat.canonical_unit,
            },
        )


def _wire_has_feature(graph, spec: ParsedSpec):
    for feat in spec.features:
        fid = f"f_{spec.router_id}_{feat.name.lower().replace(' ', '_')}"
        graph.query(
            """
            MATCH (m:RouterModel {id: $router_id}),
                  (f:RouterFeature {id: $fid})
            MERGE (m)-[:HAS_FEATURE]->(f)
            """,
            {"router_id": spec.router_id, "fid": fid},
        )


def _wire_implies(graph, spec: ParsedSpec):
    for feat in spec.features:
        if feat.name not in PHYSICAL_CEILINGS:
            continue
        fid     = f"f_{spec.router_id}_{feat.name.lower().replace(' ', '_')}"
        ceiling = PHYSICAL_CEILINGS[feat.name]
        weight  = round(compute_edge_weight(feat.canonical_value, ceiling), 2)
        for feat_name, impl_id in FEATURE_IMPLICATION_MAP:
            if feat.name == feat_name:
                graph.query(
                    """
                    MATCH (f:RouterFeature {id: $fid}),
                          (o:OperationalImplication {id: $impl_id})
                    MERGE (f)-[i:IMPLIES]->(o)
                    ON CREATE SET i.base_weight = $weight
                    """,
                    {"fid": fid, "impl_id": impl_id, "weight": weight},
                )
