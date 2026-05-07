# parser/normalizer.py
# Three responsibilities:
#   1. Unit conversion
#   2. Feature normalization to [0.0, 1.0]
#   3. Range validation — warns when values fall outside known reference ranges

from dataclasses import dataclass

# ── Unit Conversion ────────────────────────────────────────────────────────────

UNIT_CONVERSIONS: dict[str, tuple[str, float]] = {
    "tbps":  ("Gbps", 1000.0),
    "gbps":  ("Gbps", 1.0),
    "mbps":  ("Gbps", 0.001),
    "mpps":  ("Mpps", 1.0),
    "kpps":  ("Mpps", 0.001),
    "gpps":  ("Mpps", 1000.0),
    "gb":    ("GB",   1.0),
    "tb":    ("GB",   1024.0),
    "mb":    ("GB",   1 / 1024),
    "count": ("count", 1.0),
}


def convert_unit(value: float, unit: str) -> tuple[float, str]:
    """Return (converted_value, canonical_unit). Unknown units pass through."""
    key = unit.lower().strip()
    if key in UNIT_CONVERSIONS:
        canonical_unit, multiplier = UNIT_CONVERSIONS[key]
        return round(value * multiplier, 4), canonical_unit
    return value, unit


# ── Feature Reference Ranges ───────────────────────────────────────────────────
# (min_ref, max_ref) in canonical units.
# Values outside this range are clamped during normalization AND flagged.

# ── Feature Reference Ranges ───────────────────────────────────────────────────
# Max values are aligned with PHYSICAL_CEILINGS in graph/weight_engine.py.
# If you update a ceiling there, update the max here too.
# Min values are the lowest known real-world values for range warning purposes.

FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "Stacking Bandwidth":  (40.0,       10_000.0),    # Gbps  — matches PHYSICAL_CEILINGS
    "Switching Capacity":  (24.0,      100_000.0),    # Gbps  — matches PHYSICAL_CEILINGS
    "Forwarding Rate":     (18.0,      100_000.0),    # Mpps  — matches PHYSICAL_CEILINGS
    "VLAN IDs":            (256.0,       4_096.0),    # count — hard 802.1Q protocol limit
    "MAC Addresses":       (8000.0,  10_000_000.0),   # count — matches PHYSICAL_CEILINGS
    "IPv4 Routes":         (8000.0, 100_000_000.0),   # count — matches PHYSICAL_CEILINGS
    "DRAM":                (4.0,        4_096.0),     # GB    — matches PHYSICAL_CEILINGS
}


def normalize(feature_name: str, canonical_value: float) -> float:
    """
    Min-max normalize to [0.0, 1.0]. Clamps silently.
    Returns 0.5 for unknown features (neutral signal).
    """
    if feature_name not in FEATURE_RANGES:
        return 0.5
    lo, hi = FEATURE_RANGES[feature_name]
    return round(max(0.0, min(1.0, (canonical_value - lo) / (hi - lo))), 4)


# ── Range Validation ───────────────────────────────────────────────────────────

@dataclass
class RangeWarning:
    feature_name:    str
    canonical_value: float
    canonical_unit:  str
    range_min:       float
    range_max:       float
    direction:       str    # "below_minimum" | "above_maximum"
    overshoot_pct:   float  # how far outside range as % of range width
    message:         str


def validate_ranges(features: list) -> list[RangeWarning]:
    """
    Check each ParsedFeature against FEATURE_RANGES.
    Returns RangeWarning for any value outside the known range.
    Values are still processed (clamped) but the warning tells the engineer
    the system is extrapolating beyond its calibrated range.
    """
    warnings = []
    for feat in features:
        name = feat.name
        val  = feat.canonical_value
        unit = feat.canonical_unit

        if name not in FEATURE_RANGES:
            continue

        lo, hi = FEATURE_RANGES[name]
        width  = hi - lo

        if val < lo:
            overshoot = round((lo - val) / width * 100, 1)
            warnings.append(RangeWarning(
                feature_name=name,
                canonical_value=val,
                canonical_unit=unit,
                range_min=lo,
                range_max=hi,
                direction="below_minimum",
                overshoot_pct=overshoot,
                message=(
                    f"{name}={val} {unit} is below the known minimum "
                    f"({lo} {unit}). Normalised to 0.0. "
                    f"Signal will be absent — demand targets stay at seed floor."
                ),
            ))
        elif val > hi:
            overshoot = round((val - hi) / width * 100, 1)
            warnings.append(RangeWarning(
                feature_name=name,
                canonical_value=val,
                canonical_unit=unit,
                range_min=lo,
                range_max=hi,
                direction="above_maximum",
                overshoot_pct=overshoot,
                message=(
                    f"{name}={val} {unit} exceeds the known maximum "
                    f"({hi} {unit}) by {overshoot}% of range width. "
                    f"Normalised to 1.0. Demand targets may be underestimated "
                    f"— consider updating FEATURE_RANGES."
                ),
            ))
    return warnings
