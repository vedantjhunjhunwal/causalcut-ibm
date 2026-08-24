"""Async scenario pipeline — the production execution order.

Analysis runs strictly AFTER durable persistence and queue processing:

    validating -> model_inference -> persisting_events -> queue_processing
    -> state_projection -> hypergraph_update -> rule_evaluation
    -> path_extraction -> risk_propagation -> simulation -> optimization
    -> regulatory_verification -> completed | failed

Every collaborator is the existing one (EventRepository, shared ingestion
service, EventQueue, ConsumerPool, StateProjector, SafetyHypergraph). This
module orchestrates and awaits them; it never reimplements them and never
calls ``queue.put()`` directly — the ingestion service persists first.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from app.core.logging import get_logger
from app.engine.model_events import generate_model_events
from app.engine.scenario_runner import analyse_graph, register_scenario_entities
from app.engine.scenario_session import ScenarioSession, get_session_registry
from app.schemas.enums import ProcessingStatus
from app.schemas.scenario import Scenario
from app.services.ingestion import ingest_canonical_event

log = get_logger(__name__)

# Canonical stage vocabulary shared by backend and frontend.
STAGES: list[tuple[str, str]] = [
    ("validating", "Scenario validation"),
    ("model_inference", "Model inference"),
    ("persisting_events", "Event persistence"),
    ("queue_processing", "Queue processing"),
    ("state_projection", "SQLite state projection"),
    ("hypergraph_update", "Hypergraph update"),
    ("rule_evaluation", "Compound-rule activation"),
    ("path_extraction", "Causal-path extraction"),
    ("risk_propagation", "Risk propagation"),
    ("simulation", "Counterfactual simulation"),
    ("optimization", "Minimum-causal-cut optimisation"),
    ("regulatory_verification", "Regulatory verification"),
    ("completed", "Completed"),
]
STAGE_INDEX = {name: i for i, (name, _) in enumerate(STAGES)}
STAGE_LABEL = dict(STAGES)


async def run_scenario_pipeline(
    scenario: Scenario,
    *,
    events_repo,
    queue,
    settings,
    correlation_id: str | None = None,
    wait_timeout: float = 30.0,
    progress: Callable[[dict], Any] | None = None,
) -> dict[str, Any]:
    """Run a user scenario through the real backend pipeline."""
    cid = correlation_id or str(uuid.uuid4())
    t0 = time.perf_counter()

    async def emit(stage: str, **extra: Any) -> None:
        if progress is None:
            return
        msg = {
            "stage": stage,
            "label": STAGE_LABEL.get(stage, stage),
            "index": STAGE_INDEX.get(stage, -1),
            "total": len(STAGES),
            "scenario_id": scenario.scenario_id,
            "correlation_id": cid,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            **extra,
        }
        try:
            res = progress(msg)
            if hasattr(res, "__await__"):
                await res
        except Exception:
            pass  # progress must never break the pipeline

    await emit("validating", status="ok")

    # --- 1. Real model inference -> canonical PREDICTED events -------------
    await emit("model_inference", status="running")
    model_events, model_provenance = generate_model_events(scenario, cid)
    ran = [r for r in model_provenance if r.get("ran")]
    await emit("model_inference", status="ok",
               models_ran=[r.get("called") for r in ran],
               models_failed=[r.get("called") for r in model_provenance
                              if not r.get("ran")],
               events=len(model_events))

    # --- 2. User facts -> OBSERVED / SYNTHETIC events ----------------------
    scenario_events = scenario.to_events()

    # SafetyEvent is frozen by design; stamp the correlation id via model_copy
    # so the consumer can route each event to this scenario's session.
    all_events = [
        ev.model_copy(update={"correlation_id": cid})
        for ev in sorted(list(scenario_events) + list(model_events),
                         key=lambda e: e.event_time)
    ]

    # --- 3. Session registered BEFORE ingestion ----------------------------
    graph = register_scenario_entities(scenario)
    session = ScenarioSession(correlation_id=cid, scenario_id=scenario.scenario_id,
                              graph=graph)
    registry = get_session_registry()
    registry.register(session)

    ingestion = {"total": len(all_events), "accepted": 0, "duplicates": 0,
                 "rejected": 0, "queue_full": 0, "failed": 0, "details": []}
    completed = False
    stats: dict[str, Any] = {}

    try:
        # --- 4. Persist (append-only store) then enqueue -------------------
        await emit("persisting_events", status="running", total=len(all_events))
        expected = 0
        results = await asyncio.gather(
            *(ingest_canonical_event(ev, events_repo, queue, settings) for ev in all_events),
            return_exceptions=True,
        )
        for ev, res in zip(all_events, results):
            if isinstance(res, Exception):
                ingestion["rejected"] += 1
                ingestion["failed"] += 1
                ingestion["details"].append(f"{ev.event_id}: {res}")
            elif res.status is ProcessingStatus.ACCEPTED:
                ingestion["accepted"] += 1
                expected += 1
            elif res.status is ProcessingStatus.DUPLICATE:
                ingestion["duplicates"] += 1
            elif res.status is ProcessingStatus.QUEUE_FULL:
                ingestion["queue_full"] += 1
                ingestion["failed"] += 1
                ingestion["details"].append(
                    f"{ev.event_id}: queue saturated — persisted, awaiting replay")
            else:
                ingestion["rejected"] += 1
                ingestion["failed"] += 1
                ingestion["details"].append(f"{ev.event_id}: {res.detail}")
        await emit("persisting_events", status="ok", persisted=ingestion["accepted"],
                   rejected=ingestion["rejected"])

        session.set_expected(expected)

        # --- 5. Wait for queue + SQLite projection to finish ---------------
        await emit("queue_processing", status="running", expected=expected,
                   queue_depth=getattr(queue, "depth", None))
        completed = await session.wait(timeout=wait_timeout)
        stats = session.stats()
        await emit("queue_processing", status="ok" if completed else "timeout",
                   processed=stats["seen"], expected=stats["expected"],
                   failed=len(stats["errors"]))
        await emit("state_projection", status="ok" if completed else "partial",
                   projected=stats["seen"])
        await emit("hypergraph_update", status="ok" if completed else "partial",
                   applied=stats["applied"], skipped=stats["skipped"])

        log.info("scenario pipeline processed",
                 extra={"correlation_id": cid, "scenario_id": scenario.scenario_id,
                        "completed": completed, **stats})
    finally:
        registry.release(cid)

    # --- 5b. FAIL CLOSED --------------------------------------------------
    # A Minimum Causal Cut computed from partial plant state could tell an
    # operator to cut the wrong thing, or omit a hazard whose event never
    # landed. If ingestion rejected an event, the queue timed out, or an event
    # failed to project, we STOP: no hypergraph analysis, no simulation, no
    # optimisation, no recommendation.
    hard_failures: list[str] = []
    if not completed:
        hard_failures.append(
            f"queue processing timed out after {wait_timeout}s "
            f"({stats.get('seen', 0)}/{stats.get('expected', 0)} events projected)")
    if ingestion["rejected"]:
        hard_failures.append(
            f"{ingestion['rejected']} event(s) rejected at the ingestion boundary: "
            + "; ".join(ingestion["details"][:3]))
    if ingestion["queue_full"]:
        hard_failures.append(
            f"{ingestion['queue_full']} event(s) could not be queued (saturated)")
    if stats.get("errors"):
        hard_failures.append(
            f"{len(stats['errors'])} event(s) failed to project: "
            + "; ".join(stats["errors"][:3]))

    if hard_failures:
        reason = "; ".join(hard_failures)
        log.error("scenario pipeline failed — analysis suppressed",
                  extra={"correlation_id": cid, "scenario_id": scenario.scenario_id,
                         "failures": hard_failures,
                         "expected": stats.get("expected", 0),
                         "processed": stats.get("seen", 0)})
        await emit("failed", status="error", error=reason,
                   processed=stats.get("seen", 0), expected=stats.get("expected", 0))
        return {
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "correlation_id": cid,
            "status": "failed",
            "failure_stage": "queue_processing" if not completed else "persisting_events",
            "failure_reason": reason,
            "failures": hard_failures,
            # Explicitly absent: no analysis was performed on partial state.
            "recommendation": None,
            "activated_rules": [],
            "causal_paths": [],
            "graph": None,
            "regulatory_citations": [],
            "explanation": ("Pipeline did not complete: " + reason +
                            ". No causal analysis or intervention recommendation "
                            "was produced, because acting on partially projected "
                            "plant state is unsafe."),
            "warnings": hard_failures,
            "models": {"invocations": model_provenance, "mocks_used": False},
            "model_events_generated": len(model_events),
            "pipeline": {
                "order": [st for st, _ in STAGES],
                "correlation_id": cid,
                "scenario_id": scenario.scenario_id,
                "ingestion": ingestion,
                "expected_events": stats.get("expected", 0),
                "processed_events": stats.get("seen", 0),
                "failed_events": len(stats.get("errors", [])) + ingestion["failed"],
                "applied_to_graph": stats.get("applied", 0),
                "not_graph_relevant": stats.get("skipped", 0),
                "completed": False,
                "timed_out": not completed,
                "queue_depth_after": getattr(queue, "depth", None),
                "analysis_after_persistence": True,
                "analysis_performed": False,
            },
        }

    # --- 6. Analysis on the graph the consumer populated -------------------
    loop = asyncio.get_running_loop()
    pending: list[asyncio.Task] = []

    def _analysis_progress(msg: dict) -> None:
        stage = msg.get("stage", "")
        if stage in STAGE_INDEX:
            try:
                pending.append(loop.create_task(emit(stage, status="ok")))
            except RuntimeError:
                pass

    result = analyse_graph(scenario, session.graph, model_provenance, cid,
                           model_event_count=len(model_events),
                           progress_callback=_analysis_progress)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    result["pipeline"] = {
        "order": [s for s, _ in STAGES],
        "correlation_id": cid,
        "scenario_id": scenario.scenario_id,
        "ingestion": ingestion,
        "expected_events": stats.get("expected", 0),
        "processed_events": stats.get("seen", 0),
        "failed_events": len(stats.get("errors", [])) + ingestion["failed"],
        "applied_to_graph": stats.get("applied", 0),
        "not_graph_relevant": stats.get("skipped", 0),
        "completed": completed,
        "timed_out": not completed,
        "queue_depth_after": getattr(queue, "depth", None),
        "analysis_after_persistence": True,
        "analysis_performed": True,
    }

    # Reaching here means every expected event was persisted, queued and
    # projected — analysis ran on complete state.
    result["status"] = "completed"

    await emit("completed" if completed else "failed",
               status="ok" if completed else "timeout",
               rules=len(result.get("activated_rules", [])),
               has_recommendation=result.get("recommendation") is not None)
    return result
