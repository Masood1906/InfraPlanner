# graph/schema.py
# Ontology contract: node labels, relationship types, property keys.
# This is the single source of truth for the graph structure.

# ── Node Labels ──────────────────────────────────────────────────────────────
ROUTER_MODEL            = "RouterModel"
ROUTER_FEATURE          = "RouterFeature"
OPERATIONAL_IMPLICATION = "OperationalImplication"
INFRA_REQUIREMENT       = "InfraRequirement"
NODE_PROFILE            = "NodeProfile"
DEPLOYMENT_PATTERN     = "DeploymentPattern"

# ── Relationship Types ────────────────────────────────────────────────────────
HAS_FEATURE  = "HAS_FEATURE"
IMPLIES      = "IMPLIES"
REQUIRES     = "REQUIRES"
SATISFIED_BY = "SATISFIED_BY"
FITS_PATTERN = "FITS_PATTERN"   # NodeProfile → DeploymentPattern

# ── Cypher: Create Indexes ────────────────────────────────────────────────────
INDEX_STATEMENTS = [
    f"CREATE INDEX ON :{ROUTER_MODEL}(id)",
    f"CREATE INDEX ON :{ROUTER_FEATURE}(name)",
    f"CREATE INDEX ON :{OPERATIONAL_IMPLICATION}(name)",
    f"CREATE INDEX ON :{INFRA_REQUIREMENT}(resource_type)",
    f"CREATE INDEX ON :{NODE_PROFILE}(id)",
    f"CREATE INDEX ON :{DEPLOYMENT_PATTERN}(id)",
]
