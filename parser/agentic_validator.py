# parser/agentic_validator.py
# Layer 1.5 — LLM-based router identity AND spec consistency validation.
#
# WHEN IT RUNS:
#   After the rule-based validator (Layer 1) passes AND the router is
#   unknown or poorly matched (similarity_score < 0.30).
#   Known routers with similarity >= 0.30 skip this — no LLM call.
#
# WHAT IT CHECKS (two independent questions):
#
#   Q1 — Identity: Is this a real enterprise/carrier network router?
#        Catches: consumer routers (Linksys, D-Link home), non-router devices
#        (Raspberry Pi, servers), clearly fake names.
#
#   Q2 — Spec consistency: Are the submitted specs plausible for this model?
#        Catches: real model name with impossible specs (Linksys WRT54G with
#        5760 Gbps switching), specs that contradict each other, specs that
#        are wildly out of range for the claimed device class.
#
# VERDICT LOGIC:
#   - identity=false AND confidence=high → raise ValueError (hard reject)
#   - identity=false AND confidence=medium → raise ValueError (hard reject)
#   - identity=false AND confidence=low → pass (benefit of doubt)
#   - identity=true, specs_consistent=false AND confidence=high → raise ValueError
#   - identity=true, specs_consistent=false AND confidence=medium → raise ValueError
#   - any LLM failure → pass silently (data quality gate is the safety net)
#
# COST: ~120 input tokens + ~40 output tokens per call.
#   Only fires for unknown/low-similarity routers.

import logging
import os

logger = logging.getLogger(__name__)

LLM_ENABLED  = os.getenv("LLM_EXPLANATION_ENABLED", "true").lower() == "true"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Similarity threshold below which the agentic validator fires.
# 0.30 means: if the best graph match is < 30%, we don't trust the identity.
AGENTIC_TRIGGER_SIMILARITY = 0.30


class AgenticVerdict:
    """Structured result from the agentic validator."""
    __slots__ = (
        "identity_ok", "specs_ok",
        "identity_confidence", "specs_confidence",
        "identity_reason", "specs_reason",
        "should_reject", "rejection_message",
    )

    def __init__(
        self,
        identity_ok: bool,
        specs_ok: bool,
        identity_confidence: str,   # "high" | "medium" | "low"
        specs_confidence: str,
        identity_reason: str,
        specs_reason: str,
    ):
        self.identity_ok          = identity_ok
        self.specs_ok             = specs_ok
        self.identity_confidence  = identity_confidence
        self.specs_confidence     = specs_confidence
        self.identity_reason      = identity_reason
        self.specs_reason         = specs_reason

        # Determine whether to hard-reject
        # Only reject when confidence is high or medium — low confidence means
        # the LLM is uncertain and we should give the benefit of the doubt.
        self.should_reject    = False
        self.rejection_message = ""

        if not identity_ok and identity_confidence in ("high", "medium"):
            self.should_reject     = True
            self.rejection_message = (
                f"This does not appear to be a real enterprise network router. "
                f"{identity_reason} "
                f"Please enter a real router model name (e.g. Cisco 9300X, Juniper MX480, "
                f"Arista 7050X, Nokia 7750 SR)."
            )
        elif identity_ok and not specs_ok and specs_confidence in ("high", "medium"):
            self.should_reject     = True
            self.rejection_message = (
                f"The submitted specifications are not consistent with the claimed model. "
                f"{specs_reason} "
                f"Please verify your specifications against the router's datasheet."
            )

    @classmethod
    def passthrough(cls, reason: str = "") -> "AgenticVerdict":
        """Return a verdict that always passes — used on LLM failure."""
        v = cls.__new__(cls)
        v.identity_ok          = True
        v.specs_ok             = True
        v.identity_confidence  = "low"
        v.specs_confidence     = "low"
        v.identity_reason      = reason
        v.specs_reason         = reason
        v.should_reject        = False
        v.rejection_message    = ""
        return v


def check_router(
    model_name: str,
    vendor: str,
    switching_cap_gbps: float,
    forwarding_rate_mpps: float,
    ipv4_routes: float,
    dram_gb: float,
    similarity_score: float,
) -> AgenticVerdict:
    """
    Run the agentic validation check.

    Only fires when similarity_score < AGENTIC_TRIGGER_SIMILARITY.
    Returns AgenticVerdict.passthrough() on any LLM failure.
    """
    if similarity_score >= AGENTIC_TRIGGER_SIMILARITY:
        logger.debug(
            "Agentic validator: skipped for '%s' (similarity=%.2f >= %.2f)",
            model_name, similarity_score, AGENTIC_TRIGGER_SIMILARITY,
        )
        return AgenticVerdict.passthrough("Skipped — similarity above threshold")

    if not LLM_ENABLED:
        return AgenticVerdict.passthrough("LLM disabled")

    try:
        return _llm_check(
            model_name, vendor,
            switching_cap_gbps, forwarding_rate_mpps, ipv4_routes, dram_gb,
        )
    except Exception as e:
        logger.warning("Agentic validator failed (%s) — passing through", e)
        return AgenticVerdict.passthrough(f"LLM error: {e}")


def _llm_check(
    model_name: str,
    vendor: str,
    switching_cap_gbps: float,
    forwarding_rate_mpps: float,
    ipv4_routes: float,
    dram_gb: float,
) -> AgenticVerdict:
    import json
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _safe(s: str, max_len: int = 120) -> str:
        return str(s)[:max_len].replace("\n", " ").replace("\r", " ")

    model_safe  = _safe(model_name)
    vendor_safe = _safe(vendor)

    prompt = f"""You are a senior network infrastructure engineer with deep knowledge of
enterprise and carrier-grade routing equipment.

A user submitted this router specification for Kubernetes infrastructure planning:

  Model:             {model_safe}
  Vendor:            {vendor_safe}
  Switching Capacity: {switching_cap_gbps:.1f} Gbps
  Forwarding Rate:    {forwarding_rate_mpps:.1f} Mpps
  IPv4 Routes:        {int(ipv4_routes):,}
  DRAM:               {dram_gb:.1f} GB

Answer TWO independent questions. For each, give a verdict and confidence level.

QUESTION 1 — IDENTITY:
Is this a real enterprise or carrier-grade network router (or L3 switch/firewall
that handles routing at scale)?

ACCEPT: Cisco, Juniper, Arista, Huawei, Nokia, Ericsson, Extreme, Brocade,
Alcatel-Lucent, ZTE, Ciena, Ribbon, Calix, Adtran, MikroTik EdgeRouter,
Ubiquiti EdgeRouter, Fortinet FortiGate, Palo Alto, F5, A10, and similar.
Also accept unknown model names that follow enterprise naming conventions
(alphanumeric model numbers, series names like MX/ASR/NE/7750).

REJECT: Consumer routers (Linksys, Netgear Nighthawk, D-Link home, TP-Link home,
ASUS home, Belkin, Buffalo). Non-router devices (servers, PCs, phones, IoT,
Raspberry Pi, Arduino). Clearly fake/random names with no networking context.

QUESTION 2 — SPEC CONSISTENCY:
Are the submitted specs plausible for the claimed model?
Consider: switching capacity, forwarding rate, route table size, and DRAM
should be consistent with the device class and model generation.

Examples of inconsistent specs:
- Linksys WRT54G with 5760 Gbps switching (home router, max ~1 Gbps)
- Any router with 100M IPv4 routes but only 4 GB DRAM (impossible — BGP full table
  needs ~8-16 GB minimum)
- Forwarding rate 10x higher than physically possible for the switching capacity

If you don't know the exact specs for the model, be lenient — only flag
clear impossibilities, not minor discrepancies.

Respond with ONLY valid JSON (no markdown, no extra text):
{{
  "identity": {{
    "is_router": true or false,
    "confidence": "high" or "medium" or "low",
    "reason": "one concise sentence"
  }},
  "specs": {{
    "consistent": true or false,
    "confidence": "high" or "medium" or "low",
    "reason": "one concise sentence"
  }}
}}

When uncertain about either question, set confidence="low" and give benefit of doubt."""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a senior network infrastructure engineer. "
                "Respond only with the requested JSON. "
                "No markdown fences, no explanation outside the JSON object."
            )},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=150,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model adds them despite instructions
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Agentic validator: unparseable response: %r", raw)
        return AgenticVerdict.passthrough("Unparseable LLM response")

    identity = data.get("identity", {})
    specs    = data.get("specs", {})

    identity_ok   = bool(identity.get("is_router", True))
    identity_conf = str(identity.get("confidence", "low"))
    identity_why  = str(identity.get("reason", ""))[:300]

    specs_ok   = bool(specs.get("consistent", True))
    specs_conf = str(specs.get("confidence", "low"))
    specs_why  = str(specs.get("reason", ""))[:300]

    verdict = AgenticVerdict(
        identity_ok=identity_ok,
        specs_ok=specs_ok,
        identity_confidence=identity_conf,
        specs_confidence=specs_conf,
        identity_reason=identity_why,
        specs_reason=specs_why,
    )

    logger.info(
        "Agentic validator: model='%s' identity=%s(%s) specs=%s(%s) reject=%s",
        model_name,
        identity_ok, identity_conf,
        specs_ok, specs_conf,
        verdict.should_reject,
    )
    if verdict.should_reject:
        logger.warning(
            "Agentic validator: REJECTING '%s' — %s",
            model_name, verdict.rejection_message,
        )

    return verdict
