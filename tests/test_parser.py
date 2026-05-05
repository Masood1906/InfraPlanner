# tests/test_parser.py
# Unit tests for parser/input_parser.py and parser/normalizer.py.
# No graph dependency — pure Python input/output.

import pytest
from parser.input_parser import parse, _slugify, ROUTER_ALIASES
from parser.normalizer import convert_unit, normalize


# ── input_parser: happy path ──────────────────────────────────────────────────

class TestParseHappyPath:

    def test_required_fields_produce_parsed_spec(self, spec_9300x):
        spec = parse(spec_9300x)
        assert spec.model == "Cisco 9300X"
        assert spec.router_id == "cisco_9300x"
        assert spec.vendor == "Cisco"
        assert len(spec.features) > 0

    def test_all_features_present(self, spec_9300x):
        spec = parse(spec_9300x)
        names = [f.name for f in spec.features]
        assert "Switching Capacity" in names
        assert "Forwarding Rate" in names
        assert "IPv4 Routes" in names
        assert "DRAM" in names

    def test_optional_fields_included_when_provided(self, spec_9300x):
        spec = parse(spec_9300x)
        names = [f.name for f in spec.features]
        assert "Stacking Bandwidth" in names
        assert "VLAN IDs" in names
        assert "MAC Addresses" in names

    def test_optional_fields_absent_when_not_provided(self, spec_minimal):
        spec = parse(spec_minimal)
        names = [f.name for f in spec.features]
        assert "Stacking Bandwidth" not in names
        assert "VLAN IDs" not in names

    def test_minimal_spec_parses_correctly(self, spec_minimal):
        spec = parse(spec_minimal)
        assert spec.model == "Cisco 9200"
        assert spec.vendor == "Cisco"
        assert spec.series == ""          # default

    def test_plain_number_accepted_without_unit_dict(self):
        raw = {
            "model": "Test Router",
            "switching_cap":   640,
            "forwarding_rate": 2232,
            "ipv4_routes":     32000,
            "dram_gb":         8,
        }
        spec = parse(raw)
        assert len(spec.features) == 4


# ── input_parser: unit conversion applied ────────────────────────────────────

class TestParseUnitConversion:

    def test_tbps_converted_to_gbps(self, spec_9300x):
        spec = parse(spec_9300x)
        stacking = next(f for f in spec.features if f.name == "Stacking Bandwidth")
        assert stacking.raw_value == 1
        assert stacking.raw_unit == "TBps"
        assert stacking.canonical_value == 1000.0
        assert stacking.canonical_unit == "Gbps"

    def test_gbps_stays_gbps(self, spec_9300x):
        spec = parse(spec_9300x)
        switching = next(f for f in spec.features if f.name == "Switching Capacity")
        assert switching.canonical_value == 640.0
        assert switching.canonical_unit == "Gbps"

    def test_count_unit_unchanged(self, spec_9300x):
        spec = parse(spec_9300x)
        routes = next(f for f in spec.features if f.name == "IPv4 Routes")
        assert routes.canonical_value == 32000.0
        assert routes.canonical_unit == "count"


# ── input_parser: validation errors ──────────────────────────────────────────

class TestParseValidation:

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="model"):
            parse({
                "switching_cap":   {"value": 640,  "unit": "Gbps"},
                "forwarding_rate": {"value": 2232, "unit": "Mpps"},
                "ipv4_routes":     {"value": 32000,"unit": "count"},
                "dram_gb":         {"value": 8,    "unit": "GB"},
            })

    def test_missing_switching_cap_raises(self):
        with pytest.raises(ValueError):
            parse({
                "model":           "Test",
                "forwarding_rate": {"value": 2232, "unit": "Mpps"},
                "ipv4_routes":     {"value": 32000,"unit": "count"},
                "dram_gb":         {"value": 8,    "unit": "GB"},
            })

    def test_feature_dict_missing_value_key_raises(self):
        with pytest.raises(ValueError, match="value"):
            parse({
                "model":           "Test",
                "switching_cap":   {"unit": "Gbps"},   # missing "value"
                "forwarding_rate": {"value": 2232, "unit": "Mpps"},
                "ipv4_routes":     {"value": 32000,"unit": "count"},
                "dram_gb":         {"value": 8,    "unit": "GB"},
            })

    def test_empty_dict_raises(self):
        with pytest.raises(ValueError):
            parse({})


# ── input_parser: zero and negative value rejection ───────────────────────────

class TestZeroAndNegativeValues:

    def _base(self):
        return {
            "model":           "Test Router",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }

    def test_zero_switching_cap_raises(self):
        raw = self._base()
        raw["switching_cap"]["value"] = 0
        with pytest.raises((ValueError, Exception)):
            parse(raw)

    def test_negative_forwarding_rate_raises(self):
        raw = self._base()
        raw["forwarding_rate"]["value"] = -100
        with pytest.raises((ValueError, Exception)):
            parse(raw)

    def test_zero_dram_raises(self):
        raw = self._base()
        raw["dram_gb"]["value"] = 0
        with pytest.raises((ValueError, Exception)):
            parse(raw)

    def test_negative_ipv4_routes_raises(self):
        raw = self._base()
        raw["ipv4_routes"]["value"] = -1
        with pytest.raises((ValueError, Exception)):
            parse(raw)


# ── FIX-07: router alias resolution ─────────────────────────────────────────

class TestRouterAliases:

    @pytest.mark.parametrize("model_name,expected_id", [
        ("Cisco 9300X",          "cisco_9300x"),
        ("Cisco Catalyst 9300X", "cisco_9300x"),
        ("Cisco Catalyst 9200",  "cisco_9200"),
        ("Cisco Catalyst 9500",  "cisco_9500"),
        ("Cisco Catalyst 8500",  "cisco_8500"),
        ("Cisco ASR 1001-X",     "cisco_asr1001"),
        ("Cisco ASR 1006-X",     "cisco_asr1006"),
        ("Cisco ASR1001-X",      "cisco_asr1001"),
        ("Cisco ASR1006-X",      "cisco_asr1006"),
    ])
    def test_alias_resolves_to_canonical_id(self, model_name, expected_id):
        raw = {
            "model":           model_name,
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        spec = parse(raw)
        assert spec.router_id == expected_id

    def test_unknown_model_uses_slugified_id(self):
        raw = {
            "model":           "Juniper MX480",
            "switching_cap":   {"value": 480,     "unit": "Gbps"},
            "forwarding_rate": {"value": 960,     "unit": "Mpps"},
            "ipv4_routes":     {"value": 1000000, "unit": "count"},
            "dram_gb":         {"value": 64,      "unit": "GB"},
        }
        spec = parse(raw)
        assert spec.router_id == "juniper_mx480"

    def test_alias_does_not_change_model_display_name(self):
        raw = {
            "model":           "Cisco Catalyst 9300X",
            "switching_cap":   {"value": 640,   "unit": "Gbps"},
            "forwarding_rate": {"value": 2232,  "unit": "Mpps"},
            "ipv4_routes":     {"value": 32000, "unit": "count"},
            "dram_gb":         {"value": 8,     "unit": "GB"},
        }
        spec = parse(raw)
        assert spec.router_id == "cisco_9300x"
        assert spec.model     == "Cisco Catalyst 9300X"

    def test_all_alias_targets_are_valid_slugs(self):
        for alias, canonical in ROUTER_ALIASES.items():
            assert canonical == canonical.lower()
            assert " " not in canonical

    def test_alias_keys_are_valid_slugs(self):
        for alias in ROUTER_ALIASES:
            assert alias == alias.lower()
            assert " " not in alias

    def test_spaces_become_underscores(self):
        assert _slugify("Cisco 9300X") == "cisco_9300x"

    def test_hyphens_become_underscores(self):
        assert _slugify("Cisco-9300X") == "cisco_9300x"

    def test_already_lowercase_unchanged(self):
        assert _slugify("cisco_9300x") == "cisco_9300x"

    def test_mixed_case_lowercased(self):
        assert _slugify("Cisco Catalyst 9300X") == "cisco_catalyst_9300x"


# ── normalizer: unit conversion ───────────────────────────────────────────────

class TestConvertUnit:

    @pytest.mark.parametrize("value,unit,expected_val,expected_unit", [
        (1,    "TBps",  1000.0,  "Gbps"),
        (1,    "tbps",  1000.0,  "Gbps"),
        (640,  "Gbps",  640.0,   "Gbps"),
        (1000, "Mbps",  1.0,     "Gbps"),
        (2232, "Mpps",  2232.0,  "Mpps"),
        (1,    "GPps",  1000.0,  "Mpps"),
        (8,    "GB",    8.0,     "GB"),
        (1,    "TB",    1024.0,  "GB"),
        (1024, "MB",    1.0,     "GB"),
    ])
    def test_conversion(self, value, unit, expected_val, expected_unit):
        result_val, result_unit = convert_unit(value, unit)
        assert result_val == pytest.approx(expected_val, rel=1e-3)
        assert result_unit == expected_unit

    def test_unknown_unit_passes_through(self):
        val, unit = convert_unit(42.0, "widgets")
        assert val == 42.0
        assert unit == "widgets"


# ── normalizer: feature normalization ────────────────────────────────────────

class TestNormalize:

    def test_value_at_min_returns_zero(self):
        assert normalize("Forwarding Rate", 18.0) == 0.0

    def test_value_at_max_returns_one(self):
        assert normalize("Forwarding Rate", 166000.0) == 1.0

    def test_value_below_min_clamped_to_zero(self):
        assert normalize("Forwarding Rate", 0.0) == 0.0

    def test_value_above_max_clamped_to_one(self):
        assert normalize("Forwarding Rate", 999999.0) == 1.0

    def test_midpoint_value_near_half(self):
        lo, hi = 18.0, 100000.0
        mid = (lo + hi) / 2
        result = normalize("Forwarding Rate", mid)
        assert 0.49 < result < 0.51

    def test_unknown_feature_returns_neutral(self):
        assert normalize("Unknown Feature XYZ", 100.0) == 0.5

    def test_9300x_forwarding_rate_is_low_signal(self):
        result = normalize("Forwarding Rate", 2232.0)
        assert result < 0.05

    def test_high_end_forwarding_rate_is_strong_signal(self):
        result = normalize("Forwarding Rate", 166000.0)
        assert result == 1.0


# ── normalizer: range validation ──────────────────────────────────────────────

class TestValidateRanges:

    def _feat(self, name, value, unit="Mpps"):
        from parser.input_parser import ParsedFeature
        return ParsedFeature(name, value, unit, value, unit)

    def test_value_below_minimum_produces_below_warning(self):
        from parser.normalizer import validate_ranges
        warnings = validate_ranges([self._feat("Forwarding Rate", 1.0)])
        assert len(warnings) == 1
        assert warnings[0].direction == "below_minimum"

    def test_value_above_maximum_produces_above_warning(self):
        from parser.normalizer import validate_ranges
        warnings = validate_ranges([self._feat("Forwarding Rate", 999_999.0)])
        assert len(warnings) == 1
        assert warnings[0].direction == "above_maximum"

    def test_value_in_range_produces_no_warning(self):
        from parser.normalizer import validate_ranges
        warnings = validate_ranges([self._feat("Forwarding Rate", 2232.0)])
        assert warnings == []

    def test_unknown_feature_produces_no_warning(self):
        from parser.normalizer import validate_ranges
        warnings = validate_ranges([self._feat("Unknown Feature XYZ", 100.0)])
        assert warnings == []

    def test_overshoot_pct_is_positive(self):
        from parser.normalizer import validate_ranges
        warnings = validate_ranges([self._feat("Forwarding Rate", 999_999.0)])
        assert warnings[0].overshoot_pct > 0

    def test_warning_message_is_non_empty(self):
        from parser.normalizer import validate_ranges
        warnings = validate_ranges([self._feat("Forwarding Rate", 1.0)])
        assert len(warnings[0].message) > 0
