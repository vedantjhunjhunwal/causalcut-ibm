"""Blueprint ingestion & analysis routes.

POST /blueprints/analyze  — takes a base64-encoded blueprint image +
                            industry context, calls Gemini 3.1 Flash Lite
                            vision, returns zones/adjacency/sensors JSON
                            directly compatible with the Scenario schema.

The endpoint is intentionally stateless: it does NOT persist anything.
Persistence (Supabase Storage + DB) will be wired in once the Supabase
client is added in a later sprint. The contract is stable now.
"""

from __future__ import annotations

import base64
import json
import os
import re
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

log = logging.getLogger("causalcut.blueprint")

router = APIRouter(prefix="/blueprints", tags=["blueprint"])


# --------------------------------------------------------------------------- #
# Request / Response schemas                                                  #
# --------------------------------------------------------------------------- #

HAZARD_CLASSES = ["flammable", "toxic", "confined_space", "electrical", "general", "standard"]
SENSOR_MODALITIES = ["gas", "temperature", "pressure", "vibration", "smoke", "flame"]
INDUSTRY_TYPES = ["steel", "oil_gas", "chemical", "mining", "pharmaceutical", "general"]


class BlueprintAnalyzeRequest(BaseModel):
    """Payload for blueprint analysis."""
    image_b64: str = Field(
        ...,
        description="Base64-encoded blueprint image (PNG/JPEG/PDF page render).",
    )
    image_mime: str = Field(
        default="image/png",
        description="MIME type of the image (image/png, image/jpeg).",
    )
    industry_type: str = Field(
        default="general",
        description="Industry type hint to improve zone classification.",
    )
    factory_name: str = Field(
        default="Factory",
        description="Factory name for context.",
    )
    floor_label: str = Field(
        default="Ground Floor",
        description="Floor/level label (e.g. Ground Floor, Level 2).",
    )


class ZoneResult(BaseModel):
    zone_id: str
    name: str
    hazard_class: str
    baseline_gas_threshold_ppm: float
    ventilation_status: str
    ventilation_flow_ratio: float
    # Spatial hints for canvas rendering (normalized 0-1 relative to image)
    x_norm: float = Field(ge=0.0, le=1.0)
    y_norm: float = Field(ge=0.0, le=1.0)
    w_norm: float = Field(ge=0.0, le=1.0)
    h_norm: float = Field(ge=0.0, le=1.0)


class AdjacencyResult(BaseModel):
    zone_a: str
    zone_b: str
    medium: str


class SensorResult(BaseModel):
    sensor_id: str
    zone_id: str
    modality: str
    unit: str
    x_norm: float = Field(ge=0.0, le=1.0)
    y_norm: float = Field(ge=0.0, le=1.0)


class BlueprintAnalysisOutput(BaseModel):
    zones: list[ZoneResult]
    zone_adjacency: list[AdjacencyResult]
    sensors: list[SensorResult]
    analysis_notes: str


class BlueprintAnalyzeResponse(BlueprintAnalysisOutput):
    """
    Zones, adjacencies, and suggested sensors extracted from the blueprint.
    The `zones` and `zone_adjacency` arrays can be dropped directly into a
    Scenario payload. `sensors` can likewise be used as-is.
    """
    model_used: str


# --------------------------------------------------------------------------- #
# Prompt builder                                                               #
# --------------------------------------------------------------------------- #

def _build_prompt(factory_name: str, industry_type: str, floor_label: str) -> str:
    return f"""You are an expert industrial safety engineer analyzing a factory floor blueprint image.

Factory: {factory_name}
Industry: {industry_type}
Floor/Level: {floor_label}

Analyze the blueprint image carefully and extract all distinct zones/rooms/areas you can identify.

Return ONLY a JSON object with this exact structure (no markdown, no explanation, just the raw JSON):

{{
  "zones": [
    {{
      "zone_id": "zone-1",
      "name": "Human readable zone name",
      "hazard_class": "one of: flammable | toxic | confined_space | electrical | general | standard",
      "baseline_gas_threshold_ppm": 200.0,
      "ventilation_status": "nominal",
      "ventilation_flow_ratio": 1.0,
      "x_norm": 0.1,
      "y_norm": 0.1,
      "w_norm": 0.2,
      "h_norm": 0.15
    }}
  ],
  "zone_adjacency": [
    {{
      "zone_a": "zone-1",
      "zone_b": "zone-2",
      "medium": "doorway | shared_ventilation | corridor | shared_utility | open_area"
    }}
  ],
  "sensors": [
    {{
      "sensor_id": "sensor-1",
      "zone_id": "zone-1",
      "modality": "one of: gas | temperature | pressure | vibration | smoke | flame",
      "unit": "ppm | celsius | bar | g | aqi | boolean",
      "x_norm": 0.15,
      "y_norm": 0.12
    }}
  ],
  "analysis_notes": "Brief description of what was identified"
}}

Rules:
- zone_id must be "zone-N" (zone-1, zone-2, etc.)
- sensor_id must be "sensor-N"
- x_norm, y_norm are the top-left corner of the zone bounding box as fractions of image width/height (0.0 to 1.0)
- w_norm, h_norm are width/height as fractions (0.0 to 1.0)
- All coordinates must be between 0.0 and 1.0
- Assign hazard_class based on likely function: boiler rooms / furnaces = flammable, chemical stores = toxic, tanks / pits = confined_space, switchgear = electrical
- Set baseline_gas_threshold_ppm based on hazard class: flammable=150, toxic=100, general=300
- Add at least one sensor per zone (gas for flammable/toxic, temperature for heat zones, general gas otherwise)
- Identify all adjacencies (shared walls with doorways, shared ventilation ducts, open corridors)
- If the image is unclear or not a blueprint, still return a minimal valid structure with at least one zone
- Return ONLY the JSON object, nothing else"""


# --------------------------------------------------------------------------- #
# Gemini call                                                                  #
# --------------------------------------------------------------------------- #

def _call_gemini(image_b64: str, image_mime: str, prompt: str) -> dict[str, Any]:
    """Call Gemini 3.1 Flash Lite with the blueprint image and return parsed JSON."""
    try:
        from google import genai                          # type: ignore
        from google.genai import types as gtypes         # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="google-genai package not installed. Run: pip install google-genai",
        )

    from app.core.config import get_settings
    settings = get_settings()
    api_key_str = settings.gemini_api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key_str:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CAUSALCUT_GEMINI_API_KEY environment variable not set.",
        )

    keys = [k.strip() for k in api_key_str.split(",") if k.strip()]
    image_bytes = base64.b64decode(image_b64)
    last_exc = None
    response = None

    for key in keys:
        client = genai.Client(api_key=key)
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=[
                    gtypes.Content(parts=[
                        gtypes.Part(text=prompt),
                        gtypes.Part(
                            inline_data=gtypes.Blob(mime_type=image_mime, data=image_bytes)
                        ),
                    ])
                ],
                config=gtypes.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                    response_schema=BlueprintAnalysisOutput,
                ),
            )
            break # Success, stop iterating over keys
        except Exception as exc:
            log.warning("Gemini API call failed with a key: %s", exc)
            last_exc = exc

    if response is None:
        log.error("Gemini API call failed for all keys. Last error: %s", last_exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini API error: {last_exc}",
        )

    raw = response.text.strip()

    # Strip markdown code fences if Gemini wraps the JSON
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse Gemini response as JSON: %s\nRaw: %s", exc, raw[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini returned non-JSON output: {raw[:200]}",
        )


# --------------------------------------------------------------------------- #
# Validation & normalisation helpers                                           #
# --------------------------------------------------------------------------- #

def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _validate_and_clean(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitise Gemini output, filling in safe defaults."""
    zones_raw = raw.get("zones", [])
    adjacency_raw = raw.get("zone_adjacency", [])
    sensors_raw = raw.get("sensors", [])

    # --- Zones ---
    valid_zone_ids: set[str] = set()
    zones: list[dict] = []
    for i, z in enumerate(zones_raw):
        zid = z.get("zone_id", f"zone-{i + 1}")
        valid_zone_ids.add(zid)
        hc = z.get("hazard_class", "general")
        if hc not in HAZARD_CLASSES:
            hc = "general"
        zones.append({
            "zone_id": zid,
            "name": z.get("name", f"Zone {i + 1}"),
            "hazard_class": hc,
            "baseline_gas_threshold_ppm": float(z.get("baseline_gas_threshold_ppm", 200.0)),
            "ventilation_status": z.get("ventilation_status", "nominal"),
            "ventilation_flow_ratio": float(z.get("ventilation_flow_ratio", 1.0)),
            "x_norm": _clamp(z.get("x_norm", 0.05 + i * 0.15)),
            "y_norm": _clamp(z.get("y_norm", 0.05)),
            "w_norm": _clamp(z.get("w_norm", 0.2)),
            "h_norm": _clamp(z.get("h_norm", 0.2)),
        })

    if not zones:
        # Absolute fallback: one generic zone
        zones = [{
            "zone_id": "zone-1",
            "name": "Main Floor",
            "hazard_class": "general",
            "baseline_gas_threshold_ppm": 200.0,
            "ventilation_status": "nominal",
            "ventilation_flow_ratio": 1.0,
            "x_norm": 0.1, "y_norm": 0.1, "w_norm": 0.8, "h_norm": 0.8,
        }]
        valid_zone_ids.add("zone-1")

    # --- Adjacencies ---
    adjacency: list[dict] = []
    for a in adjacency_raw:
        za, zb = a.get("zone_a"), a.get("zone_b")
        if za in valid_zone_ids and zb in valid_zone_ids and za != zb:
            adjacency.append({
                "zone_a": za,
                "zone_b": zb,
                "medium": a.get("medium", "shared_utility"),
            })

    # --- Sensors ---
    sensors: list[dict] = []
    for i, s in enumerate(sensors_raw):
        zid = s.get("zone_id")
        if zid not in valid_zone_ids:
            continue
        mod = s.get("modality", "gas")
        if mod not in SENSOR_MODALITIES:
            mod = "gas"
        sensors.append({
            "sensor_id": s.get("sensor_id", f"sensor-{i + 1}"),
            "zone_id": zid,
            "modality": mod,
            "unit": s.get("unit", "ppm"),
            "x_norm": _clamp(s.get("x_norm", 0.1)),
            "y_norm": _clamp(s.get("y_norm", 0.1)),
        })

    # Ensure every zone has at least one sensor
    zones_with_sensors = {s["zone_id"] for s in sensors}
    for idx, z in enumerate(zones):
        if z["zone_id"] not in zones_with_sensors:
            mod = "gas" if z["hazard_class"] in ("flammable", "toxic") else "temperature"
            unit = "ppm" if mod == "gas" else "celsius"
            sensors.append({
                "sensor_id": f"sensor-auto-{idx + 1}",
                "zone_id": z["zone_id"],
                "modality": mod,
                "unit": unit,
                "x_norm": _clamp(z["x_norm"] + z["w_norm"] * 0.5),
                "y_norm": _clamp(z["y_norm"] + z["h_norm"] * 0.5),
            })

    return {
        "zones": zones,
        "zone_adjacency": adjacency,
        "sensors": sensors,
        "analysis_notes": raw.get("analysis_notes", "Blueprint analyzed."),
    }


# --------------------------------------------------------------------------- #
# Route                                                                        #
# --------------------------------------------------------------------------- #

@router.post(
    "/analyze",
    response_model=BlueprintAnalyzeResponse,
    summary="Analyze a factory blueprint image with Gemini Vision",
    description=(
        "Accepts a base64-encoded blueprint image and calls Gemini 3.1 Flash Lite "
        "to extract zones, adjacencies, and suggested sensors. The returned JSON "
        "is directly compatible with the Scenario schema's `zones`, `zone_adjacency`, "
        "and `sensors` fields. Coordinates are normalized (0–1) relative to image size."
    ),
)
async def analyze_blueprint(req: BlueprintAnalyzeRequest) -> BlueprintAnalyzeResponse:
    prompt = _build_prompt(req.factory_name, req.industry_type, req.floor_label)

    log.info(
        "Blueprint analysis request",
        extra={"factory": req.factory_name, "industry": req.industry_type},
    )

    raw = _call_gemini(req.image_b64, req.image_mime, prompt)
    cleaned = _validate_and_clean(raw)

    return BlueprintAnalyzeResponse(
        zones=[ZoneResult(**z) for z in cleaned["zones"]],
        zone_adjacency=[AdjacencyResult(**a) for a in cleaned["zone_adjacency"]],
        sensors=[SensorResult(**s) for s in cleaned["sensors"]],
        analysis_notes=cleaned["analysis_notes"],
        model_used="gemini-3.1-flash-lite",
    )
