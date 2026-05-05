# tests/test_confidence.py
# Tests for engine/confidence.py covering:
#   FIX-04  — dynamic profile fit normalization cap (no more magic 5.4)
#   IMPROVE-03 — feature_coverage component
#   General — score bounds, label mapping, weight sum, component independence

import pytest
from engine.inference import InferenceResult, ResourceTarget, NodeSelection
from engine.constraint_validator import ValidationResult
from engine.confidence import compute_confidence, WEIGHTS, CONFIDENCE_LABELS, _KNOWN_FEATURE_NAMES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ir(signal: float = 0.0) -> InferenceResult:
    targets = [ResourceTarget("cpu", 32, "vCPU", 32 * (1 + signal), signal)]
    return InferenceResult("test", targets, [], [])


def _make_vr(warnings=0, violations=0, fit=5.4) -> ValidationResult:
    sel = NodeSelection("np_compute_xl", "Compute-XL", "compute",
                        64, 512, 48, 2000, 3, fit, ["cpu"])
    return ValidationResult(
        valid=violations == 0,
        violations=[f"v{i}" for i in range(violations)],
        warnings=[f"w{i}" for i in range(warnings)],
        adjusted_selections=[sel],
    )


def _make_profiles(max_fit: float = 5.4) -> list[dict]:
    return [
        {"id": "np_compute_xl", "name": "Compute-XL", "vcpu": 64, "ram_gb": 512,
         "ports": 48, "storage_gb": 2000, "role": "compute",
         "total_fit": max_fit, "reqs_satisfied": 5, "fit_breakdown": []},
    ]


# ── Weight integrity ──────────────────────────────────────────────────────────

class TestWeightIntegrity:

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)

    def test_all_weight_keys_present(self):
        expected = {"signal_strength", "graph_match", "constraint_clean",
                    "profile_fit", "feature_coverage"}
        assert set(WEIGHTS.keys()) == expected

    def test_all_weights_positive(self):
        for k, v in WEIGHTS.items():
            assert v > 0, f"Weight for {k} must be positive"


# ── Score bounds ──────────────────────────────────────────────────────────────

class TestScoreBounds:

    def test_score_bounded_zero_to_one(self):
        ir = _make_ir(signal=0.0)
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=1.0,
                                submitted_feature_names=list(_KNOWN_FEATURE_NAMES),
                                all_profiles=_make_profiles())
        assert 0.0 <= c.score <= 1.0

    def test_perfect_inputs_give_high_score(self):
        ir = _make_ir(signal=3.0)
        vr = _make_vr(warnings=0, violations=0, fit=5.4)
        c  = compute_confidence(ir, vr, similarity_score=1.0,
                                submitted_feature_names=list(_KNOWN_FEATURE_NAMES),
                                all_profiles=_make_profiles(5.4))
        assert c.score >= 0.65

    def test_worst_inputs_give_low_score(self):
        ir = _make_ir(signal=0.0)
        vr = _make_vr(warnings=5, violations=5, fit=0.1)
        c  = compute_confidence(ir, vr, similarity_score=0.0,
                                submitted_feature_names=[],
                                all_profiles=_make_profiles(5.4))
        assert c.score < 0.5

    def test_no_resource_targets_gives_zero_signal(self):
        ir = InferenceResult("test", [], [], [])
        vr = _make_vr()
        c  = compute_confidence(ir, vr)
        assert c.signal_strength == 0.0

    def test_no_selections_gives_zero_profile_fit(self):
        ir = _make_ir()
        vr = ValidationResult(True, [], [], [])
        c  = compute_confidence(ir, vr)
        assert c.profile_fit == 0.0


# ── Label mapping ─────────────────────────────────────────────────────────────

class TestLabelMapping:

    @pytest.mark.parametrize("score,expected_label", [
        (0.90, "HIGH"),
        (0.85, "HIGH"),
        (0.80, "MEDIUM"),
        (0.65, "MEDIUM"),
        (0.60, "LOW"),
        (0.40, "LOW"),
        (0.39, "VERY LOW"),
        (0.00, "VERY LOW"),
    ])
    def test_label_matches_score_range(self, score, expected_label):
        label = next(
            lbl for (lo, hi), lbl in CONFIDENCE_LABELS.items()
            if lo <= score < hi
        )
        assert label == expected_label

    def test_returned_label_matches_returned_score(self):
        ir = _make_ir(signal=1.0)
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=0.8,
                                all_profiles=_make_profiles())
        expected = next(
            lbl for (lo, hi), lbl in CONFIDENCE_LABELS.items()
            if lo <= c.score < hi
        )
        assert c.label == expected


# ── FIX-04: Dynamic profile fit cap ──────────────────────────────────────────

class TestDynamicFitCap:

    def test_profile_fit_never_exceeds_one(self):
        """profile_fit must be ≤ 1.0 regardless of fit_score value."""
        vr = _make_vr(fit=5.4)
        ir = _make_ir()
        c  = compute_confidence(ir, vr, all_profiles=_make_profiles(max_fit=5.4))
        assert c.profile_fit <= 1.0

    def test_profile_fit_is_one_when_selection_equals_max(self):
        """When the selected profile has the maximum fit, score should be 1.0."""
        vr = _make_vr(fit=5.4)
        ir = _make_ir()
        c  = compute_confidence(ir, vr, all_profiles=_make_profiles(max_fit=5.4))
        assert c.profile_fit == pytest.approx(1.0, abs=1e-4)

    def test_higher_max_fit_reduces_profile_fit_score(self):
        """Adding a profile with higher total_fit lowers the normalized score."""
        vr = _make_vr(fit=5.4)
        ir = _make_ir()

        profiles_normal = _make_profiles(max_fit=5.4)
        profiles_augmented = _make_profiles(max_fit=5.4) + [
            {"id": "np_super", "name": "Super", "vcpu": 128, "ram_gb": 1024,
             "ports": 128, "storage_gb": 8000, "role": "compute",
             "total_fit": 10.0, "reqs_satisfied": 10, "fit_breakdown": []}
        ]

        c_normal    = compute_confidence(ir, vr, all_profiles=profiles_normal)
        c_augmented = compute_confidence(ir, vr, all_profiles=profiles_augmented)

        assert c_augmented.profile_fit < c_normal.profile_fit

    def test_no_profiles_provided_falls_back_safely(self):
        """When all_profiles=None, profile_fit must still be in [0, 1]."""
        vr = _make_vr(fit=5.4)
        ir = _make_ir()
        c  = compute_confidence(ir, vr, all_profiles=None)
        assert 0.0 <= c.profile_fit <= 1.0

    def test_magic_5_4_no_longer_hardcoded(self):
        """
        If we add a profile with total_fit=8.0, the old hardcoded 5.4 cap
        would give profile_fit > 1.0 for that profile. The dynamic cap must
        prevent this.
        """
        sel = NodeSelection("np_super", "Super", "compute",
                            128, 1024, 128, 8000, 1, 8.0, ["cpu"])
        vr = ValidationResult(True, [], [], [sel])
        ir = _make_ir()
        profiles = [
            {"id": "np_super", "name": "Super", "vcpu": 128, "ram_gb": 1024,
             "ports": 128, "storage_gb": 8000, "role": "compute",
             "total_fit": 8.0, "reqs_satisfied": 8, "fit_breakdown": []}
        ]
        c = compute_confidence(ir, vr, all_profiles=profiles)
        assert c.profile_fit <= 1.0


# ── IMPROVE-03: Feature coverage ─────────────────────────────────────────────

class TestFeatureCoverage:

    def test_all_known_features_gives_coverage_one(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr,
                                submitted_feature_names=list(_KNOWN_FEATURE_NAMES))
        assert c.feature_coverage == pytest.approx(1.0, abs=1e-4)

    def test_no_features_gives_neutral_coverage(self):
        """
        Empty list [] is falsy in Python, so `if submitted_feature_names:` is False.
        Both [] and None fall through to the neutral 0.5 sentinel — this is
        intentional: we cannot distinguish "submitted zero features" from
        "caller did not pass feature names" at the confidence layer.
        """
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, submitted_feature_names=[])
        assert c.feature_coverage == pytest.approx(0.5, abs=1e-4)

    def test_none_features_gives_neutral_0_5(self):
        """None (not provided) → neutral 0.5 sentinel."""
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, submitted_feature_names=None)
        assert c.feature_coverage == pytest.approx(0.5, abs=1e-4)

    def test_partial_features_gives_partial_coverage(self):
        ir = _make_ir()
        vr = _make_vr()
        # Submit 4 of 7 known features
        partial = ["Forwarding Rate", "Switching Capacity", "DRAM", "IPv4 Routes"]
        c = compute_confidence(ir, vr, submitted_feature_names=partial)
        expected = 4 / len(_KNOWN_FEATURE_NAMES)
        assert c.feature_coverage == pytest.approx(expected, abs=1e-4)

    def test_unknown_feature_names_do_not_count(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr,
                                submitted_feature_names=["Unknown Feature XYZ"])
        assert c.feature_coverage == pytest.approx(0.0, abs=1e-4)

    def test_more_features_gives_higher_coverage(self):
        ir = _make_ir()
        vr = _make_vr()
        few  = ["Forwarding Rate", "DRAM"]
        many = list(_KNOWN_FEATURE_NAMES)
        c_few  = compute_confidence(ir, vr, submitted_feature_names=few)
        c_many = compute_confidence(ir, vr, submitted_feature_names=many)
        assert c_many.feature_coverage > c_few.feature_coverage

    def test_feature_coverage_in_breakdown(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr,
                                submitted_feature_names=list(_KNOWN_FEATURE_NAMES))
        assert any("feature_coverage" in line for line in c.breakdown)

    def test_coverage_score_bounded_zero_to_one(self):
        ir = _make_ir()
        vr = _make_vr()
        # Duplicate known features — must not exceed 1.0
        duplicates = list(_KNOWN_FEATURE_NAMES) * 3
        c = compute_confidence(ir, vr, submitted_feature_names=duplicates)
        assert c.feature_coverage <= 1.0


# ── Constraint cleanliness ────────────────────────────────────────────────────

class TestConstraintCleanliness:

    def test_zero_warnings_zero_violations_gives_one(self):
        ir = _make_ir()
        vr = _make_vr(warnings=0, violations=0)
        c  = compute_confidence(ir, vr)
        assert c.constraint_clean == pytest.approx(1.0, abs=1e-4)

    def test_each_warning_reduces_by_0_1(self):
        ir = _make_ir()
        for n in range(1, 6):
            vr = _make_vr(warnings=n, violations=0)
            c  = compute_confidence(ir, vr)
            expected = max(0.0, 1.0 - n * 0.1)
            assert c.constraint_clean == pytest.approx(expected, abs=1e-4)

    def test_each_violation_reduces_by_0_2(self):
        ir = _make_ir()
        for n in range(1, 4):
            vr = _make_vr(warnings=0, violations=n)
            c  = compute_confidence(ir, vr)
            expected = max(0.0, 1.0 - n * 0.2)
            assert c.constraint_clean == pytest.approx(expected, abs=1e-4)

    def test_constraint_score_floor_is_zero(self):
        ir = _make_ir()
        vr = _make_vr(warnings=20, violations=20)
        c  = compute_confidence(ir, vr)
        assert c.constraint_clean == pytest.approx(0.0, abs=1e-4)


# ── Graph match ───────────────────────────────────────────────────────────────

class TestGraphMatch:

    def test_known_router_gets_graph_match_one(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=1.0)
        assert c.graph_match == pytest.approx(1.0, abs=1e-4)

    def test_unknown_router_gets_similarity_score(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=0.72)
        assert c.graph_match == pytest.approx(0.72, abs=1e-4)

    def test_no_match_gives_zero(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=0.0)
        assert c.graph_match == pytest.approx(0.0, abs=1e-4)

    def test_similarity_above_one_is_clamped(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=1.5)
        assert c.graph_match == pytest.approx(1.0, abs=1e-4)

    def test_negative_similarity_is_clamped_to_zero(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr, similarity_score=-0.3)
        assert c.graph_match == pytest.approx(0.0, abs=1e-4)


# ── Breakdown list ────────────────────────────────────────────────────────────

class TestBreakdown:

    def test_breakdown_has_five_entries(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr,
                                submitted_feature_names=["Forwarding Rate"],
                                all_profiles=_make_profiles())
        assert len(c.breakdown) == 5

    def test_breakdown_contains_all_component_names(self):
        ir = _make_ir()
        vr = _make_vr()
        c  = compute_confidence(ir, vr,
                                submitted_feature_names=["Forwarding Rate"],
                                all_profiles=_make_profiles())
        text = " ".join(c.breakdown)
        assert "signal_strength"  in text
        assert "graph_match"      in text
        assert "constraint_clean" in text
        assert "profile_fit"      in text
        assert "feature_coverage" in text
