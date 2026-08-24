"""Agent Orchestrator — G2/G5/G7 of the CAUSALCUT Gap Analysis.

Three thin agentic wrappers that sit OUTSIDE Stage 1-12 of the deterministic
pipeline. They read pipeline outputs and produce structured drafts/reports for
human review. They cannot write plant state, approve recommendations, or
trigger interventions.

Architecture constraint (see gap analysis §4.2):
  - These agents NEVER sit in the critical Stage 1-12 detection path.
  - Agent failures (LLM timeout, bad output) cannot degrade the CP-SAT
    recommendation pipeline.
  - All agent output goes through the existing human approval gateway.
  - The deterministic MinimumCausalCutOptimiser is untouched.

Agent 1 -- Response Drafting (G2/G5):
  Triggered when a CutRecommendation crosses a severity threshold.
  Produces: SMS alert, PA script, evacuation checklist, DGMS incident report.

Agent 2 -- Incident Pattern Mining (G2/G4):
  Runs on demand, cross-references AccidentPath history against incident RAG.
  Produces: candidate new bow-tie definitions for safety-engineer review.

Agent 3 -- Compliance Audit Scorecard (G2/G7):
  Runs against current plant state, independent of Stage 7-11.
  Produces: per-clause OISD/DGMS compliance status + at-risk flags.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("causalcut.agents")

# Gemini API key -- inherited from settings, passed in at call time.
_SEVERITY_THRESHOLD = 0.70   # above this, Agent 1 auto-drafts

# ------------------------------------------------------------------ #
# Shared LLM helper (Gemini + Groq)
# ------------------------------------------------------------------ #

def _llm_generate(
    prompt: str,
    api_key: str,
    model: str = "gemini-2.0-flash",
    provider: str = "gemini",
    groq_api_key: str | None = None,
) -> str:
    """Call the configured LLM provider and return the text response.

    provider="gemini" (default): uses google.generativeai with *api_key*.
    provider="groq": uses the groq SDK with *groq_api_key* (falls back to
        *api_key* if groq_api_key is not set, for convenience).

    Returns an error string on failure so callers can surface it gracefully.
    """
    if provider == "groq":
        return _groq_generate(prompt, groq_api_key or api_key, model)
    return _gemini_generate(prompt, api_key, model)


def _gemini_generate(prompt: str, api_key: str, model: str = "gemini-2.0-flash") -> str:
    """Call Gemini and return the text response. Returns an error string on failure."""
    try:
        import google.generativeai as genai
    except ImportError as exc:
        return f"[Agent unavailable: {exc}]"

    keys = [k.strip() for k in api_key.split(",") if k.strip()]
    last_exc = None

    for k in keys:
        try:
            genai.configure(api_key=k)
            m = genai.GenerativeModel(model)
            response = m.generate_content(prompt)
            return response.text
        except Exception as exc:
            last_exc = exc
            logger.warning("gemini call failed with a key: %s", exc)

    return f"[Agent unavailable: {last_exc}]"


def _groq_generate(prompt: str, api_key: str, model: str = "openai/gpt-oss-120b") -> str:
    """Call Groq and return the text response. Returns an error string on failure."""
    try:
        from groq import Groq
    except ImportError as exc:
        return f"[Agent unavailable — groq package not installed: {exc}]"

    keys = [k.strip() for k in api_key.split(",") if k.strip()]
    last_exc = None

    for k in keys:
        try:
            client = Groq(api_key=k)
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            last_exc = exc
            logger.warning("groq call failed with a key: %s", exc)

    return f"[Agent unavailable: {last_exc}]"


# ------------------------------------------------------------------ #
# Agent 1 -- Response Drafting Agent (G2 / G5)
# ------------------------------------------------------------------ #

def draft_emergency_response(
    cut_dict: dict[str, Any],
    path_dict: dict[str, Any],
    api_key: str,
    model: str = "gemini-2.0-flash",
    provider: str = "gemini",
    groq_api_key: str | None = None,
) -> dict[str, Any]:
    """Agent 1: draft emergency response artifacts for a confirmed high-severity cut.

    Args:
        cut_dict:  CutRecommendation.to_dict() output
        path_dict: AccidentPath.to_dict() output for the highest-severity path
        api_key:   Gemini API key
        model:     Gemini model name

    Returns:
        ResponseDraft dict with status="agent_proposed" -- never "approved".
        All fields must be reviewed and approved by a safety_manager via the
        existing /risk/approve gateway before any physical action is taken.
    """
    residual = cut_dict.get("residual_risk", 0.0)
    if residual < _SEVERITY_THRESHOLD:
        return {
            "status": "below_threshold",
            "detail": f"Residual risk {residual:.2f} below draft threshold {_SEVERITY_THRESHOLD}",
        }

    zone = path_dict.get("root_zone", "unknown")
    pathway = path_dict.get("pathway", "unknown")
    top_event = path_dict.get("top_event", "unspecified top event")
    factors = path_dict.get("contributing_factors", [])
    interventions = cut_dict.get("interventions", [])
    prop_zones = path_dict.get("propagation_zones", [])

    prompt = f"""You are a process-safety emergency response drafter for a coke-oven steel plant.
A CAUSALCUT risk engine has confirmed a high-severity accident pathway and the minimum-causal-cut
optimiser has computed a recommended intervention set. You must draft response artifacts for a safety
manager to REVIEW and APPROVE before anything is executed.

== RISK SUMMARY ==
Zone: {zone}
Pathway: {pathway}
Top Event: {top_event}
Contributing factors: {factors}
Residual risk: {residual:.2f} (threshold: 0.15)
Propagation zones: {prop_zones}

== RECOMMENDED INTERVENTIONS (from CP-SAT optimiser) ==
{json.dumps(interventions, indent=2)}

== INSTRUCTIONS ==
Produce the following as a JSON object with these exact keys:
- "sms_alert": a 160-char SMS text for the emergency contact list
- "pa_announcement": a 30-second PA announcement script (plain text)
- "dashboard_banner": a 1-sentence dashboard alert banner
- "evacuation_checklist": list of objects with "step" (int), "action" (str), "zone" (str), "priority" (str)
  ordered by risk descending (highest-risk zones evacuated first)
- "incident_report_skeleton": object with keys:
    "report_type": "DGMS Form 10 / OISD Preliminary Incident Report"
    "date_time": current UTC ISO timestamp
    "zone": root zone
    "hazard_description": 2-3 sentences describing the hazard chain
    "causal_chain": list of event strings in [M]/[P]/[C] tagged format
    "immediate_actions_recommended": list of strings from interventions
    "audit_reference": "PENDING - to be filled on approval"
    "information_class": "AGENT_PROPOSED [S] - requires human verification before submission"

Respond ONLY with valid JSON. No markdown, no explanation outside the JSON.
"""

    raw = _llm_generate(prompt, api_key, model, provider=provider, groq_api_key=groq_api_key)

    # Try to parse JSON; if it fails, return a structured error that still
    # surfaces the raw text so the operator has something to work with.
    try:
        # Strip markdown code fences if the model wrapped them
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
        if cleaned.endswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[:-1])
        draft = json.loads(cleaned)
    except json.JSONDecodeError:
        draft = {"raw_text": raw, "parse_error": "LLM did not return valid JSON"}

    return {
        "status": "agent_proposed",
        "information_class": "S",
        "note": (
            "PROPOSAL ONLY. This draft was generated by an AI agent and has NOT been "
            "approved. A safety_manager must review and approve via POST /risk/approve "
            "before any action is taken. Physical interventions are NOT triggered by "
            "generating this draft."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root_zone": zone,
        "pathway": pathway,
        "residual_risk": residual,
        "draft": draft,
    }


# ------------------------------------------------------------------ #
# Agent 2 -- Incident Pattern Mining Agent (G2 / G4)
# ------------------------------------------------------------------ #

def mine_incident_patterns(
    recent_paths: list[dict[str, Any]],
    api_key: str,
    model: str = "gemini-2.0-flash",
    rag_url: str | None = None,
    provider: str = "gemini",
    groq_api_key: str | None = None,
) -> dict[str, Any]:
    """Agent 2: cross-reference recent AccidentPath history against the incident corpus.

    Args:
        recent_paths: list of AccidentPath.to_dict() outputs
        api_key:      Gemini API key
        model:        Gemini model name
        rag_url:      optional URL for the regulatory_rag /api/patterns/query endpoint

    Returns:
        Dict with candidate bow-tie definitions and similar incident references.
    """
    if not recent_paths:
        return {"status": "no_paths", "patterns": []}

    # Summarise the recent paths for the prompt
    path_summaries = [
        {
            "hyperedge_id": p.get("hyperedge_id"),
            "pathway": p.get("pathway"),
            "top_event": p.get("top_event", ""),
            "contributing_factors": p.get("contributing_factors", []),
            "severity": p.get("severity"),
            "zone": p.get("root_zone"),
        }
        for p in recent_paths
    ]

    # Query the incident RAG if available
    similar_incidents: list[dict] = []
    if rag_url:
        try:
            import httpx
            for ps in path_summaries[:3]:  # top 3 paths
                resp = httpx.post(
                    f"{rag_url}/api/patterns/query",
                    json={"pathway": ps["pathway"], "contributing_factors": ps["contributing_factors"]},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    similar_incidents.extend(resp.json().get("incidents", []))
        except Exception as exc:
            logger.warning("incident RAG query failed: %s", exc)

    prompt = f"""You are a process-safety pattern analysis agent for a coke-oven steel plant.
Review the recent accident paths detected by CAUSALCUT and identify recurring precursor combinations
that may warrant a new or updated bow-tie rule definition.

== RECENT ACCIDENT PATHS ==
{json.dumps(path_summaries, indent=2)}

== SIMILAR HISTORICAL INCIDENTS (from incident corpus) ==
{json.dumps(similar_incidents[:5], indent=2) if similar_incidents else "None retrieved from corpus."}

== TASK ==
1. Identify any recurring factor combinations across the paths above.
2. For each pattern found, produce a candidate bow-tie definition as a JSON object with keys:
   - "candidate_id": a new unique ID like "HE-CANDIDATE-001"
   - "hazard_description": 1-2 sentences describing the hazard
   - "top_event": the loss-of-control event
   - "recurring_factors": list of factor strings (from contributing_factors)
   - "suggested_source_reference": HAZOP worksheet / OISD clause to investigate
   - "rationale": why this pattern warrants a new bow-tie rule
   - "information_class": "AGENT_PROPOSED [S]"
3. If no significant new pattern is found, return an empty patterns list.

Return ONLY a JSON object with key "patterns" (list of candidate bow-tie objects).
"""

    raw = _llm_generate(prompt, api_key, model, provider=provider, groq_api_key=groq_api_key)
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        result = {"patterns": [], "raw_text": raw, "parse_error": "LLM did not return valid JSON"}

    return {
        "status": "agent_proposed",
        "information_class": "S",
        "note": (
            "Pattern candidates are PROPOSALS for safety-engineer review. "
            "A new CompoundRule is only added after human expert validation."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paths_analyzed": len(recent_paths),
        "similar_incidents_retrieved": len(similar_incidents),
        **result,
    }


# ------------------------------------------------------------------ #
# Agent 3 -- Compliance Audit Scorecard (G2 / G7)
# ------------------------------------------------------------------ #

def run_compliance_scorecard(
    plant_state: dict[str, Any],
    api_key: str,
    model: str = "gemini-2.0-flash",
    rag_url: str | None = None,
    provider: str = "gemini",
    groq_api_key: str | None = None,
) -> dict[str, Any]:
    """Agent 3: produce a continuous compliance scorecard against plant state.

    Runs independently of Stage 7-11 (not triggered by an active accident path).
    Checks current barrier health, permit status, and zone state against
    OISD/DGMS clauses via the regulatory RAG.

    Args:
        plant_state: dict from /api/v1/state (zones, permits, barriers)
        api_key:     Gemini API key
        model:       Gemini model name
        rag_url:     optional URL for the regulatory_rag /api/verify endpoint

    Returns:
        ComplianceScorecard dict with per-clause satisfaction status.
    """
    # Key clauses to check from OISD-STD-105/114/137, Factories Act 1948
    CLAUSES = [
        {"clause": "OISD-STD-105 §7.3", "topic": "Hot-work permit procedures", "check": "active_permits"},
        {"clause": "OISD-STD-105 §8.1", "topic": "Gas detection and PPE in hazardous zones", "check": "ppe_compliance"},
        {"clause": "OISD-STD-114 §4.2", "topic": "Atmospheric monitoring thresholds", "check": "gas_levels"},
        {"clause": "OISD-STD-114 §6.1", "topic": "Ventilation adequacy in occupied zones", "check": "ventilation"},
        {"clause": "OISD-STD-137 §4.3", "topic": "Equipment inspection and proof-test intervals", "check": "barriers"},
        {"clause": "Factories Act 1948 §13", "topic": "Ventilation in workplaces", "check": "ventilation"},
        {"clause": "Factories Act 1948 §21", "topic": "Fencing of machinery", "check": "equipment"},
        {"clause": "DGMS Circular 2019-04", "topic": "Gas safety in mines and quarries", "check": "gas_levels"},
    ]

    prompt = f"""You are a regulatory compliance audit agent for a coke-oven steel plant operating
under OISD-STD-105/114/137, Factories Act 1948, and DGMS circulars.

== CURRENT PLANT STATE ==
{json.dumps(plant_state, indent=2, default=str)}

== CLAUSES TO ASSESS ==
{json.dumps(CLAUSES, indent=2)}

== TASK ==
For each clause, assess the current plant state and return a JSON object with key "scorecard"
containing a list of objects with:
- "clause": the clause reference
- "topic": clause topic
- "status": one of "satisfied" | "at_risk" | "violated" | "insufficient_data"
- "reason": 1-2 sentences explaining the status
- "zone": affected zone(s) if applicable, else null
- "recommended_action": brief action string if status is at_risk or violated, else null
- "information_class": "AGENT_PROPOSED [S]"

Also include a "summary" key with overall compliance percentage (satisfied / total).

Return ONLY valid JSON.
"""

    raw = _llm_generate(prompt, api_key, model, provider=provider, groq_api_key=groq_api_key)
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        result = {"scorecard": [], "summary": "parse_error", "raw_text": raw}

    satisfied = sum(1 for item in result.get("scorecard", []) if item.get("status") == "satisfied")
    total = len(result.get("scorecard", []))

    return {
        "status": "agent_proposed",
        "information_class": "S",
        "note": (
            "Compliance scorecard is an AI-generated assessment [S]. "
            "It does not replace a formal regulatory audit. Violations must be "
            "verified by a qualified safety officer."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clauses_checked": total,
        "satisfied": satisfied,
        "compliance_rate": round(satisfied / total, 2) if total > 0 else None,
        **result,
    }
