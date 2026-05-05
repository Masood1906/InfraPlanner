# graph/router_registry.py
# Thread-safe JSON registry for user-submitted routers.
#
# Replaces the _persist_to_seed() approach that mutated seed.py at runtime.
# Routers saved here are loaded by seed.py on every startup via load().
#
# Design:
#   - Single JSON file: graph/router_registry.json
#   - Thread-safe writes via a module-level lock
#   - Idempotent: saving the same router_id twice is a no-op
#   - No dependency on the graph connection — pure filesystem

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Registry file location.
# In Docker: /app/registry/router_registry.json (bind-mounted from ./graph/).
# Locally: graph/router_registry.json (same directory as this file).
# The REGISTRY_DIR env var lets docker-compose point to the mounted path.
_REGISTRY_DIR  = os.getenv("REGISTRY_DIR", os.path.dirname(__file__))
_REGISTRY_PATH = os.path.join(_REGISTRY_DIR, "router_registry.json")
_lock = threading.Lock()

logger.debug("router_registry path resolved to: %s", _REGISTRY_PATH)


def load() -> list[dict]:
    """Return all registered routers. Returns [] if registry does not exist."""
    if not os.path.exists(_REGISTRY_PATH):
        logger.info("Registry file not found at %s — returning empty list", _REGISTRY_PATH)
        return []
    with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
        try:
            entries = json.load(f)
            logger.debug("Registry loaded %d router(s) from %s", len(entries), _REGISTRY_PATH)
            return entries
        except json.JSONDecodeError as e:
            logger.error("Registry file is corrupt (%s): %s", _REGISTRY_PATH, e)
            return []


def save(entry: dict) -> bool:
    """
    Persist a router entry to the registry.
    entry must contain at minimum: router_id, model, vendor, series, features.
    Returns True if saved, False if already present (idempotent).
    """
    with _lock:
        entries = load()
        if any(e["router_id"] == entry["router_id"] for e in entries):
            logger.info("Registry: router '%s' already present — skipping write", entry["router_id"])
            return False
        entries.append(entry)
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        logger.info("Registry: wrote router '%s' to %s (%d total)",
                    entry["router_id"], _REGISTRY_PATH, len(entries))
        return True


def exists(router_id: str) -> bool:
    """Return True if router_id is already in the registry."""
    return any(e["router_id"] == router_id for e in load())


def spec_to_entry(spec) -> dict:
    """
    Convert a ParsedSpec into a registry entry dict.
    Stores only the data needed to re-seed the router on startup.
    """
    return {
        "router_id": spec.router_id,
        "model":     spec.model,
        "vendor":    spec.vendor,
        "series":    spec.series,
        "features": [
            {
                "name":            f.name,
                "canonical_value": f.canonical_value,
                "canonical_unit":  f.canonical_unit,
            }
            for f in spec.features
        ],
    }
