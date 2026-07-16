"""Request/response contracts for the ingestion boundary."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.canonical import SafetyEventIn
from app.schemas.enums import ProcessingStatus


class IngestBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[SafetyEventIn] = Field(min_length=1, max_length=500)


class IngestResult(BaseModel):
    event_id: uuid.UUID
    status: ProcessingStatus
    detail: str | None = None
    stale: bool = False


class IngestAck(BaseModel):
    """Returned by /events/ingest. 202 = durably persisted and queued."""

    correlation_id: str
    accepted: int
    duplicates: int
    rejected: int
    queue_depth: int
    results: list[IngestResult]


class QueueStats(BaseModel):
    depth: int
    max_size: int
    consumers: int
    enqueued_total: int
    processed_total: int
    failed_total: int
    dead_lettered_total: int


class ErrorResponse(BaseModel):
    error: str
    detail: str | object | None = None
    correlation_id: str | None = None
