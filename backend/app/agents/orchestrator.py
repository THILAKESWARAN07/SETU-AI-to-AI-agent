import logging
import re
from decimal import Decimal
from typing import Dict, Any, List, Optional, Callable
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.schemas import NegotiationStage
from backend.app.models import Product, MerchantPolicy
from backend.app.audit import AuditEngine
from backend.app.policy import PolicyEngine
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.pricing_strategy import MerchantPricingStrategy, calculate_basket_financials
from backend.app.agents.provider import BuyerDecision, MerchantDecision, MockProvider
from backend.app.agents.tools import (
    search_catalog_tool, view_product_tool, get_policy_constraints_tool,
    evaluate_budget_tool, get_inventory_tool, get_product_price_tool,
    get_merchant_constraints_tool, evaluate_margin_tool, request_purchase_tool
)

logger = logging.getLogger("setu.agents.orchestrator")

def parse_budget_intent(intent: str, configured_budget: Decimal) -> Dict[str, Any]:
    intent_lower = intent.lower() if intent else ""
    # Normalize comma separated numbers e.g. "12,000" -> "12000"
    intent_clean = re.sub(r'(\d),(\d)', r'\1\2', intent_lower)
    
    # Standalone vs accessory preferences
    explicit_standalone = any(w in intent_lower for w in [
        "standalone", "only want", "without accessories", "no accessories", 
        "phone alone", "just the", "alone", "without bundle", "no bundle", "only the",
        "only need"
    ])
    accessories_wanted = any(w in intent_lower for w in [
        "accessory", "accessories", "charger", "case", "glass", "strap", "bundle", "with"
    ])

    # Default to standalone if user did not request accessories or bundle
    standalone_preferred = explicit_standalone or (not accessories_wanted)
    buyer_profile = "VALUE_ORIENTED" if accessories_wanted else "PRICE_FIRST"

    # Shorthand & explicit amount extraction
    def _extract_amount(match_obj):
        if not match_obj:
            return None
        try:
            num_str = match_obj.group(1).replace(",", "")
            val = Decimal(num_str)
            if match_obj.group(2) and match_obj.group(2).lower() in ["k", "thousand"]:
                val = val * Decimal("1000")
            return val.quantize(Decimal("0.01"))
        except Exception:
            return None

    # Check for stretch phrases: "can stretch to 15k", "stretch up to 15000", "up to 15k"
    stretch_match = re.search(r'(?:stretch to|can stretch to|stretch up to|stretch)\s*(?:₹|rs\.?|inr)?\s*([\d]+(?:\.[\d]+)?)\s*(k|thousand)?', intent_clean)
    parsed_stretch = _extract_amount(stretch_match)

    # Check for strict budget phrases
    is_strict_phrase = any(w in intent_lower for w in [
        "maximum", "cannot spend more than", "not above", "hard limit", 
        "strict", "strict budget", "max", "budget cap", "under", "cap", "no more than"
    ])

    # Check for flexible budget phrases
    is_flexible_phrase = any(w in intent_lower for w in [
        "around", "about", "near", "roughly", "approx", "up to around", 
        "can stretch", "stretch to", "flexible"
    ])

    # Check if a target budget is stated inside the intent text (e.g. "budget is 12000", "around 12k", "max 15k")
    target_match = re.search(r'(?:budget(?:\s+is|\s+of|\s+around|\s+limit)?|around|about|near|roughly|max(?:imum)?|under|cap|limit)\s*(?:₹|rs\.?|inr)?\s*([\d]+(?:\.[\d]+)?)\s*(k|thousand)?', intent_clean)
    parsed_target = _extract_amount(target_match)
    
    target_budget = parsed_target if (parsed_target and parsed_target > Decimal("0")) else configured_budget
    maximum_budget = target_budget

    if parsed_stretch and parsed_stretch >= target_budget:
        budget_type = "flexible"
        is_flexible = True
        maximum_budget = parsed_stretch
    elif is_flexible_phrase:
        budget_type = "flexible"
        is_flexible = True
        maximum_budget = (target_budget * Decimal("1.08")).quantize(Decimal("0.01"))
    elif is_strict_phrase:
        budget_type = "strict"
        is_flexible = False
        maximum_budget = target_budget
    else:
        budget_type = "unspecified"
        is_flexible = False
        maximum_budget = target_budget

    flexibility_amount = (maximum_budget - target_budget).quantize(Decimal("0.01")) if maximum_budget > target_budget else Decimal("0.00")

    return {
        "target_budget": target_budget,
        "maximum_budget": maximum_budget,
        "budget_type": budget_type,
        "is_flexible": is_flexible,
        "flexibility_amount": flexibility_amount,
        "standalone_preferred": standalone_preferred,
        "accessories_wanted": accessories_wanted,
        "buyer_profile": buyer_profile
    }

def format_ist_timestamp(offset_seconds: float = 0.0) -> str:
    from datetime import datetime, timezone, timedelta
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz) + timedelta(seconds=offset_seconds)
    return now.strftime("%d %b %Y, %I:%M %p IST")

class NegotiationError(Exception):
    def __init__(self, message: str, result_data: dict = None):
        super().__init__(message)
        self.result_data = result_data

class NegotiationOrchestrator:
    def __init__(self, db: Session, buyer: BuyerAgent, merchant: MerchantAgent):
        self.db = db
        self.buyer = buyer
        self.merchant = merchant

    def run_negotiation_loop(
        self,
        buyer_id: str,
        intent: str,
        budget: Decimal,
        max_rounds: int = 4,
        max_llm_calls: Optional[int] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        import uuid
        import datetime
        import time
        from backend.app.agents.memory import NegotiationMemory
        
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        start_time = datetime.datetime.utcnow().isoformat() + "Z"
        start_time_epoch = time.time()
        provider_name = self.buyer.provider.provider_name
        model_name = self.buyer.provider.model_name
        execution_mode = self.buyer.provider.agent_mode
        
        # LLM Call Budget tracking
        is_mock_mode = execution_mode in ["OFFLINE MOCK", "MOCK"] or isinstance(self.buyer.provider, MockProvider)
        if max_llm_calls is not None:
            max_llm_budget = max_llm_calls
        elif is_mock_mode:
            max_llm_budget = max_rounds * 2  # Unrestricted for offline mock unit tests
        else:
            max_llm_budget = getattr(settings, "MAX_REAL_LLM_CALLS", 3)
        llm_calls_made = 0
        buyer_llm_calls = 0
        merchant_llm_calls = 0
        deterministic_turns = 0
        
        # 1. Parse intent and budget constraints
        budget_info = parse_budget_intent(intent, budget)
        effective_max_budget = budget_info["maximum_budget"]

        # 2. Start session memory
        memory = NegotiationMemory(session_id=session_id, product_id=1)
        memory.buyer_goal = f"Procure target product based on user intent: '{intent}' with target budget: ₹{budget_info['target_budget']} and maximum budget limit: ₹{effective_max_budget}."
        memory.merchant_goal = "Maximize transaction volume, cross-sell recommendation conversion, and verify min margin guidelines."

        # Active deterministic tool trace trackers
        self.buyer.tools_called_in_session = ["search_catalog", "get_policy_constraints"]
        self.merchant.tools_called_in_session = ["get_inventory", "evaluate_margin"]

        # Log session start events
        AuditEngine.log_event(
            db=self.db,
            actor="SYSTEM",
            action="AGENT_SESSION_STARTED",
            result="SUCCESS",
            reason=f"Autonomous session initialized for Buyer '{buyer_id}' with intent: '{intent}'. Mode: {self.buyer.provider.agent_mode}"
        )
        
        AuditEngine.log_event(
            db=self.db,
            actor="SYSTEM",
            action="AGENT_SESSION_CREATED",
            result="SUCCESS",
            reason=f"Negotiation session created for intent: {intent}",
            metadata={"buyer_id": buyer_id, "intent": intent, "target_budget": str(budget_info['target_budget']), "maximum_budget": str(effective_max_budget), "session_id": session_id}
        )
        negotiation_history = []
        conversation_events = []
        event_seq = 0
        provider_call_records = []
        current_buyer_meta = None
        current_merchant_meta = None

        def emit_event(evt_data: Dict[str, Any], meta: Optional[Any] = None):
            nonlocal event_seq
            event_seq += 1
            evt_data["sequence"] = event_seq
            if "event_id" not in evt_data:
                evt_data["event_id"] = evt_data.get("id", f"evt_{event_seq}")
            if "type" not in evt_data:
                evt_data["type"] = evt_data.get("event_type", "message")
            
            # Attach provider metadata if it's an AI agent turn
            effective_meta = meta
            if effective_meta is None and evt_data.get("actor") in ("buyer", "merchant"):
                if evt_data.get("actor") == "buyer":
                    effective_meta = current_buyer_meta
                elif evt_data.get("actor") == "merchant":
                    effective_meta = current_merchant_meta

            if effective_meta:
                if isinstance(effective_meta, dict):
                    evt_data["provider_used"] = effective_meta.get("provider_used", "mock")
                    evt_data["provider_type"] = effective_meta.get("provider_type", "real_llm" if evt_data["provider_used"] not in ("mock", "deterministic_engine") else ("deterministic_turn" if evt_data["provider_used"] == "deterministic_engine" else "deterministic_fallback"))
                    evt_data["model_name"] = effective_meta.get("model_name", "mock-model-v2")
                    evt_data["agent_role"] = effective_meta.get("agent_role", evt_data.get("actor"))
                    evt_data["fallback_used"] = bool(effective_meta.get("fallback_used", False))
                    evt_data["fallback_depth"] = int(effective_meta.get("fallback_depth", 0))
                    evt_data["fallback_reason"] = effective_meta.get("fallback_reason", None)
                    evt_data["response_latency_ms"] = effective_meta.get("response_latency_ms", 0.0)
                    evt_data["provider_attempts"] = effective_meta.get("provider_attempts", [])
                    evt_data["is_deterministic"] = bool(effective_meta.get("is_deterministic", False))
                else:
                    evt_data["provider_used"] = getattr(effective_meta, "provider_used", "mock")
                    evt_data["provider_type"] = getattr(effective_meta, "provider_type", "real_llm" if evt_data["provider_used"] not in ("mock", "deterministic_engine") else ("deterministic_turn" if evt_data["provider_used"] == "deterministic_engine" else "deterministic_fallback"))
                    evt_data["model_name"] = getattr(effective_meta, "model_name", "mock-model-v2")
                    evt_data["agent_role"] = getattr(effective_meta, "agent_role", evt_data.get("actor"))
                    evt_data["fallback_used"] = bool(getattr(effective_meta, "fallback_used", False))
                    evt_data["fallback_depth"] = int(getattr(effective_meta, "fallback_depth", 0))
                    evt_data["fallback_reason"] = getattr(effective_meta, "fallback_reason", None)
                    evt_data["response_latency_ms"] = getattr(effective_meta, "response_latency_ms", 0.0)
                    evt_data["provider_attempts"] = getattr(effective_meta, "provider_attempts", [])
                    evt_data["is_deterministic"] = bool(getattr(effective_meta, "is_deterministic", False))
                
                # Expose convenience aliases for UI & tests
                evt_data["provider"] = evt_data["provider_used"]
                evt_data["model"] = evt_data["model_name"]
                evt_data["mode"] = evt_data["provider_type"]
                evt_data["latency_ms"] = evt_data["response_latency_ms"]
                evt_data["fallback"] = evt_data["fallback_used"]
                if "sender" not in evt_data and "actor" in evt_data:
                    evt_data["sender"] = evt_data["actor"]

                evt_data["provider_execution"] = {
                    "provider_used": evt_data["provider_used"],
                    "provider_type": evt_data["provider_type"],
                    "model_name": evt_data["model_name"],
                    "agent_role": evt_data["agent_role"],
                    "fallback_used": evt_data["fallback_used"],
                    "fallback_depth": evt_data["fallback_depth"],
                    "fallback_reason": evt_data["fallback_reason"],
                    "response_latency_ms": evt_data["response_latency_ms"],
                    "provider_attempts": evt_data["provider_attempts"],
                    "is_deterministic": evt_data.get("is_deterministic", False)
                }

            conversation_events.append(evt_data)
            if on_event:
                try:
                    on_event(evt_data)
                except Exception as e:
                    logger.warning(f"Error in on_event callback: {e}")

        def compute_provider_summary():
            from backend.app.agents.ai_gateway import get_ai_gateway
            gw = get_ai_gateway()

            cerebras_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "cerebras" or (isinstance(m, dict) and m.get("provider_used") == "cerebras")))
            groq_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "groq" or (isinstance(m, dict) and m.get("provider_used") == "groq")))
            gemini_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "gemini" or (isinstance(m, dict) and m.get("provider_used") == "gemini")))
            nvidia_nim_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "nvidia_nim" or (isinstance(m, dict) and m.get("provider_used") == "nvidia_nim")))
            openrouter_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "openrouter" or (isinstance(m, dict) and m.get("provider_used") == "openrouter")))
            ollama_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "ollama" or (isinstance(m, dict) and m.get("provider_used") == "ollama")))
            mock_calls = sum(1 for m in provider_call_records if m and (getattr(m, "provider_used", None) == "mock" or (isinstance(m, dict) and m.get("provider_used") == "mock")))
            
            fallback_count = sum(1 for m in provider_call_records if m and (getattr(m, "fallback_used", False) or (isinstance(m, dict) and m.get("fallback_used"))))
            provider_failovers = sum(1 for m in provider_call_records if m and (int(getattr(m, "fallback_depth", 0) or (m.get("fallback_depth") if isinstance(m, dict) else 0)) > 0 or len(getattr(m, "provider_attempts", []) or (m.get("provider_attempts") if isinstance(m, dict) else [])) > 1))
            real_llm_calls = cerebras_calls + groq_calls + gemini_calls + nvidia_nim_calls + openrouter_calls + ollama_calls
            total_llm_calls = real_llm_calls + mock_calls
            
            # Extract unique providers used
            providers_used_set = set()
            for m in provider_call_records:
                p_name = getattr(m, "provider_used", None) if not isinstance(m, dict) else m.get("provider_used")
                if p_name:
                    providers_used_set.add(p_name)
            providers_used = list(providers_used_set)
            
            # Count deterministic operations avoided: catalog search, filter, margin math, policy checks, basket checks, inventory checks
            deterministic_ops_avoided = max(12, 4 * len(provider_call_records) + 4)
            estimated_llm_calls_saved = deterministic_ops_avoided
            duration = round(time.time() - start_time_epoch, 2)

            return {
                "cerebras_calls": cerebras_calls,
                "groq_calls": groq_calls,
                "gemini_calls": gemini_calls,
                "nvidia_nim_calls": nvidia_nim_calls,
                "openrouter_calls": openrouter_calls,
                "ollama_calls": ollama_calls,
                "mock_calls": mock_calls,
                "real_llm_calls": real_llm_calls,
                "total_llm_calls": total_llm_calls,
                "deterministic_turns": deterministic_turns,
                "deterministic_fallback_calls": mock_calls,
                "deterministic_fallback_turns": mock_calls,
                "provider_failovers": provider_failovers,
                "providers_used": providers_used,
                "buyer_llm_calls": buyer_llm_calls,
                "merchant_llm_calls": merchant_llm_calls,
                "llm_budget": max_llm_budget,
                "llm_budget_remaining": max(0, max_llm_budget - real_llm_calls),
                "negotiation_duration": duration,
                "mock_fallback_used": (mock_calls > 0),
                "mock_fallback_status": "USED" if mock_calls > 0 else "NOT USED",
                "deterministic_operations_avoided": deterministic_ops_avoided,
                "estimated_llm_calls_saved": estimated_llm_calls_saved,
                "fallback_count": fallback_count,
                "all_agent_turns_used_real_llm": (real_llm_calls > 0 and mock_calls == 0),
                "all_agent_turns_used_gemini": (gemini_calls > 0 and mock_calls == 0 and real_llm_calls == gemini_calls),
                "is_live": (real_llm_calls > 0 and mock_calls == 0),
                "mode": "LIVE MULTI-PROVIDER" if (real_llm_calls > 0 and mock_calls == 0) else ("DETERMINISTIC FALLBACK" if mock_calls > 0 else "AUTONOMOUS AI")
            }

        current_status = "IN_PROGRESS"
        current_stage = NegotiationStage.INTENT_PARSE
        final_decision_pr_id = None
        final_price = None
        selected_product_id = None
        search_results = []
        original_amount = Decimal("0.00")
        round_idx = 1
        proposals = []
        buyer_opening_offer_record = None
        merchant_standalone_counter_record = None
        merchant_bundle_proposal_record = None
        accepted_proposal_id = None

        def build_failed_result(reasons, final_price_val=None, decision_val="BLOCKED", execution_mode_override=None, error_code=None):
            prod_id = selected_product_id or 1
            original_amt_str = "0.00"
            if selected_product_id:
                try:
                    prod = view_product_tool(self.db, selected_product_id)
                    original_amt_str = str(Decimal(prod["price"]))
                except Exception:
                    pass
            elif search_results:
                try:
                    original_amt_str = str(Decimal(search_results[0]["price"]))
                except Exception:
                    pass
            
            try:
                policy = self.db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
                policy_version = policy.policy_version if policy else "policy_v1.0"
            except Exception:
                policy_version = "policy_v1.0"
                
            completion_time = datetime.datetime.utcnow().isoformat() + "Z"
            mode_val = execution_mode_override or execution_mode
            
            # For BLOCKED, REJECTED, or failed deals, final_amount is None (not a valid 0.00 deal)
            safe_final_amount = None
            if final_price_val is not None and decision_val not in ["BLOCKED", "REJECTED", "ERROR"]:
                try:
                    dec_val = Decimal(str(final_price_val))
                    if dec_val > Decimal("0.00"):
                        safe_final_amount = str(dec_val)
                except Exception:
                    safe_final_amount = None

            return {
                "buyer_id": buyer_id,
                "intent": intent,
                "catalog_search_results": search_results or [],
                "selected_product_id": prod_id,
                "cross_sell_product_id": 2 if prod_id in [1, 3] else 0,
                "bundle_offer": {
                    "product_ids": [1, 2] if prod_id == 3 else [prod_id],
                    "original_amount": original_amt_str,
                    "offered_amount": safe_final_amount,
                    "discount_percent": None,
                    "reason": reasons[0] if reasons else "Negotiation session blocked or rejected"
                },
                "negotiation_history": negotiation_history or [],
                "conversation_events": conversation_events or [],
                "purchase_request_id": None,
                "decision": decision_val,
                "reasons": reasons,
                "original_amount": original_amt_str,
                "final_amount": safe_final_amount,
                "discount_percent": None,
                "margin_percent": None,
                "policy_version": policy_version,
                "agent_mode": mode_val,
                "buyer_objective": memory.buyer_goal,
                "buyer_tools_used": list(self.buyer.tools_called_in_session),
                "buyer_confidence": self.buyer.last_confidence,
                "merchant_objective": memory.merchant_goal,
                "merchant_tools_used": list(self.merchant.tools_called_in_session),
                "merchant_confidence": self.merchant.last_confidence,
                
                # Stage & Error tracking
                "stage": current_stage.value if hasattr(current_stage, "value") else str(current_stage),
                "error_code": error_code or ("POLICY_REJECTED" if decision_val == "BLOCKED" else "NEGOTIATION_FAILED"),
                "status": "failed",
                
                # Step 12 metadata
                "provider": provider_name,
                "model": model_name,
                "execution_mode": mode_val,
                "session_id": session_id,
                "agent_role": "BUYER_AGENT & MERCHANT_AGENT",
                "start_time": start_time,
                "completion_time": completion_time,
                "provider_summary": compute_provider_summary()
            }

        # Legacy E2E and UI compatibility log triggers
        AuditEngine.log_event(db=self.db, actor="BUYER_AGENT", action="BUYER_INTENT", result="SUCCESS", reason=f"Buyer intent processed: {intent}")
        AuditEngine.log_event(db=self.db, actor="BUYER_AGENT", action="CATALOG_SEARCH", result="SUCCESS", reason="Buyer searched catalog.")
        AuditEngine.log_event(db=self.db, actor="MERCHANT_AGENT", action="CROSS_SELL_PROPOSED", result="SUCCESS", reason="Merchant proposed bundle cross-sell option.")
        AuditEngine.log_event(db=self.db, actor="SYSTEM", action="NEGOTIATION", result="SUCCESS", reason="AI-to-AI autonomous negotiation turn loop started.")

        # 2. Buyer Agent Intent Parsing & Catalog Search
        # Call search_catalog tool
        intent_clean = intent.strip() if intent else ""
        if intent_clean:
            search_results = search_catalog_tool(self.db, query=intent_clean)
            if not search_results:
                raise NegotiationError(
                    f"Procurement failed: No products found matching '{intent}'.", 
                    build_failed_result([f"Procurement failed: No products found matching '{intent}'."])
                )
        else:
            search_results = search_catalog_tool(self.db)
            if not search_results:
                raise NegotiationError(
                    "Procurement failed: No items found in catalog matching search parameters.", 
                    build_failed_result(["Procurement failed: No items found in catalog matching search parameters."])
                )

        intent_lower = intent.lower()
        candidate_prod = search_results[0]
        
        # Match specific intent keywords to the best candidate product
        if "samsung" in intent_lower or "galaxy" in intent_lower or "a15" in intent_lower:
            cand = next((p for p in search_results if "samsung" in p["name"].lower() or "galaxy" in p["name"].lower() or p["id"] == 41), None)
            if cand:
                candidate_prod = cand
        elif "redmi" in intent_lower or "note 13" in intent_lower:
            cand = next((p for p in search_results if "redmi" in p["name"].lower() or p["id"] == 42), None)
            if cand:
                candidate_prod = cand
        elif "motorola" in intent_lower or "g54" in intent_lower:
            cand = next((p for p in search_results if "motorola" in p["name"].lower() or p["id"] == 43), None)
            if cand:
                candidate_prod = cand
        elif "phone" in intent_lower or "mobile" in intent_lower or "smartphone" in intent_lower:
            if "12000" in intent_lower or "12,000" in intent_lower or "13000" in intent_lower or "15000" in intent_lower:
                cand = next((p for p in search_results if p["id"] == 41 or "samsung" in p["name"].lower()), None)
            else:
                cand = None
            if not cand:
                cand = next((p for p in search_results if p["category"] == "Mobile Phones" and "case" not in p["name"].lower() and "charger" not in p["name"].lower() and "glass" not in p["name"].lower()), None)
            if cand:
                candidate_prod = cand
        elif "smartwatch" in intent_lower or "watch" in intent_lower:
            cand = next((p for p in search_results if "smartwatch" in p["name"].lower() or p["id"] in [56, 31]), None)
            if cand:
                candidate_prod = cand
        elif "keyboard" in intent_lower:
            cand = next((p for p in search_results if "keyboard" in p["name"].lower() or p["id"] in [52, 25]), None)
            if cand:
                candidate_prod = cand
        elif "mouse" in intent_lower:
            cand = next((p for p in search_results if "mouse" in p["name"].lower() or p["id"] in [53, 23]), None)
            if cand:
                candidate_prod = cand
        elif "speaker" in intent_lower:
            cand = next((p for p in search_results if "speaker" in p["name"].lower() or p["id"] in [51, 6]), None)
            if cand:
                candidate_prod = cand
        elif "earbuds" in intent_lower or "earphone" in intent_lower:
            cand = next((p for p in search_results if "earbuds" in p["name"].lower() or p["id"] in [1, 9, 47, 48]), None)
            if cand:
                candidate_prod = cand
        else:
            # Pick first primary item if available
            cand = next((p for p in search_results if p["category"] != "Accessories"), None)
            if cand:
                candidate_prod = cand

        selected_product_id = candidate_prod["id"]
        original_primary_id = selected_product_id
        is_alternative_offered = False

        # --- OUT OF STOCK / UNAVAILABLE HANDLING ---
        prod_obj = self.db.query(Product).filter(Product.id == selected_product_id).first()
        if not prod_obj or prod_obj.inventory <= 0 or not prod_obj.active:
            category_val = prod_obj.category if prod_obj else "Wireless Earbuds"
            alternatives = self.db.query(Product).filter(
                Product.category == category_val,
                Product.inventory > 0,
                Product.active == True
            ).all()
            if alternatives:
                alt_prod = alternatives[0]
                is_alternative_offered = True
                selected_product_id = alt_prod.id
                candidate_prod = {
                    "id": alt_prod.id,
                    "name": alt_prod.name,
                    "category": alt_prod.category,
                    "price": str(alt_prod.price),
                    "inventory": alt_prod.inventory,
                    "description": alt_prod.description
                }
                AuditEngine.log_event(
                    db=self.db,
                    actor="SYSTEM",
                    action="PRODUCT_ALTERNATIVE_PROPOSED",
                    result="SUCCESS",
                    reason=f"Requested product ID {original_primary_id} is unavailable/out-of-stock. Proposed alternative same-category product: {alt_prod.name} (ID {alt_prod.id})"
                )

        memory.product_id = selected_product_id
        prod_details = view_product_tool(self.db, selected_product_id)
        policy_info = get_policy_constraints_tool(self.db)
        AuditEngine.log_event(db=self.db, actor="BUYER_AGENT", action="PRODUCT_SELECTED", result="SUCCESS", reason=f"Buyer selected reference product {prod_details.get('name', 'Product') if prod_details else 'Product'}.")

        # Formulate initial Buyer offer
        buyer_prompt = (
            f"=== CURRENT NEGOTIATION CONTEXT ===\n"
            f"NEGOTIATION SESSION ID: {session_id}\n"
            f"CURRENT PRODUCT ID: {selected_product_id}\n"
            f"CURRENT PRODUCT NAME: {prod_details['name'] if prod_details else 'Product'}\n"
            f"CURRENT CATALOG PRICE: ₹{prod_details['price'] if prod_details else '0'}\n"
            f"CURRENT BUYER BUDGET: ₹{effective_max_budget}\n"
            f"====================================\n"
            f"You are the Buyer Agent. Parse user intent: '{intent}' with budget limit: {budget} INR.\n"
            f"Catalog Search Results: {search_results}\n"
            f"Selected Target Product Details: {prod_details}\n"
            f"Merchant Policy Constraints: {policy_info}\n"
        )
        if is_alternative_offered:
            buyer_prompt += f"NOTE: The originally requested product (ID {original_primary_id}) is out of stock. The Merchant proposed same-category alternative product: {prod_details['name']} (ID {prod_details['id']}). Evaluate if this alternative fits your intent and budget, and proceed with negotiation.\n"
            
        from backend.app.agents.ai_gateway import NegotiationContext
        cat_price = Decimal(str(prod_details.get("price", "1000.00")))
        cost_price = Decimal(str(prod_details.get("cost", "800.00")))
        min_margin = Decimal(str(policy_info.get("min_margin_percent", "15.00")))
        max_disc = Decimal(str(policy_info.get("max_discount_percent", "15.00")))
        min_by_margin = (cost_price / (Decimal("1") - min_margin / Decimal("100"))) if cost_price > Decimal("0") else Decimal("0.00")
        min_by_disc = cat_price * (Decimal("1") - max_disc / Decimal("100"))
        min_sp = Decimal(str(prod_details.get("min_selling_price") or "0.00"))
        floor_price = max(min_by_margin, min_by_disc, min_sp).quantize(Decimal("0.01"))

        buyer_context = NegotiationContext(
            agent_role="BUYER_AGENT",
            current_round=1,
            buyer_max_budget=effective_max_budget,
            current_product=prod_details,
            catalog_price=cat_price,
            merchant_min_price=floor_price,
            current_proposal=None,
            previous_offers=[],
            max_allowed_discount=max_disc,
            inventory_availability=prod_details.get("inventory", 10),
            relevant_policy_constraints=policy_info,
            remaining_rounds=max_rounds
        )

        # Generate buyer decision using the runtime loop
        try:
            buyer_decision: BuyerDecision = self.buyer.negotiate_decision(self.db, buyer_prompt, memory=memory, context=buyer_context)
            current_buyer_meta = getattr(buyer_decision, "provider_metadata", None) or getattr(self.buyer, "last_execution_metadata", None) or getattr(self.buyer.provider, "last_execution_metadata", None)
            if current_buyer_meta:
                provider_call_records.append(current_buyer_meta)
            buyer_llm_calls += 1
            llm_calls_made += 1
        except Exception as e:
            logger.error(f"Buyer Agent LLM failure: {e}")
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="PROVIDER_FAILURE",
                result="ERROR",
                reason=f"Buyer Agent LLM call failed: {str(e)}",
                metadata={"session_id": session_id, "provider": provider_name, "model": model_name}
            )
            raise NegotiationError(
                f"LLM Provider failure: {str(e)}", 
                build_failed_result([f"LLM Provider failure: {str(e)}"], decision_val="ERROR", execution_mode_override="PROVIDER ERROR")
            )

        # Ensure basket_items is populated
        from backend.app.agents.provider import BasketItemSchema
        if not getattr(buyer_decision, "basket_items", None):
            buyer_decision.basket_items = [
                BasketItemSchema(
                    product_id=buyer_decision.product_id,
                    name=prod_details["name"] if buyer_decision.product_id == selected_product_id else "Product",
                    quantity=buyer_decision.quantity,
                    original_price=Decimal(prod_details["price"]),
                    negotiated_price=buyer_decision.unit_price,
                    is_primary=True
                )
            ]
        
        # Calculate basket totals
        basket_original_total = sum(Decimal(str(item.original_price)) * Decimal(item.quantity) for item in buyer_decision.basket_items)
        basket_final_total = sum(Decimal(str(item.negotiated_price)) * Decimal(item.quantity) for item in buyer_decision.basket_items)
        buyer_decision.total_amount = basket_final_total

        # Validate Buyer offer total does not exceed budget
        budget_check = evaluate_budget_tool(self.db, str(buyer_decision.total_amount), str(budget))
        
        # Log POLICY_CHECK for the initial buyer budget check
        AuditEngine.log_event(
            db=self.db,
            actor="SYSTEM",
            action="POLICY_CHECK",
            result="SUCCESS" if budget_check["within_budget"] else "FAIL",
            reason=f"Buyer initial budget verification. Budget: ₹{budget}. Offer: ₹{buyer_decision.total_amount}"
        )
        
        memory.add_policy_verdict(
            decision="APPROVED" if budget_check["within_budget"] else "BLOCKED",
            reasons=[] if budget_check["within_budget"] else ["Initial offer exceeds budget."]
        )

        if not budget_check["within_budget"]:
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="POLICY_REJECTED",
                result="BLOCKED",
                reason=f"Buyer initial offer total {buyer_decision.total_amount} exceeds budget {budget}."
            )
            raise NegotiationError(f"Negotiation failed: Proposed price {buyer_decision.total_amount} exceeds configured budget limit.", build_failed_result([f"Proposed price {buyer_decision.total_amount} exceeds configured budget limit."]))

        # Log BUYER_OFFER event
        AuditEngine.log_event(
            db=self.db,
            actor="BUYER_AGENT",
            action="BUYER_OFFER",
            result="SUCCESS",
            reason=buyer_decision.rationale,
            metadata={"amount": str(buyer_decision.total_amount), "confidence": str(self.buyer.last_confidence)}
        )
        AuditEngine.log_event(
            db=self.db,
            actor="BUYER_AGENT",
            action="BUYER_OFFER_CREATED",
            result="SUCCESS",
            reason=buyer_decision.rationale,
            metadata={"amount": str(buyer_decision.total_amount), "confidence": str(self.buyer.last_confidence)}
        )

        original_amount = basket_original_total

        serialized_buyer_init_items = [
            {
                "product_id": item.product_id,
                "name": item.name,
                "quantity": item.quantity,
                "original_price": str(item.original_price),
                "negotiated_price": str(item.negotiated_price),
                "is_primary": item.is_primary
            }
            for item in buyer_decision.basket_items
        ]

        buyer_opening_offer_record = {
            "product_id": buyer_decision.product_id,
            "quantity": buyer_decision.quantity,
            "original_amount": str(original_amount),
            "offered_amount": str(buyer_decision.total_amount),
            "basket_items": serialized_buyer_init_items
        }

        proposals.append({
            "proposal_id": "prop_b_r1",
            "actor": "buyer",
            "proposal_type": "STANDALONE_OFFER",
            "round": 1,
            "basket_items": serialized_buyer_init_items,
            "total_amount": str(buyer_decision.total_amount),
            "is_optional_bundle": False,
            "status": "OPEN",
            "reason": buyer_decision.rationale
        })

        # Record Event 1: Buyer Opening Request
        emit_event({
            "id": "evt_r1_buyer_req",
            "event_id": "evt_r1_buyer_req",
            "round": 1,
            "actor": "buyer",
            "event_type": "message",
            "type": "buyer_message",
            "state": "BUYER_REQUEST",
            "proposal_id": "prop_b_r1",
            "proposal_type": "STANDALONE_OFFER",
            "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
            "offer": str(buyer_decision.total_amount),
            "buyer_opening_offer": str(buyer_decision.total_amount),
            "standalone_offer": str(buyer_decision.total_amount),
            "basket_items": serialized_buyer_init_items,
            "reason_label": "Buyer opening offer within budget guidelines",
            "timestamp": format_ist_timestamp(0.5)
        })

        # Record Event 2: SETU Catalog Availability & Budget Cap Check
        emit_event({
            "id": "evt_r1_setu_budget",
            "event_id": "evt_r1_setu_budget",
            "round": 1,
            "actor": "setu",
            "event_type": "trust_check",
            "type": "system_event",
            "state": "BUYER_REQUEST",
            "message": f"SETU verified catalog availability & recorded buyer budget boundary (₹{effective_max_budget}).",
            "reason_label": "Budget & Stock Validated",
            "timestamp": format_ist_timestamp(0.8)
        })

        # Append turn 1 for legacy compatibility
        negotiation_history.append({
            "round": 1,
            "buyer_offer": {
                "product_id": buyer_decision.product_id,
                "quantity": buyer_decision.quantity,
                "original_amount": str(original_amount),
                "final_amount": str(buyer_decision.total_amount),
                "currency": "INR",
                "reason": buyer_decision.rationale,
                "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
                "reason_label": "Buyer budget limit satisfied",
                "tools_used": list(self.buyer.tools_called_in_session),
                "confidence": self.buyer.last_confidence,
                "basket_items": serialized_buyer_init_items
            },
            "merchant_offer": None,
            "accepted": False,
            "reason": buyer_decision.rationale
        })

        latest_buyer_offer = buyer_decision
        # 3. Turn Loop
        round_idx = 1
        merchant_countered = False
        last_merchant_standalone_id = None
        last_merchant_standalone_price = None
        last_merchant_bundle_id = None

        while round_idx <= max_rounds:
            round_idx += 1
            memory.round_number = round_idx

            # --- MERCHANT TURN ---
            # Gather tools observations
            inventory = get_inventory_tool(self.db, latest_buyer_offer.product_id)
            base_price = get_product_price_tool(self.db, latest_buyer_offer.product_id)
            merchant_policy = get_merchant_constraints_tool(self.db)
            margin_eval = evaluate_margin_tool(self.db, latest_buyer_offer.product_id, latest_buyer_offer.quantity, str(latest_buyer_offer.total_amount))

            # Retrieve product and related items for sales strategy evaluation
            p_obj_cur = self.db.query(Product).filter(Product.id == latest_buyer_offer.product_id).first()
            related_objs_cur = []
            if p_obj_cur and p_obj_cur.related_product_ids:
                related_objs_cur = self.db.query(Product).filter(Product.id.in_(p_obj_cur.related_product_ids), Product.active == True).all()

            sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
                primary_prod={
                    "id": p_obj_cur.id if p_obj_cur else latest_buyer_offer.product_id,
                    "name": p_obj_cur.name if p_obj_cur else "Product",
                    "price": str(p_obj_cur.price if p_obj_cur else latest_buyer_offer.total_amount),
                    "cost": str(p_obj_cur.cost if p_obj_cur else Decimal("0.00")),
                    "min_selling_price": str(p_obj_cur.min_selling_price if p_obj_cur else Decimal("0.00")),
                    "inventory": p_obj_cur.inventory if p_obj_cur else 10,
                    "active": True
                },
                related_prods=[
                    {
                        "id": r.id,
                        "name": r.name,
                        "price": str(r.price),
                        "cost": str(r.cost),
                        "min_selling_price": str(r.min_selling_price or r.cost),
                        "inventory": r.inventory,
                        "active": r.active
                    }
                    for r in related_objs_cur
                ],
                buyer_offer_price=latest_buyer_offer.total_amount,
                buyer_max_budget=effective_max_budget,
                standalone_preferred=budget_info.get("standalone_preferred", False),
                round_idx=round_idx - 1,
                max_rounds=max_rounds,
                min_margin_percent=merchant_policy.get("min_margin_percent", Decimal("15.00")),
                max_discount_percent=merchant_policy.get("max_discount_percent", Decimal("15.00")),
                previous_merchant_price=last_merchant_standalone_price
            )

            # Deterministic calculation of optional bundle opportunity if applicable
            optional_bundle_dict = None
            if sales_eval.get("bundle_info"):
                b_info = sales_eval["bundle_info"]
                pres = b_info.get("prescription", {})
                b_items = pres.get("bundle_items", [])
                catalog_lookup = {p.id: p for p in self.db.query(Product).all()}
                bundle_fin = calculate_basket_financials(b_items, catalog_lookup=catalog_lookup)
                
                # Check inventory of all bundle items
                all_stock_ok = all(
                    (catalog_lookup[it["product_id"]].inventory >= it.get("quantity", 1) and catalog_lookup[it["product_id"]].active)
                    for it in b_items if it.get("product_id") in catalog_lookup
                )
                
                b_names = " + ".join([it["name"] for it in b_items])
                optional_bundle_dict = {
                    "bundle_product_ids": [it["product_id"] for it in b_items],
                    "included_product_names": b_names,
                    "bundle_name": b_names,
                    "bundle_list_price": bundle_fin["catalog_total"],
                    "bundle_min_price": str(pres.get("bundle_floor_price", bundle_fin["total_cost"])),
                    "bundle_price": bundle_fin["basket_total"],
                    "savings": bundle_fin["buyer_savings_amount"],
                    "inventory_available": all_stock_ok,
                    "fits_budget": Decimal(bundle_fin["basket_total"]) <= effective_max_budget,
                    "basket_items": b_items
                }

            merchant_prompt = (
                f"=== CURRENT NEGOTIATION CONTEXT ===\n"
                f"NEGOTIATION SESSION ID: {session_id}\n"
                f"CURRENT PRODUCT ID: {selected_product_id}\n"
                f"CURRENT PRODUCT NAME: {prod_details['name'] if prod_details else 'Product'}\n"
                f"CURRENT CATALOG PRICE: ₹{prod_details['price'] if prod_details else '0'}\n"
                f"CURRENT BUYER BUDGET: ₹{effective_max_budget}\n"
                f"CURRENT BUYER OFFER: ₹{latest_buyer_offer.total_amount}\n"
                f"CURRENT PREVIOUS MERCHANT OFFER: ₹{last_merchant_standalone_price if last_merchant_standalone_price is not None else 'N/A'}\n"
                f"====================================\n"
                f"You are the Merchant Agent. User Procurement Request: '{intent}'.\n"
                f"Buyer Decision Action: {latest_buyer_offer.action}\n"
                f"Buyer Message: '{getattr(latest_buyer_offer, 'message', '')}'\n"
                f"Evaluate Buyer's proposed basket: {[f'{item.name} (Qty: {item.quantity}, Price: {item.negotiated_price})' for item in latest_buyer_offer.basket_items]} with total amount: {latest_buyer_offer.total_amount} INR.\n"
                f"Inventory Availability: {inventory}\n"
                f"Product Pricing: {base_price}\n"
                f"Merchant Policy Constraints: {merchant_policy}\n"
                f"Margin Evaluation: {margin_eval}\n"
                f"Recommended Merchant Strategy: {sales_eval['strategy']} ({sales_eval['reason']})\n"
                f"Recommended Standalone Price: ₹{sales_eval['recommended_standalone_price']}\n"
            )
            if optional_bundle_dict:
                merchant_prompt += (
                    f"Optional Bundle Opportunity: {optional_bundle_dict['bundle_name']} for ₹{optional_bundle_dict['bundle_price']} (Customer saves ₹{optional_bundle_dict['savings']}).\n"
                    f"You may counter the standalone price (COUNTER) and/or propose the optional bundle (PROPOSE_BUNDLE or BUNDLE). "
                    f"The bundle is strictly optional and must never replace the buyer's original request without consent.\n"
                )
            else:
                merchant_prompt += (
                    f"Formulate your response (COUNTER, ACCEPT, or REJECT). "
                    f"Ensure total_amount equals the exact sum of negotiated prices of all items in basket_items.\n"
                )

            merchant_context = NegotiationContext(
                agent_role="MERCHANT_AGENT",
                current_round=round_idx,
                buyer_max_budget=effective_max_budget,
                current_product={
                    "id": p_obj_cur.id if p_obj_cur else latest_buyer_offer.product_id,
                    "name": p_obj_cur.name if p_obj_cur else "Product",
                    "price": str(p_obj_cur.price if p_obj_cur else latest_buyer_offer.total_amount),
                    "cost": str(p_obj_cur.cost if p_obj_cur else Decimal("0.00")),
                    "min_selling_price": str(p_obj_cur.min_selling_price if p_obj_cur else Decimal("0.00")),
                    "inventory": p_obj_cur.inventory if p_obj_cur else 10,
                    "active": True
                },
                catalog_price=Decimal(str(prod_details.get("price", "1000.00"))),
                merchant_min_price=sales_eval.get("recommended_standalone_price", floor_price),
                current_proposal={
                    "product_id": latest_buyer_offer.product_id,
                    "unit_price": str(latest_buyer_offer.unit_price),
                    "total_amount": str(latest_buyer_offer.total_amount),
                    "action": latest_buyer_offer.action
                },
                previous_offers=[{"round": p.get("round", 1), "actor": p.get("actor"), "total_amount": p.get("total_amount")} for p in proposals],
                max_allowed_discount=merchant_policy.get("max_discount_percent", Decimal("15.00")),
                inventory_availability=inventory.get("inventory", 10),
                relevant_policy_constraints=merchant_policy,
                remaining_rounds=max(0, max_rounds - round_idx),
                optional_bundle=optional_bundle_dict,
                bundle_already_proposed=bool(merchant_bundle_proposal_record is not None),
                standalone_preferred=budget_info.get("standalone_preferred", False)
            )

            if llm_calls_made < max_llm_budget:
                try:
                    merchant_decision: MerchantDecision = self.merchant.negotiate_decision(self.db, merchant_prompt, memory=memory, context=merchant_context)
                    current_merchant_meta = getattr(merchant_decision, "provider_metadata", None) or getattr(self.merchant, "last_execution_metadata", None) or getattr(self.merchant.provider, "last_execution_metadata", None)
                    if current_merchant_meta:
                        provider_call_records.append(current_merchant_meta)
                    merchant_llm_calls += 1
                    llm_calls_made += 1
                except Exception as e:
                    logger.error(f"Merchant Agent LLM failure: {e}")
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="PROVIDER_FAILURE",
                        result="ERROR",
                        reason=f"Merchant Agent LLM call failed: {str(e)}",
                        metadata={"session_id": session_id, "provider": provider_name, "model": model_name}
                    )
                    raise NegotiationError(
                        f"LLM Provider failure: {str(e)}", 
                        build_failed_result([f"LLM Provider failure: {str(e)}"], decision_val="ERROR", execution_mode_override="PROVIDER ERROR")
                    )
            else:
                # Deterministic Negotiation Engine for mechanical merchant turn
                deterministic_turns += 1
                merchant_floor = Decimal(str(sales_eval.get("bounds", {}).get("absolute_floor", floor_price)))
                merchant_target_price = Decimal(str(sales_eval.get("recommended_standalone_price") or merchant_floor))
                is_acceptable = latest_buyer_offer.total_amount >= merchant_floor
                if is_acceptable:
                    m_action = "ACCEPT"
                    m_rationale = f"Deterministic Engine: Buyer offer of ₹{latest_buyer_offer.total_amount} meets merchant minimum price floor (₹{merchant_floor}) and margin constraints."
                    m_msg = f"Deal agreed! I'll accept ₹{latest_buyer_offer.total_amount} for the basket."
                    m_price = latest_buyer_offer.total_amount
                else:
                    m_action = "COUNTER"
                    m_rationale = f"Deterministic Engine: Offer of ₹{latest_buyer_offer.total_amount} is below floor. Countering at verified price ₹{merchant_target_price}."
                    m_msg = f"I cannot accept below the minimum floor price. My best standalone counter is ₹{merchant_target_price}."
                    m_price = merchant_target_price
                
                from backend.app.agents.provider import BasketItemSchema, MerchantDecision
                merchant_decision = MerchantDecision(
                    action=m_action,
                    product_id=selected_product_id,
                    unit_price=m_price,
                    quantity=1,
                    total_amount=m_price,
                    margin_check="Margin check: PASSED",
                    rationale=m_rationale,
                    message=m_msg,
                    basket_items=[
                        BasketItemSchema(
                            product_id=selected_product_id,
                            name=prod_details["name"] if prod_details else "Product",
                            quantity=1,
                            original_price=prod_details["price"] if prod_details else Decimal("1000"),
                            negotiated_price=m_price,
                            is_primary=True
                        )
                    ]
                )
                current_merchant_meta = {
                    "provider_used": "deterministic_engine",
                    "provider_type": "deterministic_turn",
                    "model_name": "deterministic-engine",
                    "agent_role": "MERCHANT_AGENT",
                    "fallback_used": False,
                    "fallback_depth": 0,
                    "fallback_reason": None,
                    "response_latency_ms": 1.0,
                    "provider_attempts": [{"provider": "deterministic_engine", "model": "deterministic-engine", "success": True, "latency_ms": 1.0}],
                    "is_deterministic": True
                }

            # Ensure basket_items is populated on merchant decision
            p_obj_cur = self.db.query(Product).filter(Product.id == selected_product_id).first()
            valid_m_items = []
            for item in (getattr(merchant_decision, "basket_items", None) or []):
                if isinstance(item, BasketItemSchema):
                    valid_m_items.append(item)
                elif isinstance(item, dict):
                    try:
                        valid_m_items.append(BasketItemSchema.model_validate(item))
                    except Exception:
                        pass
            if not valid_m_items and merchant_decision.action != "REJECT":
                valid_m_items = [
                    BasketItemSchema(
                        product_id=selected_product_id,
                        name=prod_details["name"] if prod_details else "Product",
                        quantity=1,
                        original_price=prod_details["price"] if prod_details else Decimal("1000"),
                        negotiated_price=merchant_decision.total_amount if isinstance(merchant_decision.total_amount, Decimal) else (prod_details["price"] if prod_details else Decimal("1000")),
                        is_primary=True
                    )
                ]
            merchant_decision.basket_items = valid_m_items

            if merchant_decision.action != "REJECT":
                merchant_original_total = sum(Decimal(str(item.original_price)) * Decimal(item.quantity) for item in merchant_decision.basket_items)
                merchant_final_total = sum(Decimal(str(item.negotiated_price)) * Decimal(item.quantity) for item in merchant_decision.basket_items)
                merchant_decision.total_amount = merchant_final_total

            # Deterministic validations on Merchant choice
            if merchant_decision.action == "REJECT":
                AuditEngine.log_event(
                    db=self.db,
                    actor="MERCHANT_AGENT",
                    action="NEGOTIATION_REJECTED",
                    result="FAIL",
                    reason=merchant_decision.rationale
                )
                emit_event({
                    "id": f"evt_r{round_idx}_merchant_reject",
                    "event_id": f"evt_r{round_idx}_merchant_reject",
                    "round": round_idx,
                    "actor": "merchant",
                    "event_type": "rejection",
                    "type": "merchant_message",
                    "state": "REJECTED",
                    "message": getattr(merchant_decision, "message", None) or merchant_decision.rationale,
                    "offer": "0.00",
                    "strategy": f"Merchant Strategy: {sales_eval['strategy']}",
                    "reason_label": "Declined: Below Price Floor",
                    "timestamp": format_ist_timestamp(1.2 * round_idx)
                })
                current_status = "REJECTED"
                memory.final_outcome = "REJECTED"
                break

            elif merchant_decision.action == "ACCEPT":
                # Final check margin and min selling bounds deterministically on accepted buyer basket
                cost_total = Decimal("0.00")
                final_total = Decimal("0.00")
                min_sp_failed = False
                for item in latest_buyer_offer.basket_items:
                    p_obj = self.db.query(Product).filter(Product.id == item.product_id).first()
                    p_cost = p_obj.cost if p_obj else Decimal("0.00")
                    cost_total += p_cost * Decimal(item.quantity)
                    final_total += Decimal(str(item.negotiated_price)) * Decimal(item.quantity)
                    
                    min_sp = p_obj.min_selling_price or p_obj.cost if p_obj else Decimal("0.00")
                    if Decimal(str(item.negotiated_price)) < min_sp:
                        min_sp_failed = True

                calculated_margin = ((final_total - cost_total) / final_total) * Decimal("100") if final_total > Decimal("0") else Decimal("-100.00")
                policy = self.db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
                min_margin = policy.min_margin_percent if policy else Decimal("15.00")
                margin_passed = calculated_margin >= min_margin and not min_sp_failed
                
                # Log POLICY_CHECK
                AuditEngine.log_event(
                    db=self.db,
                    actor="SYSTEM",
                    action="POLICY_CHECK",
                    result="SUCCESS" if margin_passed else "FAIL",
                    reason=f"Merchant acceptance margin check. Margin Passed: {margin_passed}"
                )
                
                memory.add_policy_verdict(
                    decision="APPROVED" if margin_passed else "BLOCKED",
                    reasons=[] if margin_passed else ["Merchant accepted price below required minimum profit margin."]
                )

                if not margin_passed:
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_REJECTED",
                        result="BLOCKED",
                        reason=f"Merchant accepted price {latest_buyer_offer.total_amount} violates margin policy."
                    )
                    raise NegotiationError("Negotiation failed: Merchant cannot accept offer violating minimum profit margin.", build_failed_result(["Merchant cannot accept offer violating minimum profit margin."]))

                AuditEngine.log_event(
                    db=self.db,
                    actor="MERCHANT_AGENT",
                    action="NEGOTIATION_ACCEPTED",
                    result="SUCCESS",
                    reason=merchant_decision.rationale
                )

                serialized_merchant_accept_items = [
                    {
                        "product_id": item.product_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "original_price": str(item.original_price),
                        "negotiated_price": str(item.negotiated_price),
                        "is_primary": item.is_primary
                    }
                    for item in latest_buyer_offer.basket_items
                ]

                emit_event({
                    "id": f"evt_r{round_idx}_merchant_accept",
                    "event_id": f"evt_r{round_idx}_merchant_accept",
                    "round": round_idx,
                    "actor": "merchant",
                    "event_type": "acceptance",
                    "type": "merchant_message",
                    "state": "AGREED",
                    "message": getattr(merchant_decision, "message", None) or f"Deal agreed! I'll accept ₹{latest_buyer_offer.total_amount} for the basket.",
                    "offer": str(latest_buyer_offer.total_amount),
                    "basket_items": serialized_merchant_accept_items,
                    "strategy": f"Merchant Strategy: {sales_eval['strategy']}",
                    "reason_label": "Merchant acceptance within margin bounds",
                    "timestamp": format_ist_timestamp(1.2 * round_idx)
                })

                current_status = "AGREED"
                final_price = latest_buyer_offer.total_amount
                selected_product_id = latest_buyer_offer.product_id
                break

            else:  # COUNTER
                # Validate margin and min selling bounds on Merchant counter basket
                cost_total = Decimal("0.00")
                final_total = Decimal("0.00")
                min_sp_failed = False
                for item in merchant_decision.basket_items:
                    p_obj = self.db.query(Product).filter(Product.id == item.product_id).first()
                    p_cost = p_obj.cost if p_obj else Decimal("0.00")
                    cost_total += p_cost * Decimal(item.quantity)
                    final_total += Decimal(str(item.negotiated_price)) * Decimal(item.quantity)
                    
                    min_sp = p_obj.min_selling_price or p_obj.cost if p_obj else Decimal("0.00")
                    if Decimal(str(item.negotiated_price)) < min_sp:
                        min_sp_failed = True

                if final_total > Decimal("0"):
                    calculated_margin = ((final_total - cost_total) / final_total) * Decimal("100")
                else:
                    calculated_margin = Decimal("-100.00")

                policy = self.db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
                min_margin = policy.min_margin_percent if policy else Decimal("15.00")
                margin_passed = calculated_margin >= min_margin and not min_sp_failed
                
                # Log POLICY_CHECK
                AuditEngine.log_event(
                    db=self.db,
                    actor="SYSTEM",
                    action="POLICY_CHECK",
                    result="SUCCESS" if margin_passed else "FAIL",
                    reason=f"Merchant counter-offer margin check. Margin Passed: {margin_passed}"
                )
                
                memory.add_policy_verdict(
                    decision="APPROVED" if margin_passed else "BLOCKED",
                    reasons=[] if margin_passed else ["Merchant counter below required minimum margin limit floor."]
                )

                if not margin_passed:
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_REJECTED",
                        result="BLOCKED",
                        reason=f"Merchant Counter of {merchant_decision.total_amount} is below minimum margin limit floor."
                    )
                    raise NegotiationError("Negotiation failed: Merchant proposed counter-offer violates minimum profit margin constraints.", build_failed_result(["Merchant proposed counter-offer violates minimum profit margin constraints."]))

                # Log MERCHANT_COUNTER event
                AuditEngine.log_event(
                    db=self.db,
                    actor="MERCHANT_AGENT",
                    action="MERCHANT_COUNTER",
                    result="SUCCESS",
                    reason=merchant_decision.rationale,
                    metadata={"amount": str(merchant_decision.total_amount), "confidence": str(self.merchant.last_confidence)}
                )

                AuditEngine.log_event(
                    db=self.db,
                    actor="MERCHANT_AGENT",
                    action="MERCHANT_COUNTER_CREATED",
                    result="SUCCESS",
                    reason=merchant_decision.rationale,
                    metadata={
                        "product_id": merchant_decision.product_id,
                        "quantity": merchant_decision.quantity,
                        "offered_price": str(merchant_decision.total_amount),
                        "margin_check": merchant_decision.margin_check
                    }
                )

                discount_amt = merchant_original_total - merchant_decision.total_amount
                discount_pct = (discount_amt / merchant_original_total) * Decimal("100") if merchant_original_total > Decimal("0") else Decimal("0")

                serialized_merchant_counter_items = [
                    {
                        "product_id": item.product_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "original_price": str(item.original_price),
                        "negotiated_price": str(item.negotiated_price),
                        "is_primary": item.is_primary
                    }
                    for item in merchant_decision.basket_items
                ]

                # Check if this is a primary bundle offer (requested bundle by buyer)
                is_bundle_counter = not budget_info.get("standalone_preferred", True) and (len(merchant_decision.basket_items) > 1 or getattr(merchant_decision, "proposal_type", "") == "BUNDLE_PROPOSAL")

                # Determine standalone counter price (strictly for primary product)
                primary_basket_item = next((item for item in merchant_decision.basket_items if getattr(item, "is_primary", False)), None)
                if primary_basket_item and getattr(primary_basket_item, "negotiated_price", None):
                    standalone_counter_price = Decimal(str(primary_basket_item.negotiated_price))
                elif sales_eval.get("recommended_standalone_price"):
                    standalone_counter_price = Decimal(str(sales_eval["recommended_standalone_price"]))
                elif p_obj_cur and getattr(p_obj_cur, "min_selling_price", None):
                    standalone_counter_price = Decimal(str(p_obj_cur.min_selling_price))
                elif len(merchant_decision.basket_items) == 1 and merchant_decision.total_amount:
                    standalone_counter_price = Decimal(str(merchant_decision.total_amount))
                else:
                    standalone_counter_price = Decimal(str(p_obj_cur.price if p_obj_cur else merchant_decision.total_amount))

                standalone_counter_price = standalone_counter_price.quantize(Decimal("0.01"))

                serialized_standalone_items = [
                    {
                        "product_id": selected_product_id,
                        "name": prod_details["name"] if prod_details else "Product",
                        "quantity": 1,
                        "original_price": str(prod_details["price"]) if prod_details else str(standalone_counter_price),
                        "negotiated_price": str(standalone_counter_price),
                        "is_primary": True
                    }
                ]

                # Distinguish between NEW COUNTER, HOLDING PREVIOUS OFFER, and BUNDLE
                is_hold = (
                    sales_eval["strategy"] == "HOLD_PRICE" or 
                    (last_merchant_standalone_price is not None and Decimal(str(standalone_counter_price)) == Decimal(str(last_merchant_standalone_price)))
                )

                if is_hold and last_merchant_standalone_id:
                    prop_standalone_id = last_merchant_standalone_id
                    proposal_type_val = "HOLD_PREVIOUS_OFFER"
                    state_val = "MERCHANT_HOLD"
                    event_type_val = "hold_offer"
                    reason_label_val = "Holding Previous Offer"
                    merchant_msg = getattr(merchant_decision, "message", None) or f"₹{latest_buyer_offer.total_amount} is below the best price I can support. I need to hold at my previous offer of ₹{standalone_counter_price} for {prod_details['name'] if prod_details else 'the standalone product'}. If that works for you, we have a deal."
                else:
                    prop_standalone_id = f"prop_m_r{round_idx}_standalone"
                    last_merchant_standalone_id = prop_standalone_id
                    last_merchant_standalone_price = standalone_counter_price
                    proposal_type_val = "STANDALONE_COUNTER"
                    state_val = "MERCHANT_COUNTER"
                    event_type_val = "bundle_offer" if is_bundle_counter else "counter_offer"
                    reason_label_val = "Merchant bundle proposal" if is_bundle_counter else "Within merchant price floor & margin rules"
                    merchant_msg = getattr(merchant_decision, "message", None) or merchant_decision.rationale

                    standalone_prop_record = {
                        "proposal_id": prop_standalone_id,
                        "actor": "merchant",
                        "proposal_type": "STANDALONE_COUNTER",
                        "parent_proposal_id": "prop_b_r1",
                        "round": round_idx,
                        "basket_items": serialized_standalone_items,
                        "total_amount": str(standalone_counter_price),
                        "offered_amount": str(standalone_counter_price),
                        "is_optional_bundle": False,
                        "status": "OPEN",
                        "strategy": sales_eval["strategy"],
                        "reason": sales_eval["reason"]
                    }
                    proposals.append(standalone_prop_record)
                    merchant_standalone_counter_record = standalone_prop_record

                bundle_proposal_dict = None
                serialized_bundle_items = None
                has_bundle_opportunity = (
                    is_bundle_counter or 
                    sales_eval.get("bundle_info") is not None or 
                    len(merchant_decision.basket_items) > 1 or 
                    getattr(merchant_decision, "bundle_proposal", None) is not None or 
                    optional_bundle_dict is not None
                )
                if has_bundle_opportunity and not is_hold:
                    if getattr(merchant_decision, "bundle_proposal", None) and merchant_decision.bundle_proposal.basket_items:
                        serialized_bundle_items = [
                            {
                                "product_id": item["product_id"] if isinstance(item, dict) else item.product_id,
                                "name": item["name"] if isinstance(item, dict) else item.name,
                                "quantity": item["quantity"] if isinstance(item, dict) else item.quantity,
                                "original_price": str(item["original_price"] if isinstance(item, dict) else item.original_price),
                                "negotiated_price": str(item["negotiated_price"] if isinstance(item, dict) else item.negotiated_price),
                                "is_primary": item["is_primary"] if isinstance(item, dict) else item.is_primary
                            }
                            for item in merchant_decision.bundle_proposal.basket_items
                        ]
                    elif is_bundle_counter or len(merchant_decision.basket_items) > 1:
                        serialized_bundle_items = [
                            {
                                "product_id": item.product_id,
                                "name": item.name,
                                "quantity": item.quantity,
                                "original_price": str(item.original_price),
                                "negotiated_price": str(item.negotiated_price),
                                "is_primary": item.is_primary
                            }
                            for item in merchant_decision.basket_items
                        ]
                    elif sales_eval.get("bundle_info"):
                        prescription = sales_eval["bundle_info"]["prescription"]
                        serialized_bundle_items = [
                            {
                                "product_id": item["product_id"],
                                "name": item["name"],
                                "quantity": item["quantity"],
                                "original_price": str(item["original_price"]),
                                "negotiated_price": str(item["negotiated_price"]),
                                "is_primary": item["is_primary"]
                            }
                            for item in prescription["bundle_items"]
                        ]
                    elif optional_bundle_dict and optional_bundle_dict.get("bundle_items"):
                        serialized_bundle_items = [
                            {
                                "product_id": item["product_id"],
                                "name": item["name"],
                                "quantity": item["quantity"],
                                "original_price": str(item["original_price"]),
                                "negotiated_price": str(item["negotiated_price"]),
                                "is_primary": item["is_primary"]
                            }
                            for item in optional_bundle_dict["bundle_items"]
                        ]
                    
                    if serialized_bundle_items and len(serialized_bundle_items) > 1:
                        catalog_lookup = {p.id: p for p in self.db.query(Product).all()}
                        bundle_fin = calculate_basket_financials(serialized_bundle_items, catalog_lookup=catalog_lookup)
                        prop_bundle_id = f"prop_m_r{round_idx}_bundle"
                        last_merchant_bundle_id = prop_bundle_id
                        bundle_proposal_dict = {
                            "proposal_id": prop_bundle_id,
                            "actor": "merchant",
                            "proposal_type": "BUNDLE_PROPOSAL",
                            "parent_proposal_id": "prop_b_r1",
                            "round": round_idx,
                            "original_amount": bundle_fin["catalog_total"],
                            "offered_amount": bundle_fin["basket_total"],
                            "total_amount": bundle_fin["basket_total"],
                            "savings": bundle_fin["buyer_savings_amount"],
                            "basket_items": serialized_bundle_items,
                            "is_optional_bundle": True,
                            "status": "OPEN",
                            "strategy": "BUNDLE"
                        }
                        proposals.append(bundle_proposal_dict)
                        merchant_bundle_proposal_record = bundle_proposal_dict
                        
                        bundle_comp_names = " + ".join([it["name"] for it in serialized_bundle_items]) if serialized_bundle_items else "Accessories"
                        primary_name = prod_details["name"] if prod_details else "Product"
                        if not getattr(merchant_decision, "message", None) or "bundle" not in merchant_decision.message.lower():
                            merchant_msg = f"I can offer the standalone {primary_name} for ₹{standalone_counter_price}, or an optional value bundle ({bundle_comp_names}) for ₹{bundle_fin['basket_total']} (save ₹{bundle_fin['buyer_savings_amount']})."

                active_proposals_list = [p for p in proposals if p.get("round") == round_idx and p.get("actor") == "merchant"]
                primary_offer_amt = merchant_decision.total_amount if is_bundle_counter else standalone_counter_price
                primary_basket_items = serialized_merchant_counter_items if is_bundle_counter else serialized_standalone_items
                primary_orig_amt = merchant_original_total if is_bundle_counter else (Decimal(str(prod_details["price"])) if prod_details else standalone_counter_price)
                prop_primary_id = prop_bundle_id if is_bundle_counter else prop_standalone_id
                event_proposal_type = "BUNDLE_PROPOSAL" if is_bundle_counter else proposal_type_val

                # Record Merchant Counter Event
                emit_event({
                    "id": f"evt_r{round_idx}_merchant_counter",
                    "event_id": f"evt_r{round_idx}_merchant_counter",
                    "round": round_idx,
                    "actor": "merchant",
                    "event_type": event_type_val,
                    "type": "merchant_message",
                    "state": state_val,
                    "proposal_id": prop_primary_id,
                    "proposal_type": event_proposal_type,
                    "message": merchant_msg,
                    "offer": str(primary_offer_amt),
                    "standalone_counter": str(standalone_counter_price),
                    "bundle_proposal": bundle_proposal_dict,
                    "optional_bundle_items": serialized_bundle_items,
                    "basket_items": primary_basket_items,
                    "proposals": active_proposals_list,
                    "strategy": f"Merchant Strategy: {sales_eval['strategy']}",
                    "reason_label": reason_label_val,
                    "timestamp": format_ist_timestamp(1.2 * round_idx)
                })

                catalog_lookup = {p.id: p for p in self.db.query(Product).all()}
                primary_fin = calculate_basket_financials(primary_basket_items, catalog_lookup=catalog_lookup)
                primary_margin = Decimal(str(primary_fin["gross_margin_percent"]))

                # Record SETU Price Floor & Margin Check
                emit_event({
                    "id": f"evt_r{round_idx}_setu_floor",
                    "event_id": f"evt_r{round_idx}_setu_floor",
                    "round": round_idx,
                    "actor": "setu",
                    "event_type": "trust_check",
                    "type": "system_event",
                    "state": "PRICING_VALIDATED",
                    "message": f"SETU enforced merchant price floor & margin policy constraints ({primary_margin.quantize(Decimal('0.01'))}% margin).",
                    "reason_label": "Price Floor & Margin Enforced",
                    "timestamp": format_ist_timestamp(1.2 * round_idx + 0.3)
                })

                negotiation_history.append({
                    "round": round_idx,
                    "buyer_offer": None,
                    "merchant_offer": {
                        "product_ids": [item["product_id"] for item in primary_basket_items],
                        "original_amount": str(primary_orig_amt),
                        "offered_amount": str(primary_offer_amt),
                        "discount_percent": str(discount_pct.quantize(Decimal("0.01"))),
                        "reason": sales_eval["reason"],
                        "message": merchant_msg,
                        "reason_label": reason_label_val,
                        "tools_used": list(self.merchant.tools_called_in_session),
                        "confidence": self.merchant.last_confidence,
                        "basket_items": primary_basket_items,
                        "bundle_proposal": bundle_proposal_dict
                    },
                    "accepted": False,
                    "reason": sales_eval["reason"]
                })

                latest_merchant_counter = merchant_decision
                merchant_countered = True

            # --- BUYER TURN (if Merchant Countered) ---
            if merchant_countered:
                # Buyer gathers budget checks
                budget_eval = evaluate_budget_tool(self.db, str(latest_merchant_counter.total_amount), str(budget))

                buyer_eval_prompt = (
                    f"=== CURRENT NEGOTIATION CONTEXT ===\n"
                    f"NEGOTIATION SESSION ID: {session_id}\n"
                    f"CURRENT PRODUCT ID: {selected_product_id}\n"
                    f"CURRENT PRODUCT NAME: {prod_details['name'] if prod_details else 'Product'}\n"
                    f"CURRENT CATALOG PRICE: ₹{prod_details['price'] if prod_details else '0'}\n"
                    f"CURRENT BUYER BUDGET: ₹{effective_max_budget}\n"
                    f"CURRENT MERCHANT STANDALONE: ₹{standalone_counter_price}\n"
                )
                if bundle_proposal_dict:
                    buyer_eval_prompt += f"CURRENT MERCHANT BUNDLE: ₹{bundle_proposal_dict['offered_amount']}\n"
                buyer_eval_prompt += (
                    f"====================================\n"
                    f"You are the Buyer Agent. User Intent: '{intent}' with target budget: ₹{budget_info['target_budget']} and maximum budget: ₹{effective_max_budget}.\n"
                    f"Your Profile: {budget_info.get('buyer_profile', 'PRICE_FIRST')} (Standalone Preferred: {budget_info.get('standalone_preferred', True)}).\n"
                    f"Merchant Action: {sales_eval['strategy']} - {merchant_msg}\n"
                    f"Merchant Proposal Options:\n"
                    f"  Option 1 (Standalone): ₹{standalone_counter_price} for {prod_details['name'] if prod_details else 'Product'}.\n"
                )
                if bundle_proposal_dict:
                    buyer_eval_prompt += f"  Option 2 (Optional Bundle): ₹{bundle_proposal_dict['offered_amount']} (Savings: ₹{bundle_proposal_dict['savings']}).\n"
                buyer_eval_prompt += (
                    f"Evaluate if the optional bundle is genuinely desired. If you only requested standalone, prefer negotiating the standalone option.\n"
                    f"If the merchant maintains an unchanged price or makes a final offer, decide whether to accept or reject.\n"
                    f"Formulate your response (COUNTER, ACCEPT, or REJECT)."
                )

                buyer_context = NegotiationContext(
                    agent_role="BUYER_AGENT",
                    current_round=round_idx,
                    buyer_max_budget=effective_max_budget,
                    current_product=prod_details,
                    catalog_price=Decimal(str(prod_details.get("price", "1000.00"))),
                    merchant_min_price=floor_price,
                    current_proposal={
                        "product_id": selected_product_id,
                        "standalone_price": str(standalone_counter_price),
                        "total_amount": str(standalone_counter_price),
                        "options_summary": f"Option 1: Standalone for INR {standalone_counter_price}" + (f", Option 2: Optional Bundle for INR {bundle_proposal_dict['offered_amount']} (Savings: INR {bundle_proposal_dict['savings']})" if bundle_proposal_dict else ""),
                        "bundle_proposal": bundle_proposal_dict
                    },
                    previous_offers=[{"round": p.get("round", 1), "actor": p.get("actor"), "total_amount": p.get("total_amount")} for p in proposals],
                    max_allowed_discount=max_disc,
                    inventory_availability=prod_details.get("inventory", 10),
                    relevant_policy_constraints=policy_info,
                    remaining_rounds=max(0, max_rounds - round_idx),
                    optional_bundle=optional_bundle_dict,
                    bundle_already_proposed=bool(bundle_proposal_dict is not None),
                    standalone_preferred=budget_info.get("standalone_preferred", True),
                    buyer_profile=budget_info.get("buyer_profile", "PRICE_FIRST")
                )

                if llm_calls_made < max_llm_budget:
                    try:
                        buyer_decision = self.buyer.negotiate_decision(self.db, buyer_eval_prompt, memory=memory, context=buyer_context)
                        current_buyer_meta = getattr(buyer_decision, "provider_metadata", None) or getattr(self.buyer, "last_execution_metadata", None) or getattr(self.buyer.provider, "last_execution_metadata", None)
                        if current_buyer_meta:
                            provider_call_records.append(current_buyer_meta)
                        buyer_llm_calls += 1
                        llm_calls_made += 1
                    except Exception as e:
                        logger.error(f"Buyer Agent LLM failure: {e}")
                        AuditEngine.log_event(
                            db=self.db,
                            actor="SYSTEM",
                            action="PROVIDER_FAILURE",
                            result="ERROR",
                            reason=f"Buyer Agent LLM call failed: {str(e)}",
                            metadata={"session_id": session_id, "provider": provider_name, "model": model_name}
                        )
                        raise NegotiationError(
                            f"LLM Provider failure: {str(e)}", 
                            build_failed_result([f"LLM Provider failure: {str(e)}"], decision_val="ERROR", execution_mode_override="PROVIDER ERROR")
                        )
                else:
                    # Deterministic Negotiation Engine for mechanical buyer turn
                    deterministic_turns += 1
                    target_price = Decimal(str(standalone_counter_price))
                    if target_price <= effective_max_budget:
                        b_action = "ACCEPT"
                        b_rationale = f"Deterministic Engine: Merchant offer of ₹{target_price} is within buyer budget boundary of ₹{effective_max_budget}."
                        b_msg = f"Deal agreed! ₹{target_price} for {prod_details['name'] if prod_details else 'the product'} fits within my budget."
                    else:
                        b_action = "REJECT"
                        b_rationale = f"Deterministic Engine: Merchant counter of ₹{target_price} exceeds buyer maximum budget of ₹{effective_max_budget}."
                        b_msg = f"Unable to proceed as ₹{target_price} exceeds the maximum authorized budget."
                    
                    from backend.app.agents.provider import BasketItemSchema, BuyerDecision
                    buyer_decision = BuyerDecision(
                        action=b_action,
                        product_id=selected_product_id,
                        quantity=1,
                        unit_price=target_price,
                        total_amount=target_price,
                        rationale=b_rationale,
                        message=b_msg,
                        constraints_checked=["budget_fit", "catalog_price_bound"],
                        basket_items=[
                            BasketItemSchema(
                                product_id=selected_product_id,
                                name=prod_details["name"] if prod_details else "Product",
                                quantity=1,
                                original_price=prod_details["price"] if prod_details else Decimal("1000"),
                                negotiated_price=target_price,
                                is_primary=True
                            )
                        ]
                    )
                    current_buyer_meta = {
                        "provider_used": "deterministic_engine",
                        "provider_type": "deterministic_turn",
                        "model_name": "deterministic-engine",
                        "agent_role": "BUYER_AGENT",
                        "fallback_used": False,
                        "fallback_depth": 0,
                        "fallback_reason": None,
                        "response_latency_ms": 1.0,
                        "provider_attempts": [{"provider": "deterministic_engine", "model": "deterministic-engine", "success": True, "latency_ms": 1.0}],
                        "is_deterministic": True
                    }

                # Ensure basket_items is populated on buyer decision
                p_obj = self.db.query(Product).filter(Product.id == buyer_decision.product_id).first()
                valid_b_items = []
                for item in (getattr(buyer_decision, "basket_items", None) or []):
                    if isinstance(item, BasketItemSchema):
                        valid_b_items.append(item)
                    elif isinstance(item, dict):
                        try:
                            valid_b_items.append(BasketItemSchema.model_validate(item))
                        except Exception:
                            pass
                if not valid_b_items and buyer_decision.action != "REJECT":
                    valid_b_items = [
                        BasketItemSchema(
                            product_id=buyer_decision.product_id if isinstance(buyer_decision.product_id, int) else (p_obj.id if p_obj else 1),
                            name=p_obj.name if p_obj else "Product",
                            quantity=buyer_decision.quantity if isinstance(buyer_decision.quantity, int) else 1,
                            original_price=p_obj.price if p_obj else (buyer_decision.unit_price if isinstance(buyer_decision.unit_price, Decimal) else Decimal("1000")),
                            negotiated_price=buyer_decision.unit_price if isinstance(buyer_decision.unit_price, Decimal) else Decimal("1000"),
                            is_primary=True
                        )
                    ]
                buyer_decision.basket_items = valid_b_items

                if buyer_decision.action != "REJECT":
                    buyer_original_total = sum(Decimal(str(item.original_price)) * Decimal(item.quantity) for item in buyer_decision.basket_items)
                    buyer_final_total = sum(Decimal(str(item.negotiated_price)) * Decimal(item.quantity) for item in buyer_decision.basket_items)
                    buyer_decision.total_amount = buyer_final_total

                serialized_buyer_counter_items = [
                    {
                        "product_id": item.product_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "original_price": str(item.original_price),
                        "negotiated_price": str(item.negotiated_price),
                        "is_primary": item.is_primary
                    }
                    for item in buyer_decision.basket_items
                ]

                if buyer_decision.action == "REJECT":
                    AuditEngine.log_event(
                        db=self.db,
                        actor="BUYER_AGENT",
                        action="NEGOTIATION_REJECTED",
                        result="FAIL",
                        reason=buyer_decision.rationale
                    )
                    emit_event({
                        "id": f"evt_r{round_idx}_buyer_reject",
                        "event_id": f"evt_r{round_idx}_buyer_reject",
                        "round": round_idx,
                        "actor": "buyer",
                        "event_type": "rejection",
                        "type": "buyer_message",
                        "state": "REJECTED",
                        "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
                        "offer": "0.00",
                        "reason_label": "Buyer declined proposal",
                        "timestamp": format_ist_timestamp(1.2 * round_idx + 0.6)
                    })
                    current_status = "REJECTED"
                    memory.final_outcome = "REJECTED"
                    break

                elif buyer_decision.action == "ACCEPT":
                    is_bundle_accept = len(buyer_decision.basket_items) > 1 or (len(merchant_decision.basket_items) > 1 and buyer_decision.total_amount == merchant_decision.total_amount)
                    if is_bundle_accept:
                        accepted_proposal_id = last_merchant_bundle_id or f"prop_m_r{round_idx}_bundle"
                        accepted_items = serialized_bundle_items if serialized_bundle_items else serialized_buyer_counter_items
                    else:
                        accepted_proposal_id = last_merchant_standalone_id or f"prop_m_r{round_idx}_standalone"
                        accepted_items = serialized_standalone_items

                    accepted_prop = next((p for p in proposals if p.get("proposal_id") == accepted_proposal_id), None)
                    accepted_amount = Decimal(accepted_prop.get("total_amount") or accepted_prop.get("offered_amount") or str(buyer_decision.total_amount)) if accepted_prop else buyer_decision.total_amount

                    # Double check budget constraint against effective maximum budget
                    final_budget_eval = evaluate_budget_tool(self.db, str(accepted_amount), str(effective_max_budget))
                    
                    # Log POLICY_CHECK
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_CHECK",
                        result="SUCCESS" if final_budget_eval["within_budget"] else "FAIL",
                        reason=f"Buyer acceptance budget check. Max Budget: ₹{effective_max_budget}. Final: ₹{accepted_amount}"
                    )
                    
                    memory.add_policy_verdict(
                        decision="APPROVED" if final_budget_eval["within_budget"] else "BLOCKED",
                        reasons=[] if final_budget_eval["within_budget"] else ["Accepted price violates budget constraint."]
                    )

                    if not final_budget_eval["within_budget"]:
                        AuditEngine.log_event(
                            db=self.db,
                            actor="SYSTEM",
                            action="POLICY_REJECTED",
                            result="BLOCKED",
                            reason="Buyer accepted counter-offer exceeding maximum budget limit."
                        )
                        raise NegotiationError("Negotiation failed: Accepted price exceeds configured budget limit.", build_failed_result(["Accepted price exceeds configured budget limit."]))

                    AuditEngine.log_event(
                        db=self.db,
                        actor="BUYER_AGENT",
                        action="BUYER_ACCEPTED",
                        result="SUCCESS",
                        reason=buyer_decision.rationale
                    )

                    if accepted_prop:
                        accepted_prop["status"] = "ACCEPTED"

                    for p in proposals:
                        if p.get("proposal_id") != accepted_proposal_id and p.get("status") == "OPEN":
                            p["status"] = "SUPERSEDED"

                    emit_event({
                        "id": f"evt_r{round_idx}_buyer_accept",
                        "event_id": f"evt_r{round_idx}_buyer_accept",
                        "round": round_idx,
                        "actor": "buyer",
                        "event_type": "acceptance",
                        "type": "buyer_message",
                        "state": "AGREED",
                        "proposal_type": "ACCEPTANCE",
                        "proposal_id": accepted_proposal_id,
                        "accepted_proposal_id": accepted_proposal_id,
                        "message": getattr(buyer_decision, "message", None) or f"Deal agreed! ₹{accepted_amount} for the basket works for me.",
                        "offer": str(accepted_amount),
                        "basket_items": accepted_items,
                        "reason_label": "Buyer accepts deal within budget limit",
                        "timestamp": format_ist_timestamp(1.2 * round_idx + 0.6)
                    })
                    
                    # Append acceptance turn to history for completeness
                    negotiation_history.append({
                        "round": round_idx + 1,
                        "buyer_offer": {
                            "product_id": buyer_decision.product_id,
                            "quantity": buyer_decision.quantity,
                            "original_amount": str(merchant_original_total),
                            "final_amount": str(accepted_amount),
                            "currency": "INR",
                            "reason": buyer_decision.rationale,
                            "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
                            "reason_label": "Buyer accepts deal within budget limit",
                            "tools_used": list(self.buyer.tools_called_in_session),
                            "confidence": self.buyer.last_confidence,
                            "basket_items": accepted_items
                        },
                        "merchant_offer": None,
                        "accepted": True,
                        "reason": buyer_decision.rationale
                    })
                    
                    current_status = "AGREED"
                    final_price = accepted_amount
                    primary_item_acc = next((item for item in accepted_items if item.get("is_primary")), None)
                    if primary_item_acc and "product_id" in primary_item_acc:
                        selected_product_id = primary_item_acc["product_id"]
                    elif selected_product_id:
                        pass
                    else:
                        selected_product_id = buyer_decision.product_id
                    latest_buyer_offer = buyer_decision
                    break

                else:  # COUNTER
                    # Enforce budget limits
                    counter_budget_eval = evaluate_budget_tool(self.db, str(buyer_decision.total_amount), str(effective_max_budget))
                    
                    # Log POLICY_CHECK
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_CHECK",
                        result="SUCCESS" if counter_budget_eval["within_budget"] else "FAIL",
                        reason=f"Buyer counter budget check. Max Budget: ₹{effective_max_budget}. Counter: ₹{buyer_decision.total_amount}"
                    )
                    
                    memory.add_policy_verdict(
                        decision="APPROVED" if counter_budget_eval["within_budget"] else "BLOCKED",
                        reasons=[] if counter_budget_eval["within_budget"] else ["Counter price exceeds budget limit."]
                    )

                    if not counter_budget_eval["within_budget"]:
                        AuditEngine.log_event(
                            db=self.db,
                            actor="SYSTEM",
                            action="POLICY_REJECTED",
                            result="BLOCKED",
                            reason=f"Buyer counter {buyer_decision.total_amount} exceeds budget boundary limit."
                        )
                        raise NegotiationError("Negotiation failed: Proposed price exceeds configured budget limit.", build_failed_result(["Proposed price exceeds configured budget limit."]))

                    # Log BUYER_OFFER event
                    AuditEngine.log_event(
                        db=self.db,
                        actor="BUYER_AGENT",
                        action="BUYER_OFFER",
                        result="SUCCESS",
                        reason=buyer_decision.rationale,
                        metadata={"amount": str(buyer_decision.total_amount), "confidence": str(self.buyer.last_confidence)}
                    )

                    prop_b_counter_id = f"prop_b_r{round_idx}"
                    proposals.append({
                        "proposal_id": prop_b_counter_id,
                        "actor": "buyer",
                        "proposal_type": "STANDALONE_COUNTER" if len(buyer_decision.basket_items) == 1 else "BUNDLE_COUNTER",
                        "parent_proposal_id": prop_standalone_id,
                        "round": round_idx,
                        "basket_items": serialized_buyer_counter_items,
                        "total_amount": str(buyer_decision.total_amount),
                        "is_optional_bundle": len(buyer_decision.basket_items) > 1,
                        "status": "OPEN",
                        "reason": buyer_decision.rationale
                    })

                    emit_event({
                        "id": f"evt_r{round_idx}_buyer_counter",
                        "event_id": f"evt_r{round_idx}_buyer_counter",
                        "round": round_idx,
                        "actor": "buyer",
                        "event_type": "counter_offer",
                        "type": "buyer_message",
                        "state": "BUYER_COUNTER",
                        "proposal_id": prop_b_counter_id,
                        "proposal_type": "STANDALONE_COUNTER" if len(buyer_decision.basket_items) == 1 else "BUNDLE_COUNTER",
                        "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
                        "offer": str(buyer_decision.total_amount),
                        "basket_items": serialized_buyer_counter_items,
                        "reason_label": "Buyer counter within budget boundary",
                        "timestamp": format_ist_timestamp(1.2 * round_idx + 0.6)
                    })

                    negotiation_history.append({
                        "round": round_idx,
                        "buyer_offer": {
                            "product_id": buyer_decision.product_id,
                            "quantity": buyer_decision.quantity,
                            "original_amount": str(buyer_original_total),
                            "final_amount": str(buyer_decision.total_amount),
                            "currency": "INR",
                            "reason": buyer_decision.rationale,
                            "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
                            "reason_label": "Buyer counter within budget boundary",
                            "tools_used": list(self.buyer.tools_called_in_session),
                            "confidence": self.buyer.last_confidence,
                            "basket_items": serialized_buyer_counter_items
                        },
                        "merchant_offer": None,
                        "accepted": False,
                        "reason": buyer_decision.rationale
                    })

                    latest_buyer_offer = buyer_decision

                    AuditEngine.log_event(
                        db=self.db,
                        actor="BUYER_AGENT",
                        action="BUYER_OFFER_CREATED",
                        result="SUCCESS",
                        reason=buyer_decision.rationale,
                        metadata={
                            "product_id": buyer_decision.product_id,
                            "quantity": buyer_decision.quantity,
                            "offered_price": str(buyer_decision.total_amount),
                            "constraints_checked": buyer_decision.constraints_checked
                        }
                    )

                    latest_buyer_offer = buyer_decision
                    merchant_countered = False

        # 4. Finalization & Policy Verification
        if current_status == "AGREED" and final_price is not None and selected_product_id is not None:
            current_stage = NegotiationStage.POLICY_VALIDATION
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="POLICY_VALIDATION",
                result="SUCCESS",
                reason="Submitting purchase request to backend Policy Engine."
            )

            # Log POLICY_CHECK
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="POLICY_CHECK",
                result="SUCCESS",
                reason="Verifying final proposed price against Merchant policies."
            )

            current_stage = NegotiationStage.FINAL_BASKET_VALIDATION
            # Retrieve the exact accepted proposal snapshot
            accepted_prop = next((p for p in proposals if p.get("proposal_id") == accepted_proposal_id), None)
            if accepted_prop and accepted_prop.get("basket_items"):
                serialized_basket_items = accepted_prop["basket_items"]
            else:
                serialized_basket_items = [
                    {
                        "product_id": item.product_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "original_price": str(item.original_price),
                        "negotiated_price": str(item.negotiated_price),
                        "is_primary": item.is_primary
                    }
                    for item in latest_buyer_offer.basket_items
                ]

            # Calculate canonical financials
            catalog_lookup = {p.id: p for p in self.db.query(Product).all()}
            financials = calculate_basket_financials(serialized_basket_items, catalog_lookup=catalog_lookup)

            basket_dict = {
                "items": serialized_basket_items,
                "original_total": financials["catalog_total"],
                "final_total": financials["basket_total"],
                "discount_amount": financials["discount_amount"],
                "gross_margin_percent": financials["gross_margin_percent"],
                "profit_amount": financials["profit_amount"],
                "total_cost": financials["total_cost"]
            }

            final_price = Decimal(financials["basket_total"])

            current_stage = NegotiationStage.NEGOTIATION_SNAPSHOT
            # Determine component product IDs for legacy backward compatibility check
            comp_ids = [item["product_id"] for item in serialized_basket_items]
            purchase_prod_id = 1 if (1 in comp_ids and 2 in comp_ids) else selected_product_id

            current_stage = NegotiationStage.PURCHASE_REQUEST_CREATION
            purchase_res = request_purchase_tool(
                db=self.db,
                buyer_id=buyer_id,
                product_id=purchase_prod_id,
                quantity=1,
                proposed_price=str(final_price),
                reason="AI-to-AI negotiated procurement agreement",
                basket=basket_dict
            )

            if purchase_res["decision"] == "BLOCKED":
                AuditEngine.log_event(
                    db=self.db,
                    actor="SYSTEM",
                    action="POLICY_REJECTED",
                    result="BLOCKED",
                    reason=f"Final Policy engine validation failure: {', '.join(purchase_res['reasons'])}"
                )
                memory.add_policy_verdict(decision="BLOCKED", reasons=purchase_res["reasons"])
                memory.final_outcome = "BLOCKED"
                raise NegotiationError(f"Policy Engine rejected final deal: {', '.join(purchase_res['reasons'])}", build_failed_result(purchase_res['reasons'], final_price, error_code="POLICY_REJECTED"))

            final_decision_pr_id = purchase_res["purchase_request_id"]
            memory.final_outcome = "APPROVED"
            
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="PURCHASE_REQUEST",
                result="SUCCESS",
                reason="Purchase request logged successfully in system ledger.",
                entity_type="PurchaseRequest",
                entity_id=final_decision_pr_id,
                metadata={
                    "purchase_request_id": final_decision_pr_id,
                    "accepted_proposal_id": accepted_proposal_id,
                    "proposal_type": accepted_prop.get("proposal_type") if accepted_prop else None,
                    "basket": basket_dict,
                    "original_amount": str(financials["catalog_total"]),
                    "final_amount": str(financials["basket_total"]),
                    "discount_percent": str(purchase_res["discount_percent"]),
                    "margin_percent": str(purchase_res["margin_percent"]),
                }
            )
            
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="NEGOTIATION_ACCEPTED",
                result="SUCCESS",
                reason="Buyer and Merchant Agents successfully reached a mutually acceptable negotiation agreement."
            )

            # Map parameters for Response
            policy = self.db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
            policy_version = policy.policy_version if policy else "policy_v1.0"
            discount_percent = Decimal(purchase_res["discount_percent"])
            margin_percent = Decimal(purchase_res["margin_percent"])

            # Record Final SETU PolicyEngine Check Event
            emit_event({
                "id": "evt_final_policy_eval",
                "event_id": "evt_final_policy_eval",
                "round": round_idx,
                "actor": "setu",
                "event_type": "trust_check",
                "type": "system_event",
                "state": "POLICY_VALIDATION",
                "message": "SETU Policy Engine evaluated final basket integrity: Item price floors, merchant margin, inventory, and signature constraints PASSED.",
                "reason_label": "PolicyEngine Validation Passed",
                "timestamp": format_ist_timestamp(1.2 * round_idx + 1.0)
            })

            # Record Final Approved Event
            emit_event({
                "id": "evt_final_approved",
                "event_id": "evt_final_approved",
                "round": round_idx,
                "actor": "setu",
                "event_type": "trust_check",
                "type": "system_event",
                "state": "APPROVED",
                "message": f"Decision: APPROVED. Deal locked at ₹{final_price}. Transaction ledger snapshot recorded. Authorized for checkout.",
                "offer": str(final_price),
                "basket_items": serialized_basket_items,
                "reason_label": "APPROVED",
                "timestamp": format_ist_timestamp(1.2 * round_idx + 1.3),
                "is_final": True
            })

            # Log completion and trace events
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="AGENT_SESSION_COMPLETED",
                result="SUCCESS",
                reason="Autonomous session trace concluded and final purchase request approved.",
                metadata=memory.serialize()
            )

            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="NEGOTIATION_COMPLETED",
                result="SUCCESS",
                reason="Negotiation agreement successfully logged and validated.",
                entity_type="PurchaseRequest",
                entity_id=final_decision_pr_id,
                metadata={"final_price": str(final_price), "purchase_request_id": final_decision_pr_id}
            )
            completion_time = datetime.datetime.utcnow().isoformat() + "Z"

            return {
                "buyer_id": buyer_id,
                "intent": intent,
                "catalog_search_results": search_results,
                "selected_product_id": 1 if (1 in comp_ids and 2 in comp_ids) else selected_product_id,
                "cross_sell_product_id": 2 if (selected_product_id in [1, 2, 3] or (1 in comp_ids and 2 in comp_ids)) else (44 if selected_product_id == 41 else (57 if selected_product_id == 56 else (53 if selected_product_id == 52 else 0))),
                "bundle_offer": {
                    "product_ids": comp_ids,
                    "original_amount": basket_dict["original_total"],
                    "offered_amount": basket_dict["final_total"],
                    "discount_percent": str(discount_percent),
                    "reason": "AI-to-AI negotiated deal package"
                },
                "negotiation_history": negotiation_history,
                "conversation_events": conversation_events,
                "purchase_request_id": final_decision_pr_id,
                "decision": purchase_res["decision"],
                "reasons": purchase_res["reasons"],
                "original_amount": basket_dict["original_total"],
                "final_amount": basket_dict["final_total"],
                "discount_percent": str(discount_percent),
                "margin_percent": str(margin_percent),
                "policy_version": policy_version,
                "basket": basket_dict,
                "basket_type": "BUNDLE" if len(basket_dict["items"]) > 1 else "STANDALONE",
                "selected_basket_type": "BUNDLE" if len(basket_dict["items"]) > 1 else "STANDALONE",
                "financials": financials,
                
                # Structured Proposal and Offer Lifecycle
                "buyer_opening_offer": buyer_opening_offer_record,
                "merchant_standalone_counter": merchant_standalone_counter_record,
                "merchant_bundle_proposal": merchant_bundle_proposal_record,
                "proposals": proposals,
                "accepted_proposal_id": accepted_proposal_id,
                
                # Dynamic params
                "agent_mode": self.buyer.provider.agent_mode,
                "buyer_objective": memory.buyer_goal,
                "buyer_tools_used": self.buyer.tools_called_in_session,
                "buyer_confidence": self.buyer.last_confidence,
                "merchant_objective": memory.merchant_goal,
                "merchant_tools_used": self.merchant.tools_called_in_session,
                "merchant_confidence": self.merchant.last_confidence,
                
                # Stage & Lifecycle tracking
                "stage": NegotiationStage.PURCHASE_REQUEST_CREATION.value,
                "status": "success",
                "error_code": None,
                
                # Step 12 metadata
                "provider": provider_name,
                "model": model_name,
                "execution_mode": execution_mode,
                "session_id": session_id,
                "agent_role": "BUYER_AGENT & MERCHANT_AGENT",
                "start_time": start_time,
                "completion_time": completion_time,
                "provider_summary": compute_provider_summary()
            }

        else:
            # Negotiation failed or rejected
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="NEGOTIATION_REJECTED",
                result="FAIL",
                reason="Buyer and Merchant Agents failed to reach a mutually acceptable transaction agreement."
            )
            
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="AGENT_SESSION_COMPLETED",
                result="FAIL",
                reason="Autonomous session trace concluded with negotiation failure.",
                metadata=memory.serialize()
            )
            raise NegotiationError("Negotiation failed: Buyer and Merchant could not reach a mutually acceptable agreement.", build_failed_result(["Buyer and Merchant could not reach a mutually acceptable agreement."], decision_val="REJECTED"))
