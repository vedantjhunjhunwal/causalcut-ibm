import os
import sys

# Ensure regulatory_rag module is accessible
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import vector_store

class ComplianceVerifier:
    """
    Intakes a proposed intervention action, queries the FAISS index for relevant
    regulatory standards, and assesses if the action violates or complies with them.
    
    Section 4.9 of Design Doc: "Validates: is the proposed cut legal?"
    """
    def __init__(self):
        # We ensure the vector store is loaded by making a dummy query
        try:
            vector_store.query("warmup", top_k=1)
        except Exception:
            pass
            
    def verify_action(self, proposed_action: str, zone_context: str = "") -> dict:
        """
        Retrieves regulatory evidence for a proposed action and verifies compliance.
        
        Args:
            proposed_action: A natural language description of the intervention
                             (e.g., "Suspend hot work permit in Zone 1").
            zone_context: Additional context like "Ammonia level > 200ppm".
            
        Returns:
            A dictionary containing compliance status and regulatory evidence.
        """
        query_str = f"Action: {proposed_action}. Context: {zone_context}"
        
        # 1. Retrieve top regulatory chunks
        try:
            results = vector_store.query(
                query_text=query_str,
                top_k=3,
                timeout_seconds=5.0
            )
        except Exception as e:
            return {
                "verified": False,
                "compliance_status": "unverified",
                "reason": f"retrieval error: {str(e)}",
                "evidence": []
            }
            
        if not results.get("verified", False):
            return {
                "verified": False,
                "compliance_status": "unverified",
                "reason": results.get("reason", "timeout or unknown error"),
                "evidence": []
            }
            
        evidence = results.get("evidence", [])
        
        # 2. Rule-based Compliance Check (MVP Simplification)
        # In a full system, an LLM or complex NLP pipeline would assess this.
        # For MVP, we assume the action is 'compliant' unless the evidence contains
        # strong prohibitory keywords combined with the action context.
        # Here we just tag it as compliant and return the retrieved clauses as basis.
        
        prohibited_keywords = ["shall not", "prohibited", "forbidden", "must not"]
        status = "compliant"
        
        for chunk in evidence:
            text_lower = chunk.get("text", "").lower()
            if any(pk in text_lower for pk in prohibited_keywords):
                # Simple heuristic: if the rule strictly prohibits something,
                # we might need manual review. We'll flag it.
                status = "requires_manual_review"
                break
                
        return {
            "verified": True,
            "compliance_status": status,
            "action_evaluated": proposed_action,
            "evidence": evidence
        }

if __name__ == "__main__":
    verifier = ComplianceVerifier()
    
    # Test case 1: Normal compliant action
    action = "Suspend hot work permit PTW-007"
    context = "Toxic gas concentration rising above 200ppm in Coke Oven"
    result = verifier.verify_action(action, context)
    
    print(f"Action: {action}")
    print(f"Status: {result['compliance_status']}")
    print(f"Evidence chunks retrieved: {len(result['evidence'])}")
    for ev in result['evidence']:
        print(f" - [{ev.get('source_type')}] {ev.get('citation')}: {ev.get('similarity', 0):.4f}")
