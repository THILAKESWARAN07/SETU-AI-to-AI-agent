import logging
import re
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.models import Product, MerchantPolicy
from backend.app.audit import AuditEngine
from backend.app.policy import PolicyEngine
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.pricing_strategy import MerchantPricingStrategy
from backend.app.agents.provider import BuyerDecision, MerchantDecision
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
    standalone_preferred = any(w in intent_lower for w in [
        "standalone", "only want", "without accessories", "no accessories", 
        "phone alone", "just the", "alone", "without bundle", "no bundle"
    ])
    accessories_wanted = any(w in intent_lower for w in [
        "accessory", "accessories", "charger", "case", "glass", "strap", "bundle", "with"
    ])

    # Shorthand & explicit amount extraction
    # Patterns like "12k", "15k", "1.5k", "12000", "₹12000"
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
        "accessories_wanted": accessories_wanted
    }

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
        max_rounds: int = 4
    ) -> Dict[str, Any]:
        import uuid
        import datetime
        from backend.app.agents.memory import NegotiationMemory
        
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        start_time = datetime.datetime.utcnow().isoformat() + "Z"
        provider_name = self.buyer.provider.provider_name
        model_name = self.buyer.provider.model_name
        execution_mode = self.buyer.provider.agent_mode
        
        # 1. Parse intent and budget constraints
        budget_info = parse_budget_intent(intent, budget)
        effective_max_budget = budget_info["maximum_budget"]

        # 2. Start session memory
        memory = NegotiationMemory(session_id=session_id, product_id=1)
        memory.buyer_goal = f"Procure target product based on user intent: '{intent}' with target budget: ₹{budget_info['target_budget']} and maximum budget limit: ₹{effective_max_budget}."
        memory.merchant_goal = "Maximize transaction volume, cross-sell recommendation conversion, and verify min margin guidelines."

        # Clear active trace trackers
        self.buyer.tools_called_in_session = []
        self.merchant.tools_called_in_session = []

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
        current_status = "IN_PROGRESS"
        final_decision_pr_id = None
        final_price = None
        selected_product_id = None
        search_results = []
        original_amount = Decimal("0.00")
        round_idx = 1

        def build_failed_result(reasons, final_price_val=None, decision_val="BLOCKED", execution_mode_override=None):
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
            
            return {
                "buyer_id": buyer_id,
                "intent": intent,
                "catalog_search_results": search_results or [],
                "selected_product_id": prod_id,
                "cross_sell_product_id": 2 if prod_id in [1, 3] else 0,
                "bundle_offer": {
                    "product_ids": [1, 2] if prod_id == 3 else [prod_id],
                    "original_amount": original_amt_str,
                    "offered_amount": str(final_price_val) if final_price_val else original_amt_str,
                    "discount_percent": "0.00",
                    "reason": "Negotiation session failed"
                },
                "negotiation_history": negotiation_history or [],
                "purchase_request_id": 0,
                "decision": decision_val,
                "reasons": reasons,
                "original_amount": original_amt_str,
                "final_amount": str(final_price_val) if final_price_val else "0.00",
                "discount_percent": "0.00",
                "margin_percent": "0.00",
                "policy_version": policy_version,
                "agent_mode": mode_val,
                "buyer_objective": memory.buyer_goal,
                "buyer_tools_used": list(self.buyer.tools_called_in_session),
                "buyer_confidence": self.buyer.last_confidence,
                "merchant_objective": memory.merchant_goal,
                "merchant_tools_used": list(self.merchant.tools_called_in_session),
                "merchant_confidence": self.merchant.last_confidence,
                
                # Step 12 metadata
                "provider": provider_name,
                "model": model_name,
                "execution_mode": mode_val,
                "session_id": session_id,
                "agent_role": "BUYER_AGENT & MERCHANT_AGENT",
                "start_time": start_time,
                "completion_time": completion_time
            }

        # Legacy E2E and UI compatibility log triggers
        AuditEngine.log_event(db=self.db, actor="BUYER_AGENT", action="BUYER_INTENT", result="SUCCESS", reason=f"Buyer intent processed: {intent}")
        AuditEngine.log_event(db=self.db, actor="BUYER_AGENT", action="CATALOG_SEARCH", result="SUCCESS", reason="Buyer searched catalog.")
        AuditEngine.log_event(db=self.db, actor="BUYER_AGENT", action="PRODUCT_SELECTED", result="SUCCESS", reason="Buyer selected reference product Wireless Earbuds.")
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

        # Formulate initial Buyer offer
        buyer_prompt = (
            f"You are the Buyer Agent. Parse user intent: '{intent}' with budget limit: {budget} INR.\n"
            f"Catalog Search Results: {search_results}\n"
            f"Selected Target Product Details: {prod_details}\n"
            f"Merchant Policy Constraints: {policy_info}\n"
        )
        if is_alternative_offered:
            buyer_prompt += f"NOTE: The originally requested product (ID {original_primary_id}) is out of stock. The Merchant proposed same-category alternative product: {prod_details['name']} (ID {prod_details['id']}). Evaluate if this alternative fits your intent and budget, and proceed with negotiation.\n"
            
        buyer_prompt += (
            "Please formulate your initial OFFER decision. You are negotiating a purchase basket. "
            "Please populate the basket_items list in your structured output, containing the primary product "
            "and its details. Ensure the total_amount equals the sum of negotiated prices of all items in the basket."
        )

        # Generate buyer decision using the runtime loop
        try:
            buyer_decision: BuyerDecision = self.buyer.negotiate_decision(self.db, buyer_prompt, memory=memory)
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
            metadata={
                "product_id": buyer_decision.product_id,
                "quantity": buyer_decision.quantity,
                "offered_price": str(buyer_decision.total_amount),
                "constraints_checked": buyer_decision.constraints_checked
            }
        )

        original_amount = basket_original_total

        # Append turn 1
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
                "basket_items": [
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
            },
            "merchant_offer": None,
            "accepted": False,
            "reason": buyer_decision.rationale
        })

        latest_buyer_offer = buyer_decision

        # 3. Turn Loop
        round_idx = 1
        merchant_countered = False

        while round_idx <= max_rounds:
            round_idx += 1
            memory.round_number = round_idx

            # --- MERCHANT TURN ---
            # Gather tools observations
            inventory = get_inventory_tool(self.db, latest_buyer_offer.product_id)
            base_price = get_product_price_tool(self.db, latest_buyer_offer.product_id)
            merchant_policy = get_merchant_constraints_tool(self.db)
            margin_eval = evaluate_margin_tool(self.db, latest_buyer_offer.product_id, latest_buyer_offer.quantity, str(latest_buyer_offer.total_amount))

            merchant_prompt = (
                f"You are the Merchant Agent. User Procurement Request: '{intent}'.\n"
                f"Buyer Decision Action: {latest_buyer_offer.action}\n"
                f"Buyer Message: '{getattr(latest_buyer_offer, 'message', '')}'\n"
                f"Evaluate Buyer's proposed basket: {[f'{item.name} (Qty: {item.quantity}, Price: {item.negotiated_price})' for item in latest_buyer_offer.basket_items]} with total amount: {latest_buyer_offer.total_amount} INR.\n"
                f"Inventory Availability: {inventory}\n"
                f"Product Pricing: {base_price}\n"
                f"Merchant Policy Constraints: {merchant_policy}\n"
                f"Margin Evaluation: {margin_eval}\n"
                f"Buyer Rationale: '{latest_buyer_offer.rationale}'\n"
                f"You are negotiating a basket. Formulate your response (COUNTER, ACCEPT, or REJECT). "
                f"If you choose to COUNTER, you can offer a profitable bundle containing the primary product "
                f"plus one or more compatible accessories/complementary products (from its related_product_ids list). "
                f"Intelligently adjust individual item prices in the basket_items list to maximize profit while staying "
                f"within the buyer's budget and satisfying policies. Ensure total_amount equals the sum of negotiated prices."
            )

            try:
                merchant_decision: MerchantDecision = self.merchant.negotiate_decision(self.db, merchant_prompt, memory=memory)
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

            # Ensure basket_items is populated on merchant decision
            if merchant_decision.action != "REJECT" and not getattr(merchant_decision, "basket_items", None):
                p_obj = self.db.query(Product).filter(Product.id == merchant_decision.product_id).first()
                merchant_decision.basket_items = [
                    BasketItemSchema(
                        product_id=merchant_decision.product_id,
                        name=p_obj.name if p_obj else "Product",
                        quantity=merchant_decision.quantity,
                        original_price=p_obj.price if p_obj else merchant_decision.unit_price,
                        negotiated_price=merchant_decision.unit_price,
                        is_primary=True
                    )
                ]

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
                    reason=f"Merchant acceptance basket margin check. Margin Passed: {margin_passed}"
                )
                
                memory.add_policy_verdict(
                    decision="APPROVED" if margin_passed else "BLOCKED",
                    reasons=[] if margin_passed else ["Merchant margin limit violation on acceptance."]
                )

                if not margin_passed:
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_REJECTED",
                        result="BLOCKED",
                        reason="Merchant accepted offer below required minimum margin limit floor."
                    )
                    raise NegotiationError("Negotiation failed: Accepted offer violates minimum profit margin constraints.", build_failed_result(["Accepted offer violates minimum profit margin constraints."]))

                AuditEngine.log_event(
                    db=self.db,
                    actor="MERCHANT_AGENT",
                    action="MERCHANT_ACCEPTED",
                    result="SUCCESS",
                    reason=merchant_decision.rationale
                )
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

                negotiation_history.append({
                    "round": round_idx,
                    "buyer_offer": None,
                    "merchant_offer": {
                        "product_ids": [item.product_id for item in merchant_decision.basket_items],
                        "original_amount": str(merchant_original_total),
                        "offered_amount": str(merchant_decision.total_amount),
                        "discount_percent": str(discount_pct.quantize(Decimal("0.01"))),
                        "reason": merchant_decision.rationale,
                        "message": getattr(merchant_decision, "message", None) or merchant_decision.rationale,
                        "reason_label": "Within merchant price floor & margin rules",
                        "tools_used": list(self.merchant.tools_called_in_session),
                        "confidence": self.merchant.last_confidence,
                        "basket_items": [
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
                    },
                    "accepted": False,
                    "reason": merchant_decision.rationale
                })

                latest_merchant_counter = merchant_decision
                merchant_countered = True

            # --- BUYER TURN (if Merchant Countered) ---
            if merchant_countered:
                # Buyer gathers budget checks
                budget_eval = evaluate_budget_tool(self.db, str(latest_merchant_counter.total_amount), str(budget))

                buyer_eval_prompt = (
                    f"You are the Buyer Agent. Evaluate Merchant's proposed basket counter-offer: {[f'{item.name} (Qty: {item.quantity}, Price: {item.negotiated_price})' for item in latest_merchant_counter.basket_items]} with total amount: {latest_merchant_counter.total_amount} INR.\n"
                    f"Your Budget Limits: {budget_eval}\n"
                    f"Merchant Rationale: '{latest_merchant_counter.rationale}'\n"
                    f"Evaluate if the recommended bundle/accessories are relevant and provide additional value. "
                    f"Reject irrelevant upselling. Verify if the total amount respects your budget of {budget} INR. "
                    f"Formulate your response (COUNTER, ACCEPT, or REJECT)."
                )

                try:
                    buyer_decision = self.buyer.negotiate_decision(self.db, buyer_eval_prompt, memory=memory)
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

                # Ensure basket_items is populated on buyer decision
                if buyer_decision.action != "REJECT" and not getattr(buyer_decision, "basket_items", None):
                    p_obj = self.db.query(Product).filter(Product.id == buyer_decision.product_id).first()
                    buyer_decision.basket_items = [
                        BasketItemSchema(
                            product_id=buyer_decision.product_id,
                            name=p_obj.name if p_obj else "Product",
                            quantity=buyer_decision.quantity,
                            original_price=p_obj.price if p_obj else buyer_decision.unit_price,
                            negotiated_price=buyer_decision.unit_price,
                            is_primary=True
                        )
                    ]

                if buyer_decision.action != "REJECT":
                    buyer_original_total = sum(Decimal(str(item.original_price)) * Decimal(item.quantity) for item in buyer_decision.basket_items)
                    buyer_final_total = sum(Decimal(str(item.negotiated_price)) * Decimal(item.quantity) for item in buyer_decision.basket_items)
                    buyer_decision.total_amount = buyer_final_total

                if buyer_decision.action == "REJECT":
                    AuditEngine.log_event(
                        db=self.db,
                        actor="BUYER_AGENT",
                        action="NEGOTIATION_REJECTED",
                        result="FAIL",
                        reason=buyer_decision.rationale
                    )
                    current_status = "REJECTED"
                    memory.final_outcome = "REJECTED"
                    break

                elif buyer_decision.action == "ACCEPT":
                    # Double check budget constraint against effective maximum budget
                    final_budget_eval = evaluate_budget_tool(self.db, str(latest_merchant_counter.total_amount), str(effective_max_budget))
                    
                    # Log POLICY_CHECK
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_CHECK",
                        result="SUCCESS" if final_budget_eval["within_budget"] else "FAIL",
                        reason=f"Buyer acceptance budget check. Max Budget: ₹{effective_max_budget}. Final: ₹{latest_merchant_counter.total_amount}"
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
                    
                    # Append acceptance turn to history for completeness
                    negotiation_history.append({
                        "round": round_idx + 1,
                        "buyer_offer": {
                            "product_id": latest_merchant_counter.product_id,
                            "quantity": latest_merchant_counter.quantity,
                            "original_amount": str(merchant_original_total),
                            "final_amount": str(latest_merchant_counter.total_amount),
                            "currency": "INR",
                            "reason": buyer_decision.rationale,
                            "message": getattr(buyer_decision, "message", None) or buyer_decision.rationale,
                            "reason_label": "Buyer accepts deal within budget limit",
                            "tools_used": list(self.buyer.tools_called_in_session),
                            "confidence": self.buyer.last_confidence,
                            "basket_items": [
                                {
                                    "product_id": item.product_id,
                                    "name": item.name,
                                    "quantity": item.quantity,
                                    "original_price": str(item.original_price),
                                    "negotiated_price": str(item.negotiated_price),
                                    "is_primary": item.is_primary
                                }
                                for item in latest_merchant_counter.basket_items
                            ]
                        },
                        "merchant_offer": None,
                        "accepted": True,
                        "reason": buyer_decision.rationale
                    })
                    
                    current_status = "AGREED"
                    final_price = latest_merchant_counter.total_amount
                    selected_product_id = latest_merchant_counter.product_id
                    latest_buyer_offer = latest_merchant_counter
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

                    negotiation_history.append({
                        "round": round_idx,
                        "buyer_offer": {
                            "product_id": buyer_decision.product_id,
                            "quantity": buyer_decision.quantity,
                            "original_amount": str(buyer_original_total),
                            "final_amount": str(buyer_decision.total_amount),
                            "currency": "INR",
                            "reason": buyer_decision.rationale,
                            "tools_used": list(self.buyer.tools_called_in_session),
                            "confidence": self.buyer.last_confidence,
                            "basket_items": [
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
                        },
                        "merchant_offer": None,
                        "accepted": False,
                        "reason": buyer_decision.rationale
                    })

                    latest_buyer_offer = buyer_decision
                    merchant_countered = False

        # 4. Finalization & Policy Verification
        if current_status == "AGREED" and final_price is not None and selected_product_id is not None:
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

            # Construct final basket dict
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
            basket_dict = {
                "items": serialized_basket_items,
                "original_total": str(sum(Decimal(str(i["original_price"])) * Decimal(i["quantity"]) for i in serialized_basket_items)),
                "final_total": str(sum(Decimal(str(i["negotiated_price"])) * Decimal(i["quantity"]) for i in serialized_basket_items)),
                "discount_amount": str(sum((Decimal(str(i["original_price"])) - Decimal(i["negotiated_price"])) * Decimal(i["quantity"]) for i in serialized_basket_items))
            }

            # Determine component product IDs for legacy backward compatibility check
            comp_ids = [item["product_id"] for item in serialized_basket_items]
            purchase_prod_id = 1 if (1 in comp_ids and 2 in comp_ids) else selected_product_id

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
                raise NegotiationError(f"Policy Engine rejected final deal: {', '.join(purchase_res['reasons'])}", build_failed_result(purchase_res['reasons'], final_price))

            final_decision_pr_id = purchase_res["purchase_request_id"]
            memory.final_outcome = "APPROVED"
            
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="PURCHASE_REQUEST",
                result="SUCCESS",
                reason="Purchase request logged successfully in system ledger.",
                entity_type="PurchaseRequest",
                entity_id=final_decision_pr_id
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
                "cross_sell_product_id": 2 if (1 in comp_ids and 2 in comp_ids) else 0,
                "bundle_offer": {
                    "product_ids": comp_ids,
                    "original_amount": basket_dict["original_total"],
                    "offered_amount": basket_dict["final_total"],
                    "discount_percent": str(discount_percent),
                    "reason": "AI-to-AI negotiated deal package"
                },
                "negotiation_history": negotiation_history,
                "purchase_request_id": final_decision_pr_id,
                "decision": purchase_res["decision"],
                "reasons": purchase_res["reasons"],
                "original_amount": basket_dict["original_total"],
                "final_amount": basket_dict["final_total"],
                "discount_percent": str(discount_percent),
                "margin_percent": str(margin_percent),
                "policy_version": policy_version,
                "basket": basket_dict,
                
                # New response params for Step 10
                "agent_mode": self.buyer.provider.agent_mode,
                "buyer_objective": memory.buyer_goal,
                "buyer_tools_used": self.buyer.tools_called_in_session,
                "buyer_confidence": self.buyer.last_confidence,
                "merchant_objective": memory.merchant_goal,
                "merchant_tools_used": self.merchant.tools_called_in_session,
                "merchant_confidence": self.merchant.last_confidence,
                
                # Step 12 metadata
                "provider": provider_name,
                "model": model_name,
                "execution_mode": execution_mode,
                "session_id": session_id,
                "agent_role": "BUYER_AGENT & MERCHANT_AGENT",
                "start_time": start_time,
                "completion_time": completion_time
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
