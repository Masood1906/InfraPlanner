# parser/input_parser.py
# Accepts raw router spec dict, validates fields, converts units.
# Returns a ParsedSpec — the canonical internal representation.

from dataclasses import dataclass, field
from parser.normalizer import convert_unit, validate_ranges


# ── Schema: what fields we accept and their expected units ────────────────────
# (field_key, display_name, expected_unit, required)
SPEC_SCHEMA: list[tuple[str, str, str, bool]] = [
    ("model",            "Router Model",       None,    True),
    ("vendor",           "Vendor",             None,    False),
    ("series",           "Series",             None,    False),
    ("stacking_bw",      "Stacking Bandwidth", "Gbps",  False),
    ("switching_cap",    "Switching Capacity", "Gbps",  True),
    ("forwarding_rate",  "Forwarding Rate",    "Mpps",  True),
    ("vlan_ids",         "VLAN IDs",           "count", False),
    ("mac_addresses",    "MAC Addresses",      "count", False),
    ("ipv4_routes",      "IPv4 Routes",        "count", True),
    ("dram_gb",          "DRAM",               "GB",    True),
]

REQUIRED_FIELDS = {s[0] for s in SPEC_SCHEMA if s[3]}

# Maps common name variants to canonical router IDs that exist in the graph.
# Prevents "Cisco Catalyst 9300X" being treated as unknown when "cisco_9300x"
# is already seeded. Add entries here whenever a new router is seeded. (FIX-07)
ROUTER_ALIASES: dict[str, str] = {
    "cisco_catalyst_9300x":  "cisco_9300x",
    "cisco_catalyst_9200":   "cisco_9200",
    "cisco_catalyst_9500":   "cisco_9500",
    "cisco_catalyst_8500":   "cisco_8500",
    "cisco_asr_1001_x":      "cisco_asr1001",
    "cisco_asr_1006_x":      "cisco_asr1006",
    "cisco_asr1001x":        "cisco_asr1001",
    "cisco_asr1006x":        "cisco_asr1006",
    "cisco_asr1001_x":       "cisco_asr1001",
    "cisco_asr1006_x":       "cisco_asr1006",
}


@dataclass
class ParsedFeature:
    name: str           # display name matching graph RouterFeature.name
    raw_value: float
    raw_unit: str
    canonical_value: float
    canonical_unit: str


@dataclass
class ParsedSpec:
    router_id: str
    model: str
    vendor: str
    series: str
    features: list[ParsedFeature] = field(default_factory=list)
    range_warnings: list = field(default_factory=list)  # RangeWarning list


def parse(raw: dict) -> ParsedSpec:
    """
    Validate and normalize a raw router spec dict.
    Raises ValueError with a descriptive message on bad input.

    Expected raw format:
    {
        "model": "Cisco 9300X",
        "vendor": "Cisco",          # optional
        "series": "9300",           # optional
        "switching_cap":  {"value": 640,  "unit": "Gbps"},
        "forwarding_rate":{"value": 2232, "unit": "Mpps"},
        "ipv4_routes":    {"value": 32000,"unit": "count"},
        "dram_gb":        {"value": 8,    "unit": "GB"},
        ...
    }
    """
    _validate(raw)

    raw_id    = _slugify(str(raw["model"]))
    router_id = ROUTER_ALIASES.get(raw_id, raw_id)   # resolve alias (FIX-07)
    spec = ParsedSpec(
        router_id=router_id,
        model=str(raw["model"]),
        vendor=str(raw.get("vendor", "Unknown")),
        series=str(raw.get("series", "")),
    )

    # Map each numeric field to a ParsedFeature
    field_to_display = {s[0]: s[1] for s in SPEC_SCHEMA}
    for key, display_name, _, _ in SPEC_SCHEMA:
        if key in ("model", "vendor", "series") or key not in raw:
            continue
        entry = raw[key]
        extracted = _extract(key, entry)
        if extracted is None:
            continue   # optional zero field — skip silently
        raw_val, raw_unit = extracted
        canon_val, canon_unit = convert_unit(raw_val, raw_unit)
        spec.features.append(ParsedFeature(
            name=display_name,
            raw_value=raw_val,
            raw_unit=raw_unit,
            canonical_value=canon_val,
            canonical_unit=canon_unit,
        ))

    spec.range_warnings = validate_ranges(spec.features)
    return spec


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate(raw: dict):
    missing = REQUIRED_FIELDS - set(raw.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")


# Optional fields that are vendor-specific or legitimately zero.
# When submitted as 0, they are treated as "not provided" and silently skipped
# rather than raising a validation error or emitting a misleading range warning.
# stacking_bw=0 is valid for non-stackable routers (e.g. Juniper MX series).
OPTIONAL_ZERO_FIELDS: frozenset[str] = frozenset({"stacking_bw"})


def _extract(key: str, entry) -> tuple[float, str] | None:
    """
    Accept either a plain number or {"value": x, "unit": y}.
    Returns None for optional fields submitted as 0 (treated as not provided).
    Raises ValueError for required fields with zero/negative values.
    Validates that the unit is recognized.
    """
    if isinstance(entry, dict):
        if "value" not in entry:
            raise ValueError(f"Field '{key}' dict must have a 'value' key")
        val = float(entry["value"])
    else:
        val = float(entry)
    if val <= 0:
        if key in OPTIONAL_ZERO_FIELDS:
            return None   # treat as not provided — skip silently
        raise ValueError(f"Field '{key}' value must be positive, got {val}")
    unit = str(entry.get("unit", "count")) if isinstance(entry, dict) else _default_unit(key)
    
    # Validate unit is recognized
    from parser.normalizer import UNIT_CONVERSIONS
    if unit.lower() not in UNIT_CONVERSIONS:
        valid_units = sorted(set(u for u, _ in UNIT_CONVERSIONS.values()))
        raise ValueError(
            f"Field '{key}' has unrecognized unit '{unit}'. "
            f"Valid units: {', '.join(valid_units)}"
        )
    
    return val, unit


def _default_unit(key: str) -> str:
    defaults = {
        "stacking_bw": "Gbps", "switching_cap": "Gbps",
        "forwarding_rate": "Mpps", "dram_gb": "GB",
        "vlan_ids": "count", "mac_addresses": "count", "ipv4_routes": "count",
    }
    return defaults.get(key, "count")


def _slugify(text: str) -> str:
    """'Cisco Catalyst 9300X' → 'cisco_catalyst_9300x'"""
    return text.lower().strip().replace(" ", "_").replace("-", "_")
