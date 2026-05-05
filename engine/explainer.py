# engine/explainer.py
# Generates natural language explanations for a DeploymentPlan.
#
# Two explanation modes:
#   simple     → plain English for any user, no technical jargon.
#                Default view in the UI.
#   technical  → full reasoning chain for network engineers.
#                Available via "Show technical reasoning" toggle.
#
# Each mode has an LLM path (gpt-4o-mini) and a template fallback.
# LLM mode is controlled by LLM_EXPLANATION_ENABLED env var.

import logging
import os
from engine.deployment_planner import DeploymentPlan

logger = logging.getLogger(__name__)
LLM_ENABLED  = os.getenv("LLM_EXPLANATION_ENABLED", "true").lower() == "true"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def explain(plan: DeploymentPlan) -> str:
    """Technical explanation for network engineers."""
    if LLM_ENABLED:
        try:
            return _llm_explain(plan)
        except Exception as e:
            logger.warning("LLM technical explain failed (%s), falling back to template.", e)
    return _template_explain(plan)


def explain_simple(plan: DeploymentPlan) -> str:
    """Plain-English explanation for any user. No technical jargon."""
    if LLM_ENABLED:
        try:
            return _llm_explain_simple(plan)
        except Exception as e:
            logger.warning("LLM simple explain failed (%s), falling back to template.", e)
    return _template_explain_simple(plan)


def explain_relationship(path_nodes: list[dict], path_edges: list[dict]) -> str:
    """
    Generate a plain-English explanation of a graph path between two nodes.
    Reuses the same OpenAI client and model as explain().
    Falls back to a template sentence if LLM is disabled or fails.
    """
    if LLM_ENABLED:
        try:
            return _llm_explain_relationship(path_nodes, path_edges)
        except Exception as e:
            logger.warning("LLM relationship explain failed (%s), falling back to template.", e)
    return _template_explain_relationship(path_nodes, path_edges)


def _llm_explain_relationship(path_nodes: list[dict], path_edges: list[dict]) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _safe(label: str) -> str:
        """Truncate and strip newlines to prevent prompt injection."""
        return str(label)[:100].replace("\n", " ").replace("\r", " ")

    source = _safe(path_nodes[0].get("label", "unknown")) if path_nodes else "unknown"
    target = _safe(path_nodes[-1].get("label", "unknown")) if path_nodes else "unknown"

    # Build a compact hop-by-hop description for the prompt
    hops = []
    for i, edge in enumerate(path_edges):
        src = next((n for n in path_nodes if n["id"] == edge["source"]), None)
        tgt = next((n for n in path_nodes if n["id"] == edge["target"]), None)
        if not src or not tgt:
            continue
        props = []
        if edge.get("base_weight") is not None:
            props.append(f"weight={edge['base_weight']:.2f}")
        if edge.get("fit_score") is not None:
            props.append(f"fit_score={edge['fit_score']:.2f}")
        if edge.get("priority") is not None:
            props.append(f"priority={edge['priority']}")
        prop_str = f" ({', '.join(props)})" if props else ""
        hops.append(
            f"  {i+1}. [{src['type']}] {src['label']} "
            f"--{edge['type']}{prop_str}--> "
            f"[{tgt['type']}] {tgt['label']}"
        )

    prompt = f"""You are an expert Kubernetes infrastructure architect specializing \
in virtualized Cisco router deployments.

A user is exploring a knowledge graph that maps router hardware specifications \
to Kubernetes deployment decisions. The graph has these node types:
- RouterModel: a physical Cisco router device
- RouterFeature: a measurable hardware capability (e.g. forwarding rate, DRAM)
- OperationalImplication: an infrastructure demand implied by the feature
- InfraRequirement: a specific resource that must be provisioned
- NodeProfile: a Kubernetes node hardware profile that satisfies a requirement
- DeploymentPattern: a recommended Kubernetes cluster topology

The user asked: "What is the relationship between {source} and {target}?"

Here is the path found in the graph:
{chr(10).join(hops)}

Explain this relationship in 2-3 plain English sentences written for a network engineer. \
Be specific about the numbers (weights, fit scores, priorities) and explain WHY each \
step follows from the previous one. Do not use bullet points."""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are an expert Kubernetes infrastructure architect. "
                "Explain graph relationships clearly and concisely to network engineers."
            )},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=250,
    )
    return response.choices[0].message.content.strip()


def _template_explain_relationship(path_nodes: list[dict], path_edges: list[dict]) -> str:
    """Fallback template when LLM is unavailable."""
    if not path_edges:
        return "These two nodes are directly connected in the knowledge graph."
    parts = []
    for edge in path_edges:
        src = next((n for n in path_nodes if n["id"] == edge["source"]), None)
        tgt = next((n for n in path_nodes if n["id"] == edge["target"]), None)
        if not src or not tgt:
            continue
        rel = edge["type"].replace("_", " ").lower()
        parts.append(f"{src['label']} {rel} {tgt['label']}")
    return ". ".join(parts) + "."


# ── Simple explanation (plain English, no jargon) ────────────────────────────

def _llm_explain_simple(plan: DeploymentPlan) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Collect role counts across all clusters
    role_counts: dict[str, int] = {}
    for c in plan.clusters:
        for n in c.nodes:
            role_counts[n.role] = role_counts.get(n.role, 0) + 1

    total_nodes = sum(c.node_count for c in plan.clusters)
    total_vcpu  = sum(c.total_vcpu  for c in plan.clusters)
    total_ram   = sum(c.total_ram_gb for c in plan.clusters)

    # Translate topology label to plain English
    topology_plain = {
        "high_performance": "high-performance",
        "memory_routing":   "memory-optimised routing",
        "compute_heavy":    "compute-heavy",
        "network_heavy":    "network-heavy",
        "balanced":         "balanced",
        "minimal":          "minimal",
        "dual_cluster":     "dual-cluster",
    }.get(plan.topology_type, plan.topology_type.replace("_", " "))

    roles_str = ", ".join(
        f"{count} {role} node{'s' if count > 1 else ''}"
        for role, count in sorted(role_counts.items())
    )

    warnings_str = (
        "\n".join(f"- {w}" for w in plan.warnings)
        if plan.warnings else "None"
    )

    prompt = f"""A Kubernetes infrastructure plan has been generated for a router called \
'{plan.router_name or plan.router_id}'.

PLAN FACTS (do not repeat these verbatim — use them to write natural sentences):
- Router name: {plan.router_name or plan.router_id}
- Plan is valid: {plan.valid}
- Deployment style: {topology_plain}
- High availability: {'yes — the system keeps running even if one node fails' if plan.ha_enabled else 'no'}
- Number of clusters: {plan.cluster_count}
- Total nodes: {total_nodes} ({roles_str})
- Total CPU capacity: {total_vcpu} virtual CPUs
- Total memory: {total_ram} GB
- Warnings: {warnings_str}

Write a plain-English explanation in exactly 3 short paragraphs for someone who does not \
know Kubernetes, graph databases, or networking jargon. Rules:
- Never use: seed_min, signal, fit_score, demand_target, oi_high_pkt, oi_high_net, \
oi_high_route, oi_high_mem, oi_port_dense, InfraRequirement, OperationalImplication, \
NodeProfile, DeploymentPattern, vCPU (say 'processing power' instead), topology_type.
- Explain what kind of router this is in one sentence.
- Explain why the system chose this deployment style.
- Explain what each node type does in plain terms \
(compute = packet processing, network = traffic handling, memory = storing route tables, \
storage = system data).
- If the plan is valid say so reassuringly. If not, say what the user should check.
- If there are warnings, explain what they mean in plain English and what the user should do.
- End with one sentence telling the user what to do next.
- Maximum 120 words total.
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": (
                "You explain complex infrastructure plans in plain English "
                "for non-technical users. Be warm, clear, and concise. "
                "Never use technical jargon."
            )},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()


def _template_explain_simple(plan: DeploymentPlan) -> str:
    """Deterministic plain-English fallback — no LLM required."""
    name = plan.router_name or plan.router_id

    # Router class sentence
    topology_desc = {
        "high_performance": "a high-capacity router that needs strong processing, networking, and memory",
        "memory_routing":   "a routing-heavy device that manages large numbers of network paths",
        "compute_heavy":    "a packet-processing-intensive router",
        "network_heavy":    "a high-throughput networking device",
        "balanced":         "a general-purpose access or campus switch",
        "minimal":          "a small or branch-office router",
        "dual_cluster":     "a very high-scale router requiring split deployment",
    }.get(plan.topology_type, "a router")

    # Node role sentences
    role_counts: dict[str, int] = {}
    for c in plan.clusters:
        for n in c.nodes:
            role_counts[n.role] = role_counts.get(n.role, 0) + 1

    role_descriptions = {
        "compute": "handle packet processing and forwarding",
        "network": "manage high-speed traffic and port capacity",
        "memory":  "store and look up routing tables",
        "storage": "hold system logs and configuration data",
        "balanced": "handle a mix of processing, networking, and memory tasks",
    }
    node_parts = [
        f"{count} node{'s' if count > 1 else ''} to {role_descriptions.get(role, role)}"
        for role, count in sorted(role_counts.items())
    ]

    total_nodes = sum(c.node_count for c in plan.clusters)
    ha_sentence = (
        "The deployment uses high availability, so it keeps running even if one node has a problem."
        if plan.ha_enabled else
        "High availability is not enabled for this deployment."
    )

    status_sentence = (
        "The plan is ready to use."
        if plan.valid else
        "The plan has issues that need to be resolved before deployment."
    )

    # Warning translations
    warning_sentences = []
    for w in plan.warnings:
        w_lower = w.lower()
        if "capped" in w_lower:
            warning_sentences.append(
                "Some node counts were reduced to fit within cluster limits — "
                "consider splitting into additional clusters if you need more capacity."
            )
        elif "unknown" in w_lower or "similar" in w_lower:
            warning_sentences.append(
                "This router model is not in the system's database, so the plan is based "
                "on the closest known router. Review the plan before deploying."
            )
        elif "stacking" in w_lower or "below" in w_lower:
            warning_sentences.append(
                "One optional feature was not provided and was skipped — this is normal "
                "if your router does not support it."
            )

    lines = [
        f"The {name} is {topology_desc}.",
        f"The system recommends a {plan.topology_type.replace('_', ' ')} deployment "
        f"across {plan.cluster_count} cluster{'s' if plan.cluster_count > 1 else ''} "
        f"with {total_nodes} nodes: " + "; ".join(node_parts) + ".",
        ha_sentence,
        status_sentence,
    ]
    if warning_sentences:
        lines.append("Note: " + " ".join(dict.fromkeys(warning_sentences)))
    lines.append("You can review the full technical details by switching to the Technical Reasoning tab.")

    return " ".join(lines)


# ── Technical LLM explanation ─────────────────────────────────────────────────

def _llm_explain(plan: DeploymentPlan) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = _build_prompt(plan)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Kubernetes infrastructure architect specializing "
                    "in virtualized router deployments across multiple vendors (Cisco, Juniper, etc.). "
                    "Explain deployment plans clearly to network engineers. "
                    "Be concise, technical, and specific. "
                    "Do not use bullet points — write in clear paragraphs. "
                    "If the reasoning chain shows node counts were capped, explicitly state "
                    "that the plan may be under-provisioned and the engineer should consider "
                    "splitting into multiple clusters. "
                    "Always trace the exact path: feature → implication → requirement → node profile. "
                    "Maximum 3 paragraphs."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=450,
    )
    return response.choices[0].message.content.strip()


def _build_prompt(plan: DeploymentPlan) -> str:
    """Build a structured prompt from the deployment plan data."""

    # Summarize clusters
    cluster_lines = []
    for c in plan.clusters:
        roles = {}
        for n in c.nodes:
            roles[n.role] = roles.get(n.role, 0) + 1
        role_summary = ", ".join(f"{count}× {role}" for role, count in roles.items())
        cluster_lines.append(
            f"  {c.cluster_id}: {c.node_count} nodes ({role_summary}) | "
            f"vCPU={c.total_vcpu} RAM={c.total_ram_gb}GB Ports={c.total_ports}"
        )

    # Full reasoning chain: Feature → Implication → Requirement → Node
    # Include ALL reasoning line types so the LLM sees the complete path.
    chain_lines = [
        r for r in plan.reasoning
        if r.startswith(("[Target]", "[Select]", "[Pattern]", "[Plan]"))
    ]

    prompt = f"""A Kubernetes deployment plan has been generated for router: {plan.router_id}

PLAN SUMMARY:
- Valid: {plan.valid}
- Topology: {plan.topology_type}
- HA Enabled: {plan.ha_enabled}
- Pattern Selected: {plan.pattern_name}
- Final Cluster Count: {plan.cluster_count}

CLUSTERS:
{chr(10).join(cluster_lines)}

FULL REASONING CHAIN (Feature → Implication → Requirement → Node → Pattern):
{chr(10).join(chain_lines)}

WARNINGS: {', '.join(plan.warnings) if plan.warnings else 'None'}

Please explain this deployment plan to a network engineer in exactly 3 paragraphs:

Paragraph 1 — Router characteristics: Which specific hardware features (forwarding rate,
IPv4 routes, DRAM, switching capacity) drove which operational implications, and what
demand targets were computed. Reference the actual numbers from the reasoning chain.

Paragraph 2 — Node selection: For each node type selected, explain which resource
requirement it satisfies and why that profile was the best fit. Show the chain:
feature → implication → requirement → node profile.

Paragraph 3 — Topology and cluster design: State the pattern that was selected and the
FINAL cluster count ({plan.cluster_count}). If the reasoning chain contains a [Pattern]
line mentioning a split (e.g. 'Planner split the deployment into N cluster(s)'), explicitly
explain that the base pattern starts with fewer clusters but the planner split due to node
count. Describe what the HA configuration means operationally and any warnings to act on.
"""
    return prompt


# ── Template explanation (fallback) ──────────────────────────────────────────

def _template_explain(plan: DeploymentPlan) -> str:
    """
    Builds a structured natural language explanation from the plan
    without any LLM call. Deterministic and always available.
    Shows the full Feature → Implication → Requirement → Node chain.
    """
    lines = []

    # Opening
    status = "valid" if plan.valid else "invalid"
    lines.append(
        f"The deployment plan for router '{plan.router_id}' is {status}. "
        f"The system determined a {plan.topology_type} topology across "
        f"{plan.cluster_count} Kubernetes cluster(s) with HA "
        f"{'enabled' if plan.ha_enabled else 'disabled'}."
    )

    # Feature → Implication → Requirement chain (demand targets)
    target_lines = [r for r in plan.reasoning if r.startswith("[Target]")]
    if target_lines:
        lines.append("\nResource demand analysis (Feature → Implication → Requirement):")
        for t in target_lines:
            body = t.replace("[Target] ", "")
            lines.append(f"  • {body}")

    # Requirement → Node profile chain
    select_lines = [r for r in plan.reasoning if r.startswith("[Select]")]
    if select_lines:
        lines.append("\nNode profile selection (Requirement → Node):")
        for s in select_lines:
            body = s.replace("[Select] ", "")
            lines.append(f"  • {body}")

    # Pattern match — show all [Pattern] lines including any split explanation
    pattern_lines = [r for r in plan.reasoning if r.startswith("[Pattern]")]
    if pattern_lines:
        lines.append("\nDeployment pattern:")
        for p in pattern_lines:
            body = p.replace("[Pattern] ", "")
            lines.append(f"  • {body}")

    # Cluster summary
    lines.append("\nCluster layout:")
    for c in plan.clusters:
        role_counts: dict[str, int] = {}
        for n in c.nodes:
            role_counts[n.role] = role_counts.get(n.role, 0) + 1
        role_str = ", ".join(f"{v}× {k}" for k, v in role_counts.items())
        lines.append(
            f"  • {c.cluster_id}: {c.node_count} nodes ({role_str}) — "
            f"total vCPU={c.total_vcpu}, RAM={c.total_ram_gb}GB, Ports={c.total_ports}"
        )

    # Warnings
    if plan.warnings:
        lines.append("\nWarnings:")
        for w in plan.warnings:
            lines.append(f"  ⚠ {w}")

    # Violations
    if plan.violations:
        lines.append("\nViolations (plan blocked):")
        for v in plan.violations:
            lines.append(f"  ✗ {v}")

    return "\n".join(lines)
