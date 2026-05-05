# engine/confidence.py
# Computes a confidence score (0.0 – 1.0) for a deployment plan.
#
# Five signals, each normalized to [0.0, 1.0]:
#
#   signal_strength  — average implication weight across all resource targets.
#                      Strong signals → high confidence in demand targets.
#
#   graph_match      — how well the router matched graph knowledge.
#                      1.0 = exact known router.
#                      similarity_score = unknown router matched via cosine similarity.
#                      0.0 = no match found, pure feature inference.
#
#   constraint_clean — penalises auto-fixes applied by the constraint validator.
#                      Each warning reduces confidence by 0.1 (floor 0.0).
#                      Violations reduce by 0.2 each.
#
#   profile_fit      — average fit_score of selected node profiles, normalized
#                      against the maximum possible fit in the profile set.
#                      Dynamic cap — never breaks when new profiles are added.
#                      (FIX-04: was hardcoded to 5.4)
#
#   feature_coverage — ratio of submitted feature names that are recognized
#                      by the inference engine's implication map.
#                      A router with 7 recognized features has higher coverage
#                      than one with 2, even if both produce valid plans.
#                      (IMPROVE-03: new component)

from dataclasses import dataclass
from engine.inference import InferenceResult, NodeSelection
from engine.constraint_validator import ValidationResult

# Weights must sum to 1.0
# Rebalanced: profile_fit raised (most direct hardware match signal),
# signal_strength and graph_match reduced (they are correlated for known routers).
WEIGHTS = {
    "signal_strength":  0.20,
    "graph_match":      0.25,
    "constraint_clean": 0.25,
    "profile_fit":      0.20,
    "feature_coverage": 0.10,
}

CONFIDENCE_LABELS = {
    (0.85, 1.01): "HIGH",
    (0.65, 0.85): "MEDIUM",
    (0.40, 0.65): "LOW",
    (0.00, 0.40): "VERY LOW",
}

# All feature names recognized by the inference engine's implication map.
# Derived from graph/weight_engine.py FEATURE_IMPLICATION_MAP.
# Used to compute feature_coverage without importing the full weight engine
# at confidence-score time (keeps this module dependency-free).
_KNOWN_FEATURE_NAMES: frozenset[str] = frozenset({
    "Forwarding Rate",
    "Switching Capacity",
    "Stacking Bandwidth",
    "IPv4 Routes",
    "MAC Addresses",
    "VLAN IDs",
    "DRAM",
})


@dataclass
class ConfidenceScore:
    score:            float
    label:            str
    signal_strength:  float
    graph_match:      float
    constraint_clean: float
    profile_fit:      float
    feature_coverage: float       # new (IMPROVE-03)
    breakdown:        list[str]


def compute_confidence(
    inference_result: InferenceResult,
    validation_result: ValidationResult,
    similarity_score: float = 1.0,
    submitted_feature_names: list[str] | None = None,
    all_profiles: list[dict] | None = None,
    range_warning_count: int = 0,
) -> ConfidenceScore:
    """
    Compute a weighted confidence score from five independent signals.

    Parameters
    ----------
    inference_result         : output of engine.inference.infer()
    validation_result        : output of engine.constraint_validator.validate()
    similarity_score         : 1.0 for known routers, cosine score for unknown
    submitted_feature_names  : list of feature names from the parsed spec
    all_profiles             : full profile list from graph query
    range_warning_count      : number of below-minimum range warnings from the
                               parser. Each one means a required feature's signal
                               is completely absent — penalised like a cap warning.
    """
    breakdown = []

    # ── Signal strength ───────────────────────────────────────────────────────
    if inference_result.resource_targets:
        avg_signal = sum(
            t.signal_strength for t in inference_result.resource_targets
        ) / len(inference_result.resource_targets)
        signal_score = round(min(avg_signal / 3.0, 1.0), 4)
    else:
        avg_signal   = 0.0
        signal_score = 0.0

    breakdown.append(
        f"signal_strength={signal_score:.2f} "
        f"(avg implication signal={avg_signal:.3f})"
    )

    # ── Graph match ───────────────────────────────────────────────────────────
    graph_score = round(min(max(similarity_score, 0.0), 1.0), 4)
    if similarity_score >= 1.0:
        breakdown.append("graph_match=1.00 (exact known router)")
    elif similarity_score > 0:
        breakdown.append(
            f"graph_match={graph_score:.2f} "
            f"(unknown router, cosine similarity={similarity_score:.2f})"
        )
    else:
        breakdown.append("graph_match=0.00 (no graph match, feature-only inference)")

    # ── Constraint cleanliness ────────────────────────────────────────────────
    # Three classes of penalty, worst to least:
    #   range_warnings  — feature value below known minimum: signal is completely
    #                     absent. The plan is built on seed-floor defaults, not
    #                     the router's actual specs. Deduct 0.20 each.
    #   cap_warnings    — node count capped: plan may be under-provisioned. 0.15.
    #   other_warnings  — general data quality issues. 0.10.
    #   violations      — hard constraint failures. 0.20.
    cap_warnings   = sum(1 for w in validation_result.warnings if "capped" in w.lower())
    other_warnings = len(validation_result.warnings) - cap_warnings
    violation_count = len(validation_result.violations)
    constraint_score = round(
        max(0.0, 1.0
            - (range_warning_count * 0.20)
            - (cap_warnings        * 0.15)
            - (other_warnings      * 0.10)
            - (violation_count     * 0.20)),
        4,
    )
    breakdown.append(
        f"constraint_clean={constraint_score:.2f} "
        f"({range_warning_count} range warnings, {cap_warnings} cap warnings, "
        f"{other_warnings} other warnings, {violation_count} violations)"
    )

    # ── Profile fit ───────────────────────────────────────────────────────────
    # Normalization cap is computed dynamically from the actual profile data
    # so adding new profiles never silently breaks this score. (FIX-04)
    real_selections = [
        s for s in validation_result.adjusted_selections
        if s.fit_score > 0
    ]
    if real_selections:
        avg_fit = sum(s.fit_score for s in real_selections) / len(real_selections)
        # Dynamic cap: max total_fit across all profiles returned by the graph.
        # Falls back to avg_fit itself (score=1.0) when no profile list provided,
        # which is safe because it means only one profile was ever considered.
        max_possible_fit = (
            max((float(p["total_fit"]) for p in all_profiles), default=avg_fit)
            if all_profiles
            else avg_fit
        )
        fit_score = round(min(avg_fit / max(max_possible_fit, 1e-9), 1.0), 4)
    else:
        avg_fit   = 0.0
        fit_score = 0.0

    breakdown.append(
        f"profile_fit={fit_score:.2f} (avg profile fit_score={avg_fit:.2f})"
        if real_selections else "profile_fit=0.00 (no profiles selected)"
    )

    # ── Feature coverage ──────────────────────────────────────────────────────
    # Ratio of submitted features that are recognized by the inference engine.
    # A router with 7 recognized features has more information than one with 2.
    # (IMPROVE-03)
    if submitted_feature_names:
        recognized = sum(
            1 for name in submitted_feature_names
            if name in _KNOWN_FEATURE_NAMES
        )
        coverage_score = round(
            min(recognized / max(len(_KNOWN_FEATURE_NAMES), 1), 1.0), 4
        )
        breakdown.append(
            f"feature_coverage={coverage_score:.2f} "
            f"({recognized}/{len(_KNOWN_FEATURE_NAMES)} features recognized)"
        )
    else:
        coverage_score = 0.5   # neutral when feature names not provided
        breakdown.append("feature_coverage=0.50 (feature names not provided)")

    # ── Weighted composite ────────────────────────────────────────────────────
    score = round(
        signal_score     * WEIGHTS["signal_strength"]  +
        graph_score      * WEIGHTS["graph_match"]       +
        constraint_score * WEIGHTS["constraint_clean"]  +
        fit_score        * WEIGHTS["profile_fit"]       +
        coverage_score   * WEIGHTS["feature_coverage"],
        4,
    )

    label = next(
        lbl for (lo, hi), lbl in CONFIDENCE_LABELS.items()
        if lo <= score < hi
    )

    return ConfidenceScore(
        score=score,
        label=label,
        signal_strength=signal_score,
        graph_match=graph_score,
        constraint_clean=constraint_score,
        profile_fit=fit_score,
        feature_coverage=coverage_score,
        breakdown=breakdown,
    )
