import json

class ExplanationRenderer:
    """
    LLM Explanation Layer (Section 4.10) - MVP Template-Based Version.
    Converts validated causal cuts and regulatory evidence into an operator-readable summary.
    Does NOT calculate risk or select interventions (per safety constraints).
    """
    
    def __init__(self):
        pass
        
    def render_explanation(self, intervention_recommendation: dict, verifier_result: dict) -> str:
        """
        Constructs the final human-readable explanation combining the cut and citations.
        
        Args:
            intervention_recommendation: Output from the Minimum-Causal-Cut Optimiser.
            verifier_result: Output from the ComplianceVerifier.
            
        Returns:
            A formatted markdown string for the Operator Console.
        """
        
        # Extract interventions
        actions = intervention_recommendation.get("interventions", [])
        action_list_str = "\n".join([f"  {i+1}. {a['action']}" for i, a in enumerate(actions)])
        
        # Extract risk metrics
        risk_before = intervention_recommendation.get("risk_before", "N/A")
        risk_after = intervention_recommendation.get("residual_risk", "N/A")
        cost = intervention_recommendation.get("total_cost", "N/A")
        
        # Extract evidence
        status = verifier_result.get("compliance_status", "unverified").upper()
        evidence_list = verifier_result.get("evidence", [])
        
        if evidence_list:
            citations_str = "\n".join(
                [f"   - **{ev.get('citation', 'Unknown')}** [{ev.get('source_type', 'N/A')}]:\n     \"{ev.get('text', '').strip()[:150]}...\"" for ev in evidence_list]
            )
        else:
            citations_str = "   - No specific regulatory clauses retrieved or index unavailable."
            
        # Construct template
        template = f"""
======================================================================
RECOMMENDED MINIMUM-CAUSAL-CUT
======================================================================
The system recommends the following minimum action set to reduce 
compound risk below the safety threshold:

SELECTED INTERVENTIONS:
{action_list_str}

RISK ASSESSMENT:
 - Risk Before:  {risk_before}
 - Risk After:   {risk_after}  (Counterfactual Estimate)
 - Total Cost:   {cost}

REGULATORY COMPLIANCE: [{status}]
{citations_str}

STATUS: AWAITING HUMAN APPROVAL
REQUIRED APPROVER: Shift Officer
======================================================================
"""
        return template.strip()

if __name__ == "__main__":
    renderer = ExplanationRenderer()
    
    mock_recommendation = {
        "interventions": [
            {"action": "SUSPEND PERMIT PTW-007 (hot work, Zone 1)"},
            {"action": "EVACUATE WORKER W-003 FROM ZONE 1"}
        ],
        "risk_before": 0.82,
        "residual_risk": 0.08,
        "total_cost": "LOW"
    }
    
    mock_verifier_result = {
        "compliance_status": "compliant",
        "evidence": [
            {
                "citation": "OISD-STD-116 Clause 4.3",
                "source_type": "oisd_standard",
                "text": "Hot work shall be stopped immediately when hazardous atmosphere is detected."
            },
            {
                "citation": "Factories Act 1948 Section 41",
                "source_type": "factories_act",
                "text": "No worker shall be required to work in conditions injurious to health."
            }
        ]
    }
    
    explanation = renderer.render_explanation(mock_recommendation, mock_verifier_result)
    print(explanation)
