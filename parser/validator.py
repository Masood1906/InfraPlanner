# parser/validator.py
# Layer 1 defence against junk and physically impossible router specs.
#
# Runs immediately after parse() and before any graph traversal or inference.
# Raises ValueError with a specific, human-readable message so the API returns
# HTTP 422 and the frontend shows a clear rejection — not a misleading plan.
#
# Design principles:
#   - Only reject what is CLEARLY wrong. Do not over-filter.
#   - Every rejection message tells the user exactly what is wrong and what
#     realistic values look like.
#   - Legitimate edge cases (very small branch routers, future hardware) must
#     not be rejected. Thresholds are set well below any real-world minimum.
#   - This is not a business rules engine. It is a sanity filter.

from parser.input_parser import ParsedSpec
from parser.normalizer import FEATURE_RANGES

# ── Rejection thresholds ──────────────────────────────────────────────────────
_HARD_FLOOR: dict[str, tuple[float, str]] = {
    "Switching Capacity": (0.1,  "Gbps  — smallest real switches start at ~24 Gbps"),
    "Forwarding Rate":    (0.1,  "Mpps  — smallest real routers start at ~15 Mpps"),
    "IPv4 Routes":        (10,   "routes — smallest real routers support at least 8,000"),
    "DRAM":               (0.5,  "GB    — smallest real routers have at least 4 GB"),
}

# Hard ceiling — values above this are physically impossible today
_HARD_CEILING: dict[str, tuple[float, str]] = {
    "IPv4 Routes":        (100_000_000, "routes — maximum known routing table size is ~100M"),
    "Switching Capacity": (800_000,     "Gbps   — largest known fabric is ~800 Tbps"),
    "Forwarding Rate":    (200_000,     "Mpps   — largest known forwarding rate is ~200 Tbps"),
    "DRAM":               (65_536,      "GB     — maximum known router DRAM is ~64 TB"),
}

_RATIO_MAX = 500.0   # Mpps per Gbps — above this is physically impossible
_RATIO_MIN = 0.001   # Mpps per Gbps — below this is physically impossible

_MODEL_MIN_LENGTH = 2
_MODEL_MAX_DIGITS_RATIO = 0.8

# Characters that have no place in a router model name and indicate injection attempts
_INVALID_MODEL_CHARS: frozenset[str] = frozenset("'\"`;{}()[]\\<>")

_NON_ROUTER_BRANDS: frozenset[str] = frozenset({
    # Consumer electronics & phones
    "samsung", "apple", "sony", "lg", "xiaomi", "oppo", "vivo",
    "motorola", "oneplus", "realme", "honor", "blackberry",
    # PC / laptop brands
    "lenovo", "dell", "asus", "acer", "toshiba", "razer", "msi",
    # Consumer appliances
    "panasonic", "philips", "bosch", "siemens", "whirlpool", "dyson",
    # Internet / social media
    "amazon", "facebook", "meta", "twitter", "netflix", "spotify",
    "google", "microsoft",
    # Automotive
    "toyota", "honda", "bmw", "ford", "tesla", "volkswagen", "mercedes",
    # Apparel
    "nike", "adidas", "puma", "gucci",
    # Junk / test strings
    "test", "testing", "asdf", "qwerty", "hello", "world", "foo", "bar",
    "baz", "lorem", "ipsum", "random", "unknown", "example", "sample",
    "dummy", "fake", "junk", "garbage", "invalid", "none", "null",
    "xyz", "abc", "aaa", "bbb",})

# Networking vendor names — a model name that is ONLY a vendor name (no model
# number) is not a valid model identifier. "cisco" alone is a vendor, not a
# router model. "Cisco 9300X" is valid. "cisco" is not.
_NETWORKING_VENDORS: frozenset[str] = frozenset({
    "cisco", "juniper", "arista", "huawei", "nokia", "ericsson",
    "alcatel", "lucent", "alcatel-lucent", "palo alto", "fortinet",
    "checkpoint", "f5", "a10", "radware", "barracuda", "sonicwall",
    "watchguard", "extreme", "brocade", "foundry", "netgear", "ubiquiti",
    "mikrotik", "ruckus", "aerohive", "meraki", "cambium", "vyos",
    "cumulus", "sonic", "openwrt", "pfsense", "mellanox", "broadcom",
    "intel", "marvell", "cavium", "tilera", "ciena", "infinera",
    "adtran", "calix", "ribbon", "sycamore", "zhone", "dasan", "bdcom",
    "zte", "h3c", "ruijie", "maipu", "fiberhome",
})


def validate_spec(spec: ParsedSpec) -> None:
    """
    Validate a ParsedSpec for physical plausibility.
    Raises ValueError with a specific message if the spec is junk.
    Returns None if the spec is acceptable.

    Call this immediately after parse() and before map_to_graph().
    """
    _check_model_name(spec)
    _check_hard_floors(spec)
    _check_hard_ceilings(spec)
    _check_all_required_below_minimum(spec)
    _check_dram_vs_routes(spec)
    _check_forwarding_switching_ratio(spec)


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_model_name(spec: ParsedSpec) -> None:
    """Reject model names that are clearly not router identifiers."""
    name = spec.model.strip()

    if len(name) < _MODEL_MIN_LENGTH:
        raise ValueError(
            f"Model name '{name}' is too short to be a valid router model. "
            f"Please enter the full router model name (e.g. 'Cisco 9300X', 'Juniper MX480')."
        )

    # Reject names containing special characters used in injection attacks
    bad_chars = [c for c in name if c in _INVALID_MODEL_CHARS]
    if bad_chars:
        raise ValueError(
            f"Model name contains invalid characters: {bad_chars}. "
            f"Please enter a real router model name (e.g. 'Cisco 9300X', 'Juniper MX480')."
        )

    # Reject if purely numeric
    digits    = sum(1 for c in name if c.isdigit())
    non_space = sum(1 for c in name if not c.isspace())
    if non_space > 0 and digits / non_space >= _MODEL_MAX_DIGITS_RATIO:
        raise ValueError(
            f"Model name '{name}' appears to be a number, not a router model. "
            f"Please enter a real router model name (e.g. 'Cisco 9300X', 'Juniper MX480')."
        )

    # Reject if the model name is ONLY a vendor name with no model number.
    # "cisco" alone is a vendor, not a model. "Cisco 9300X" is valid.
    name_lower = name.lower().strip()
    if name_lower in _NETWORKING_VENDORS:
        raise ValueError(
            f"'{name}' is a vendor name, not a router model. "
            f"Please include the model number (e.g. 'Cisco 9300X', 'Cisco ASR 1006-X', "
            f"'Juniper MX480')."
        )

    # Reject known non-networking brands
    brand_token = name.lower().split()[0] if name.split() else ""
    if brand_token in _NON_ROUTER_BRANDS:
        raise ValueError(
            f"'{name}' does not appear to be a network router model. "
            f"'{brand_token.title()}' is not a networking vendor. "
            f"Please enter a real router model name from a networking vendor "
            f"(e.g. Cisco, Juniper, Arista, Nokia)."
        )

    # Reject if vendor field is a known non-networking brand.
    # Skip generic placeholders ("unknown", "none", "null") — these are the
    # schema default when the user omits the optional vendor field.
    _VENDOR_PLACEHOLDERS = frozenset({"unknown", "none", "null", ""})
    vendor_lower = (spec.vendor or "").lower().strip()
    if vendor_lower and vendor_lower not in _VENDOR_PLACEHOLDERS and vendor_lower in _NON_ROUTER_BRANDS:
        raise ValueError(
            f"Vendor '{spec.vendor}' is not a networking vendor. "
            f"Please enter a real networking vendor (e.g. Cisco, Juniper, Arista)."
        )


def _check_hard_floors(spec: ParsedSpec) -> None:
    """Reject any required feature below the hard floor (physically impossible)."""
    feat_map = {f.name: f for f in spec.features}
    for feat_name, (floor, hint) in _HARD_FLOOR.items():
        feat = feat_map.get(feat_name)
        if feat is None:
            continue
        if feat.canonical_value < floor:
            raise ValueError(
                f"{feat_name} = {feat.canonical_value} {feat.canonical_unit} is too low "
                f"to be a real network device. Minimum accepted: {floor} {hint}. "
                f"Please check your input values."
            )


def _check_hard_ceilings(spec: ParsedSpec) -> None:
    """Reject any feature above the hard ceiling (physically impossible today)."""
    feat_map = {f.name: f for f in spec.features}
    for feat_name, (ceiling, hint) in _HARD_CEILING.items():
        feat = feat_map.get(feat_name)
        if feat is None:
            continue
        if feat.canonical_value > ceiling:
            raise ValueError(
                f"{feat_name} = {feat.canonical_value:,.0f} {feat.canonical_unit} "
                f"exceeds the maximum physically possible value ({ceiling:,.0f} {hint}). "
                f"Please check your input — this value is not realistic for any network device."
            )


def _check_all_required_below_minimum(spec: ParsedSpec) -> None:
    """Reject if ALL required features are below their reference minimum."""
    required_ranged = {"Switching Capacity", "Forwarding Rate", "IPv4 Routes", "DRAM"}
    feat_map = {f.name: f for f in spec.features}

    below   = []
    checked = []
    for name in required_ranged:
        feat = feat_map.get(name)
        if feat is None or name not in FEATURE_RANGES:
            continue
        lo, _ = FEATURE_RANGES[name]
        checked.append(name)
        if feat.canonical_value < lo:
            below.append(name)

    if checked and len(below) == len(checked):
        raise ValueError(
            f"All required features ({', '.join(below)}) are below the known minimum "
            f"for real network devices. The submitted values do not represent a valid router. "
            f"Please enter realistic specifications. "
            f"Example: Switching Capacity ≥ 24 Gbps, Forwarding Rate ≥ 18 Mpps, "
            f"IPv4 Routes ≥ 8,000, DRAM ≥ 4 GB."
        )


def _check_dram_vs_routes(spec: ParsedSpec) -> None:
    """
    Reject physically impossible DRAM vs IPv4 route table combinations.
    A full BGP internet table (~900K routes) needs 8-16 GB RAM minimum.
    """
    feat_map    = {f.name: f for f in spec.features}
    routes_feat = feat_map.get("IPv4 Routes")
    dram_feat   = feat_map.get("DRAM")

    if routes_feat is None or dram_feat is None:
        return

    routes = routes_feat.canonical_value
    dram   = dram_feat.canonical_value

    if routes > 4_000_000 and dram < 32:
        raise ValueError(
            f"IPv4 Routes = {int(routes):,} requires at least 32 GB DRAM to hold the "
            f"routing table in memory, but DRAM = {dram} GB was submitted. "
            f"A router with {int(routes):,} routes needs substantial memory for RIB/FIB. "
            f"Please verify both values."
        )
    if routes > 500_000 and dram < 8:
        raise ValueError(
            f"IPv4 Routes = {int(routes):,} requires at least 8 GB DRAM to hold the "
            f"routing table in memory, but DRAM = {dram} GB was submitted. "
            f"A full BGP internet table (~900K routes) needs 8-16 GB minimum. "
            f"Please verify both values."
        )


def _check_forwarding_switching_ratio(spec: ParsedSpec) -> None:
    """
    Reject physically impossible forwarding-rate / switching-capacity ratios.
    Real routers: ~0.3–2.0 Mpps per Gbps.
    """
    feat_map = {f.name: f for f in spec.features}
    fwd  = feat_map.get("Forwarding Rate")
    swit = feat_map.get("Switching Capacity")

    if fwd is None or swit is None:
        return
    if swit.canonical_value <= 0:
        return

    ratio = fwd.canonical_value / swit.canonical_value

    if ratio > _RATIO_MAX:
        raise ValueError(
            f"Forwarding Rate ({fwd.canonical_value} Mpps) is {ratio:.0f}× the Switching "
            f"Capacity ({swit.canonical_value} Gbps). This ratio is physically impossible — "
            f"a router cannot forward more packets than its switching fabric can carry. "
            f"Real routers have ~0.3–2.0 Mpps per Gbps. Please check your values."
        )

    if ratio < _RATIO_MIN:
        raise ValueError(
            f"Forwarding Rate ({fwd.canonical_value} Mpps) is extremely low relative to "
            f"Switching Capacity ({swit.canonical_value} Gbps). "
            f"Real routers have ~0.3–2.0 Mpps per Gbps. Please check your values."
        )
