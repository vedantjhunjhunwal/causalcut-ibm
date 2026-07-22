"""Standalone CAUSALCUT model server.

Runs the trained artifacts as a SEPARATE service (e.g. on a GPU box) so the
main backend can call them over HTTP instead of loading them in-process.

Crucially this reuses the exact same shared service layer
(``app.services.model_service``) as the in-process path — there is still only
one implementation of model loading, preprocessing and inference. This process
just puts an HTTP boundary in front of it.

Run:
    uvicorn model_server.server:app --host 0.0.0.0 --port 9000

Then point the backend at it:
    CAUSALCUT_GAS_MODEL_API_URL=http://localhost:9000/api/v1/models/gas/predict
    CAUSALCUT_MACHINE_MODEL_API_URL=http://localhost:9000/api/v1/models/machine-failure/predict
    ...
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from app.api.v1.routes.models import router as models_router

logging.basicConfig(
    level=os.getenv("MODEL_SERVER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("causalcut.model_server")

app = FastAPI(
    title="CAUSALCUT Model Server",
    description=(
        "Standalone inference service for the CAUSALCUT trained artifacts "
        "(gas XGBoost + IsolationForest, AI4I LightGBM, hydraulic LightGBM, "
        "YOLOv8 vision, ByteTrack, FAISS regulatory RAG)."
    ),
    version="1.0.0",
)

# Same router, same shared services — no duplicated model logic.
app.include_router(models_router, prefix="/api/v1")


@app.on_event("startup")
async def _warm() -> None:
    """Eagerly load artifacts so the first real request isn't slow."""
    from app.services.model_service import get_registry

    status = get_registry().status_all()
    for name, st in status.items():
        log.info(
            "model %s: available=%s artifact=%s %s",
            name, st["available"], st["artifact_path"],
            f"({st['degraded_reason']})" if st["degraded_reason"] else "",
        )


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "causalcut-model-server"}
