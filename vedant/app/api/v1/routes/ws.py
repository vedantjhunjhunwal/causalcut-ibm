"""WebSocket progress feed for scenario execution.

Clients POST ``/scenario/start``, get a ``run_id`` back immediately, then
connect to ``/ws/scenarios/{run_id}`` and receive the *real* backend pipeline
stages as they happen::

    {"stage": "queue_processing", "label": "Queue processing", "index": 3,
     "total": 13, "status": "running", "elapsed_ms": 42.7, "seq": 4,
     "run_id": "run-ab12cd34ef"}

Two properties make this safe for a browser client:

* **Replay.** Progress is recorded per run, so a client that connects a few
  hundred milliseconds after ``/scenario/start`` returns — or one that
  reconnects after a dropped socket — still receives every stage that already
  happened, in order, before the live feed resumes. Nothing is "simulated" to
  fill the gap; the replayed messages are the ones the pipeline actually
  emitted.
* **No gaps, no duplicates.** The subscriber queue is registered *before* the
  history snapshot is taken, so a message emitted during replay cannot be
  lost. Each message carries a monotonic per-run ``seq``, so anything already
  replayed is filtered out of the live stream.

One asyncio.Queue per client, no polling. Disconnection is silent and never
affects the running pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
from itertools import count
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("causalcut.ws")

router = APIRouter(tags=["websocket"])

# Subscriber registry keyed by run_id. A client that subscribes to
# /ws/scenarios/{run_id} receives ONLY that run's progress — scenario runs are
# not broadcast to every connected client. The legacy key "*" preserves the
# old firehose endpoint for debugging.
_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
_lock = asyncio.Lock()

FIREHOSE = "*"

# Terminal stages. Once one of these is broadcast for a run, that run's feed is
# finished: the pipeline has settled and the result is fetchable from
# GET /scenario/runs/{run_id}.
TERMINAL_STAGES = frozenset({"completed", "failed"})

# Replay buffer: run_id -> ordered progress messages.
_history: dict[str, list[dict[str, Any]]] = {}
_seq = count(1)

# Bounds so a long-lived server cannot grow without limit.
MAX_HISTORY_PER_RUN = 512
MAX_RUNS_RETAINED = 64


async def subscribe(run_id: str = FIREHOSE) -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    async with _lock:
        _subscribers.setdefault(run_id, []).append(q)
    return q


async def unsubscribe(q: asyncio.Queue[dict[str, Any]], run_id: str = FIREHOSE) -> None:
    async with _lock:
        lst = _subscribers.get(run_id, [])
        try:
            lst.remove(q)
        except ValueError:
            pass
        if not lst:
            _subscribers.pop(run_id, None)


def _remember(msg: dict[str, Any]) -> None:
    """Append to the run's replay buffer, evicting the oldest runs first."""
    run_id = msg.get("run_id")
    if not run_id:
        return
    buf = _history.setdefault(run_id, [])
    buf.append(msg)
    if len(buf) > MAX_HISTORY_PER_RUN:
        del buf[: len(buf) - MAX_HISTORY_PER_RUN]
    while len(_history) > MAX_RUNS_RETAINED:
        _history.pop(next(iter(_history)))


def history(run_id: str) -> list[dict[str, Any]]:
    """The stages already emitted for a run (used for replay and polling)."""
    return list(_history.get(run_id, []))


async def broadcast_progress(msg: dict[str, Any]) -> None:
    """Record then deliver a progress update to that run's subscribers.

    The message is stamped with a monotonic ``seq`` so a replaying client can
    tell which messages it has already seen.
    """
    msg = {**msg, "seq": next(_seq)}
    async with _lock:
        _remember(msg)
        targets: list[asyncio.Queue] = []
        run_id = msg.get("run_id")
        if run_id and run_id in _subscribers:
            targets += _subscribers[run_id]
        targets += _subscribers.get(FIREHOSE, [])
        for q in list(targets):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # slow client: drop this update rather than block


def subscriber_count(run_id: str | None = None) -> int:
    if run_id is None:
        return sum(len(v) for v in _subscribers.values())
    return len(_subscribers.get(run_id, []))


def reset_history() -> None:
    """Test hook: forget every recorded run."""
    _history.clear()


@router.websocket("/ws/scenarios/{run_id}")
async def ws_scenario(websocket: WebSocket, run_id: str) -> None:
    """Per-run progress feed — a client sees only the run it asked for.

    Order matters: subscribe first, snapshot second. A message emitted between
    the two lands in the queue and is de-duplicated by ``seq`` rather than
    being lost.
    """
    await websocket.accept()
    q = await subscribe(run_id)
    try:
        await websocket.send_text(json.dumps(
            {"stage": "subscribed", "run_id": run_id, "label": "Subscribed"}))

        # --- replay everything this run has already emitted ---------------
        async with _lock:
            replay = list(_history.get(run_id, []))
        last_seq = replay[-1].get("seq", 0) if replay else 0
        finished = False
        for msg in replay:
            await websocket.send_text(json.dumps(msg))
            if msg.get("stage") in TERMINAL_STAGES:
                finished = True
        if finished:
            # The run had already settled before this client connected; the
            # replay above delivered the terminal stage, so there is nothing
            # further to stream.
            return

        # --- live feed ----------------------------------------------------
        while True:
            msg = await q.get()
            if msg.get("seq", 0) <= last_seq:
                continue  # already delivered during replay
            await websocket.send_text(json.dumps(msg))
            if msg.get("stage") in TERMINAL_STAGES:
                return
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await unsubscribe(q, run_id)


@router.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket) -> None:
    """Legacy firehose (all runs) — kept for debugging/back-compat."""
    await websocket.accept()
    q = await subscribe(FIREHOSE)
    try:
        while True:
            msg = await q.get()
            await websocket.send_text(json.dumps(msg))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await unsubscribe(q, FIREHOSE)
