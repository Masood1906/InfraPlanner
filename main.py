# main.py
# Entry point: python main.py  →  start FastAPI server

import logging
import os
from dotenv import load_dotenv
from graph.queries import (
    get_implications_for_router,
    get_requirements_for_implications,
    get_node_profiles_for_requirements,
    build_implications_from_weights,
)
from parser.input_parser import parse
from parser.validator import validate_spec
from parser.agentic_validator import check_router, AGENTIC_TRIGGER_SIMILARITY
from parser.entity_mapper import map_to_graph
from engine.inference import infer
from engine.constraint_validator import validate
from engine.deployment_planner import plan
from engine.explainer import explain, explain_simple

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Data quality gate ─────────────────────────────────────────────────────────
# Threshold below which we skip inference entirely and return an empty plan.
# Computed from signals available BEFORE inference — no graph traversal needed.
# Completely name-agnostic: based only on similarity score and feature ranges.
_DATA_QUALITY_THRESHOLD = 0.40


def _compute_data_quality(mapping: dict, spec) -> tuple[float, str]:
    """
    Compute a data_quality_score (0.0–1.0) from pre-inference signals.
    Returns (score, reason_string).  reason is "" when score passes.

    Two equal-weight components:

    similarity_score (0.5 weight)
        How well the submitted router matched the knowledge graph.
        0.0 = no match at all.  1.0 = exact known router.
        An unknown router with 0% similarity has no topology hint and
        no graph-derived weights — inference runs on seed-floor defaults only.

    feature_quality (0.5 weight)
        Fraction of the 4 required features that are within the known
        reference range.  A feature below minimum normalises to 0.0 and
        contributes nothing to inference signals.
        4/4 in range → 1.0.  0/4 in range → 0.0.
    """
    from parser.normalizer import FEATURE_RANGES

    sim       = float(mapping.get("similarity_score", 0.0))
    sim_score = min(max(sim, 0.0), 1.0)

    required_names = {"Switching Capacity", "Forwarding Rate", "IPv4 Routes", "DRAM"}
    feat_map = {f.name: f for f in spec.features}
    in_range = 0
    checked  = 0
    for name in required_names:
        feat = feat_map.get(name)
        if feat is None or name not in FEATURE_RANGES:
            continue
        lo, _ = FEATURE_RANGES[name]
        checked += 1
        if feat.canonical_value >= lo:
            in_range += 1
    feature_quality = (in_range / checked) if checked > 0 else 0.0

    score = round(0.5 * sim_score + 0.5 * feature_quality, 4)

    if score >= _DATA_QUALITY_THRESHOLD:
        return score, ""

    # Build a specific, actionable reason message
    parts = []
    if sim_score == 0.0:
        parts.append("no similar router found in the knowledge graph (0% match)")
    elif sim_score < 0.30:
        parts.append(f"very low graph similarity ({sim_score:.0%})")

    if feature_quality < 1.0:
        below = [
            name for name in required_names
            if name in feat_map
            and name in FEATURE_RANGES
            and feat_map[name].canonical_value < FEATURE_RANGES[name][0]
        ]
        if below:
            parts.append(
                f"{len(below)} required feature(s) below known minimum "
                f"({', '.join(below)})"
            )

    reason = (
        "Cannot generate a reliable deployment plan: "
        + (" and ".join(parts) if parts else "input quality too low")
        + ". Please verify your specifications are for a real network device."
    )
    return score, reason


def _empty_plan(spec, mapping: dict, data_quality_score: float, reason: str):
    """
    Return a DeploymentPlan with no clusters when data quality is too low.
    plan_status = "needs_review" signals the frontend to show the rejection panel.
    """
    from engine.deployment_planner import DeploymentPlan
    dp = DeploymentPlan(
        router_id=spec.router_id,
        clusters=[],
        topology_type="",
        ha_enabled=False,
        reasoning=[
            f"[Skipped] Data quality score {data_quality_score:.2f} is below "
            f"threshold {_DATA_QUALITY_THRESHOLD}. Inference was not run."
        ],
        warnings=(
            list(mapping.get("warnings", []))
            + [rw.message for rw in spec.range_warnings]
        ),
        violations=[],
        valid=False,
        plan_status="needs_review",
        plan_status_reason=reason,
        data_quality_score=data_quality_score,
    )
    dp.router_name      = spec.model
    dp.similarity_score = mapping.get("similarity_score", 0.0)
    dp.similar_to       = mapping.get("similar_to")
    return dp


def run_pipeline(graph, raw_spec: dict, persist: bool = False):
    # ── Parse + Validate + Map ────────────────────────────────────────────────
    spec    = parse(raw_spec)
    validate_spec(spec)          # raises ValueError for junk/impossible inputs
    mapping = map_to_graph(graph, spec, persist=persist)

    logger.info(
        "Parser: %s (id=%s, new=%s, similar=%s, similarity=%.2f)",
        spec.model, spec.router_id,
        mapping["is_new"], mapping["is_similar"], mapping["similarity_score"],
    )
    for w in mapping.get("warnings", []):
        logger.warning("Mapper: %s", w)
    for rw in spec.range_warnings:
        logger.warning("Range: %s", rw.message)

    # ── Layer 1.5: Agentic validation ─────────────────────────────────────────
    # Fires only for unknown/low-similarity routers (similarity < 0.30).
    # Checks both identity (is this a real router?) and spec consistency
    # (do the numbers make sense for the claimed model?).
    # Known routers skip this entirely — zero LLM cost for normal usage.
    feat_map = {f.name: f for f in spec.features}
    agentic_verdict = check_router(
        model_name=spec.model,
        vendor=spec.vendor,
        switching_cap_gbps=feat_map.get("Switching Capacity").canonical_value
            if feat_map.get("Switching Capacity") else 0.0,
        forwarding_rate_mpps=feat_map.get("Forwarding Rate").canonical_value
            if feat_map.get("Forwarding Rate") else 0.0,
        ipv4_routes=feat_map.get("IPv4 Routes").canonical_value
            if feat_map.get("IPv4 Routes") else 0.0,
        dram_gb=feat_map.get("DRAM").canonical_value
            if feat_map.get("DRAM") else 0.0,
        similarity_score=mapping["similarity_score"],
    )
    if agentic_verdict.should_reject:
        raise ValueError(agentic_verdict.rejection_message)

    # ── Data quality gate ─────────────────────────────────────────────────────
    # Runs before graph traversal and inference.  If the input does not meet
    # the minimum quality threshold, return an empty plan immediately.
    # This prevents misleading cluster architectures for unknown/junk routers.
    dq_score, dq_reason = _compute_data_quality(mapping, spec)
    if dq_score < _DATA_QUALITY_THRESHOLD:
        logger.warning(
            "Data quality gate: router='%s' score=%.2f — skipping inference. %s",
            spec.router_id, dq_score, dq_reason,
        )
        return _empty_plan(spec, mapping, dq_score, dq_reason)

    # ── Graph Traversal ───────────────────────────────────────────────────────
    implications = get_implications_for_router(graph, mapping["router_id"])

    if not implications and mapping["is_new"]:
        implications = build_implications_from_weights(mapping["implied_weights"])

    impl_ids     = [i["id"] for i in implications]
    requirements = get_requirements_for_implications(graph, impl_ids)
    req_ids      = [r["id"] for r in requirements]
    profiles     = get_node_profiles_for_requirements(graph, req_ids)

    # ── Infer → Validate → Plan → Explain ────────────────────────────────────
    inference_result  = infer(
        mapping["router_id"], implications, requirements, profiles,
        instance_weights=mapping["implied_weights"],
    )
    validation_result = validate(inference_result)
    deployment_plan   = plan(inference_result, validation_result, graph=graph)

    deployment_plan.router_id        = spec.router_id
    deployment_plan.router_name      = spec.model
    deployment_plan.warnings.extend(mapping.get("warnings", []))
    deployment_plan.warnings.extend([rw.message for rw in spec.range_warnings])
    deployment_plan.similarity_score = mapping["similarity_score"]
    deployment_plan.similar_to       = mapping["similar_to"]
    deployment_plan.data_quality_score = dq_score

    from engine.confidence import compute_confidence
    deployment_plan.confidence = compute_confidence(
        inference_result,
        validation_result,
        similarity_score=mapping["similarity_score"],
        submitted_feature_names=[f.name for f in spec.features],
        all_profiles=profiles,
        range_warning_count=sum(
            1 for rw in spec.range_warnings
            if rw.direction == "below_minimum"
        ),
    )
    deployment_plan.explanation        = explain(deployment_plan)
    deployment_plan.simple_explanation = explain_simple(deployment_plan)

    _log_plan(deployment_plan)
    return deployment_plan


def _log_plan(dp):
    status = "VALID" if dp.valid else "INVALID"
    similar_note = (
        f"  matched→{dp.similar_to} ({dp.similarity_score:.2f})"
        if getattr(dp, "similar_to", None) else ""
    )
    logger.info("Plan [%s] router=%s%s topology=%s clusters=%d ha=%s",
                status, dp.router_id, similar_note,
                dp.topology_type, dp.cluster_count, dp.ha_enabled)
    if dp.confidence:
        c = dp.confidence
        logger.info(
            "Confidence: %.2f [%s] signal=%.2f graph=%.2f constraints=%.2f fit=%.2f",
            c.score, c.label, c.signal_strength,
            c.graph_match, c.constraint_clean, c.profile_fit,
        )
    for w in dp.warnings:
        logger.warning("Plan warning: %s", w)
    for v in dp.violations:
        logger.error("Plan violation: %s", v)


if __name__ == "__main__":
    import uvicorn
    from api.app import create_app
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.getenv("API_PORT", 8000)))
