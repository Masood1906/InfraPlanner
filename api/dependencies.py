# api/dependencies.py
# Manages the FalkorDB connection lifecycle.
# Graph is connected + seeded once at startup via FastAPI lifespan,
# then injected into route handlers via app.state.

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from falkordb import FalkorDB
from graph.schema import INDEX_STATEMENTS
from graph.seed import seed, GRAPH_SCHEMA_VERSION

load_dotenv()

logger = logging.getLogger(__name__)

FALKOR_HOST = os.getenv("FALKOR_HOST", "localhost")
FALKOR_PORT = int(os.getenv("FALKOR_PORT", 6379))
GRAPH_NAME  = os.getenv("GRAPH_NAME", "infra_planner")

# Meta-graph name: stores schema version so we can detect stale graphs.
_META_GRAPH = f"{GRAPH_NAME}_meta"


def _get_stored_version(db) -> str:
    """Return the schema version stored in the meta-graph, or '' if absent."""
    try:
        meta = db.select_graph(_META_GRAPH)
        result = meta.query("MATCH (v:SchemaVersion) RETURN v.version LIMIT 1")
        if result.result_set:
            return str(result.result_set[0][0])
    except Exception:
        pass
    return ""


def _store_version(db, version: str):
    """Persist the current schema version in the meta-graph."""
    try:
        meta = db.select_graph(_META_GRAPH)
        meta.query("MERGE (v:SchemaVersion) SET v.version = $v", {"v": version})
    except Exception as e:
        logger.warning("Could not store schema version: %s", e)


def _reset_graph(db, graph_name: str):
    """
    Delete all nodes and relationships in the graph so seed() starts fresh.
    Uses MATCH (n) DETACH DELETE n in batches to avoid memory spikes on
    large graphs. Falls back to graph.delete() if available.
    """
    graph = db.select_graph(graph_name)
    try:
        # FalkorDB >= 4.x exposes graph.delete()
        graph.delete()
        logger.info("Graph '%s' deleted via graph.delete()", graph_name)
    except Exception:
        # Fallback: delete all nodes in batches
        logger.info("Deleting graph '%s' via DETACH DELETE batches", graph_name)
        while True:
            result = graph.query(
                "MATCH (n) WITH n LIMIT 1000 DETACH DELETE n RETURN count(n)"
            )
            deleted = result.result_set[0][0] if result.result_set else 0
            if deleted == 0:
                break
        logger.info("Graph '%s' cleared.", graph_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Connect, check schema version, re-seed if stale, index on startup.
    """
    if not os.getenv("API_SECRET_KEY", "").strip():
        logger.warning(
            "API_SECRET_KEY is not set. "
            "Admin endpoint is open to all callers. "
            "Set API_SECRET_KEY in .env before deploying to production."
        )

    db    = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
    graph = db.select_graph(GRAPH_NAME)

    stored_version = _get_stored_version(db)
    if stored_version != GRAPH_SCHEMA_VERSION:
        logger.warning(
            "Graph schema version mismatch: stored='%s' code='%s'. "
            "Resetting graph and re-seeding.",
            stored_version, GRAPH_SCHEMA_VERSION,
        )
        _reset_graph(db, GRAPH_NAME)
        graph = db.select_graph(GRAPH_NAME)
    else:
        logger.info(
            "Graph schema version '%s' matches. Skipping reset.",
            GRAPH_SCHEMA_VERSION,
        )

    for stmt in INDEX_STATEMENTS:
        try:
            graph.query(stmt)
        except Exception:
            pass  # index already exists

    seed(graph)
    _store_version(db, GRAPH_SCHEMA_VERSION)

    app.state.graph = graph
    logger.info(
        "FalkorDB connected → graph='%s' schema_version='%s'",
        GRAPH_NAME, GRAPH_SCHEMA_VERSION,
    )
    yield
    logger.info("FalkorDB connection released.")


def get_graph(request: Request):
    """FastAPI dependency — injects the shared graph from app.state."""
    return request.app.state.graph
