"""Remote model service client.

When a ``*_MODEL_API_URL`` is configured, the backend calls that remote model
server over HTTP instead of loading the artifact in-process. The remote
response uses the identical ``ModelResponse`` envelope, so every downstream
consumer (scenario orchestrator, model events bridge, dashboard) is unchanged.

Reliability: configurable timeout, retry count and exponential backoff.
A remote failure NEVER fabricates a prediction — it returns a degraded
envelope with ``prediction=None`` and a ``degraded_reason`` describing the
transport error, exactly like a missing local artifact.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from app.services.model_service import (
    BaseModelService,
    InvalidFeaturesError,
    ModelResponse,
)

log = logging.getLogger("causalcut.models.remote")


class RemoteModelService(BaseModelService):
    """Calls a remote model endpoint, mirroring a local service's interface."""

    def __init__(
        self,
        name: str,
        url: str,
        *,
        timeout_s: float = 10.0,
        retries: int = 1,
        backoff_s: float = 0.25,
    ) -> None:
        super().__init__()
        self.name = name
        self.url = url
        self.timeout_s = timeout_s
        self.retries = max(0, retries)
        self.backoff_s = backoff_s
        self._loaded = True  # nothing to load locally

    @property
    def available(self) -> bool:
        return bool(self.status().get("available", False))

    def readiness(self) -> tuple[bool, str | None]:
        st = self.status()
        ready = bool(st.get("ready", False))
        return ready, st.get("degraded_reason")

    @property
    def artifact_path(self) -> str | None:
        return self.url

    # -------------------------------------------------------------- #
    def _post(self, payload: dict[str, Any], correlation_id: str) -> tuple[dict | None, str | None]:
        """POST with retry/backoff. Returns (body, error)."""
        last_err: str | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    r = client.post(
                        self.url, json=payload,
                        headers={"X-Correlation-ID": correlation_id},
                    )
                if r.status_code == 422:
                    # Contract violation — surface immediately, do not retry.
                    raise InvalidFeaturesError(
                        (r.json() or {}).get("detail", "remote rejected features"))
                if r.status_code >= 500 or r.status_code == 503:
                    last_err = f"remote HTTP {r.status_code}: {r.text[:160]}"
                else:
                    return r.json(), None
            except InvalidFeaturesError:
                raise
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"

            if attempt < self.retries:
                sleep_for = self.backoff_s * (2 ** attempt)
                log.warning("remote model '%s' attempt %d failed (%s); retrying in %.2fs",
                            self.name, attempt + 1, last_err, sleep_for)
                time.sleep(sleep_for)
        return None, last_err

    def _call(self, payload: dict[str, Any], correlation_id: str | None,
              scenario_id: str | None) -> ModelResponse:
        cid = correlation_id or str(uuid.uuid4())
        t0 = time.perf_counter()
        body, err = self._post(payload, cid)
        latency = round((time.perf_counter() - t0) * 1000, 3)

        if body is None:
            log.error("remote model '%s' unavailable: %s", self.name, err)
            return ModelResponse(
                model_name=self.name, model_version="unavailable", prediction=None,
                confidence=None, inference_mode="degraded", latency_ms=latency,
                correlation_id=cid, scenario_id=scenario_id, artifact_path=self.url,
                degraded_reason=f"remote model call failed: {err}",
            )

        # Preserve the remote envelope; annotate transport.
        extra = {k: v for k, v in body.items() if k not in {
            "model_name", "model_version", "prediction", "confidence",
            "inference_mode", "latency_ms", "correlation_id", "scenario_id",
            "artifact_path", "degraded_reason", "timestamp"}}
        extra["transport"] = "remote"
        extra["remote_url"] = self.url
        extra["remote_latency_ms"] = body.get("latency_ms")

        return ModelResponse(
            model_name=body.get("model_name", self.name),
            model_version=body.get("model_version", "unknown"),
            prediction=body.get("prediction"),
            confidence=body.get("confidence"),
            inference_mode=body.get("inference_mode", "real"),
            latency_ms=latency,  # wall-clock incl. network
            correlation_id=cid,
            scenario_id=scenario_id or body.get("scenario_id"),
            artifact_path=body.get("artifact_path") or self.url,
            degraded_reason=body.get("degraded_reason"),
            extra=extra,
        )

    # Maps this client to its entry in the model server's /models/status body.
    registry_key: str = "gas"

    def status(self) -> dict[str, Any]:
        """Query the model server's PER-MODEL readiness, not just /health.

        A model server can be perfectly healthy while a specific model is
        unusable (e.g. missing YOLO checkpoint, no torch). Reporting that model
        as available because ``/health`` returned 200 would be a false positive,
        so we read ``/api/v1/models/status`` and return this model's own entry.
        """
        base = self.url.split("/api/v1/")[0]
        try:
            with httpx.Client(timeout=max(self.timeout_s, 5.0)) as client:
                r = client.get(f"{base}/api/v1/models/status")
            if r.status_code != 200:
                return self._unavailable(f"remote /models/status HTTP {r.status_code}")
            body = r.json()
        except Exception as exc:
            return self._unavailable(f"remote unreachable: {exc}")

        entry = body.get(self.registry_key)
        if not isinstance(entry, dict):
            return self._unavailable(
                f"remote /models/status has no entry for '{self.registry_key}'")

        ready = bool(entry.get("ready", entry.get("available", False)))
        return {
            "model_name": entry.get("model_name", self.name),
            "model_version": entry.get("model_version", "remote"),
            "available": ready,
            "ready": ready,
            "artifact_found": entry.get("artifact_found"),
            "artifact_path": entry.get("artifact_path", self.url),
            "dependency_status": entry.get("dependency_status", {}),
            "load_status": "loaded" if ready else "not_loaded",
            "inference_mode": entry.get("inference_mode", "real" if ready else "unavailable"),
            "transport": "remote",
            "remote_url": self.url,
            "degraded_reason": entry.get("degraded_reason"),
        }

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "model_name": self.name, "model_version": "remote",
            "available": False, "ready": False, "artifact_found": None,
            "artifact_path": self.url, "dependency_status": {},
            "load_status": "unreachable", "inference_mode": "unavailable",
            "transport": "remote", "remote_url": self.url,
            "degraded_reason": reason,
        }


# --------------------------------------------------------------------------- #
# Concrete remote services (payloads match the model server's route schemas)
# --------------------------------------------------------------------------- #
class RemoteGasService(RemoteModelService):
    registry_key = "gas"

    def predict(self, features, sensor_id="GS-03", zone_id="zone-1",
                correlation_id=None, scenario_id=None, require_real=False):
        if features is None or len(features) != 128:
            raise InvalidFeaturesError(
                f"gas model expects 128 features, got {0 if features is None else len(features)}")
        return self._call({"features": list(features), "sensor_id": sensor_id,
                           "zone_id": zone_id, "scenario_id": scenario_id},
                          correlation_id, scenario_id)


class RemoteMachineService(RemoteModelService):
    registry_key = "machine"

    def predict(self, features: dict, correlation_id=None, scenario_id=None, require_real=False):
        payload = dict(features)
        payload["scenario_id"] = scenario_id
        return self._call(payload, correlation_id, scenario_id)


class RemoteHydraulicService(RemoteModelService):
    registry_key = "hydraulic"

    def predict(self, sensor_data: dict, correlation_id=None, scenario_id=None, require_real=False):
        return self._call({"sensor_data": sensor_data, "scenario_id": scenario_id},
                          correlation_id, scenario_id)


class RemoteVisionService(RemoteModelService):
    registry_key = "vision"

    def detect(self, image_ref, correlation_id=None, scenario_id=None, require_real=False):
        return self._call({"image_ref": image_ref, "scenario_id": scenario_id},
                          correlation_id, scenario_id)


class RemoteTrackingService(RemoteModelService):
    registry_key = "tracking"

    def update(self, detections, correlation_id=None, scenario_id=None, require_real=False):
        return self._call({"detections": detections, "scenario_id": scenario_id},
                          correlation_id, scenario_id)


class RemoteRegulatoryService(RemoteModelService):
    registry_key = "regulatory"

    def verify(self, actions, zone_context="", correlation_id=None, scenario_id=None):
        return self._call({"actions": list(actions), "zone_context": zone_context,
                           "scenario_id": scenario_id}, correlation_id, scenario_id)
