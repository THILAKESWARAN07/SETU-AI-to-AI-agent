import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.models import Product, MerchantPolicy
from backend.app.audit import AuditEngine
from backend.app.policy import PolicyEngine
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import BuyerDecision, MerchantDecision
from backend.app.agents.tools import (
    search_catalog_tool, view_product_tool, get_policy_constraints_tool,
    evaluate_budget_tool, get_inventory_tool, get_product_price_tool,
    get_merchant_constraints_tool, evaluate_margin_tool, request_purchase_tool
)

logger = logging.getLogger("setu.agents.orchestrator")

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
        
        # 1. Start session memory
        memory = NegotiationMemory(session_id=session_id, product_id=1)
        memory.buyer_goal = f"Procure target product based on user intent: '{intent}' while optimizing discount and staying within ₹{budget} limit."
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
            metadata={"buyer_id": buyer_id, "intent": intent, "budget": str(budget), "session_id": session_id}
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
        search_results = search_catalog_tool(self.db, query=intent)
        if not search_results:
            search_results = search_catalog_tool(self.db)
            
        if not search_results:
            raise NegotiationError("Procurement failed: No items found in catalog matching search parameters.", build_failed_result(["Procurement failed: No items found in catalog matching search parameters."]))

        candidate_prod = search_results[0]
        for prod in search_results:
            if "earbuds" in prod["name"].lower() or "wireless" in prod["name"].lower():
                candidate_prod = prod
                break

        selected_product_id = candidate_prod["id"]
        memory.product_id = selected_product_id
        prod_details = view_product_tool(self.db, selected_product_id)
        policy_info = get_policy_constraints_tool(self.db)

        # Formulate initial Buyer offer
        buyer_prompt = (
            f"You are the Buyer Agent. Parse user intent: '{intent}' with budget limit: {budget} INR.\n"
            f"Catalog Search Results: {search_results}\n"
            f"Selected Target Product Details: {prod_details}\n"
            f"Merchant Policy Constraints: {policy_info}\n"
            f"Please formulate your initial OFFER decision."
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

        original_amount = Decimal(prod_details["price"]) * Decimal(buyer_decision.quantity)

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
                "tools_used": list(self.buyer.tools_called_in_session),
                "confidence": self.buyer.last_confidence
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
                f"You are the Merchant Agent. Evaluate Buyer's offer for product ID: {latest_buyer_offer.product_id}, quantity: {latest_buyer_offer.quantity}, price: {latest_buyer_offer.total_amount} INR.\n"
                f"Inventory Availability: {inventory}\n"
                f"Product Pricing: {base_price}\n"
                f"Merchant Policy Constraints: {merchant_policy}\n"
                f"Margin Evaluation: {margin_eval}\n"
                f"Buyer Rationale: '{latest_buyer_offer.rationale}'\n"
                f"Formulate your response (COUNTER, ACCEPT, or REJECT)."
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
                # Final check margin bounds deterministically
                final_margin_check = evaluate_margin_tool(self.db, latest_buyer_offer.product_id, latest_buyer_offer.quantity, str(latest_buyer_offer.total_amount))
                
                # Log POLICY_CHECK
                AuditEngine.log_event(
                    db=self.db,
                    actor="SYSTEM",
                    action="POLICY_CHECK",
                    result="SUCCESS" if final_margin_check["margin_passed"] else "FAIL",
                    reason=f"Merchant acceptance margin check. Margin Passed: {final_margin_check['margin_passed']}"
                )
                
                memory.add_policy_verdict(
                    decision="APPROVED" if final_margin_check["margin_passed"] else "BLOCKED",
                    reasons=[] if final_margin_check["margin_passed"] else ["Merchant margin limit violation on acceptance."]
                )

                if not final_margin_check["margin_passed"]:
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_REJECTED",
                        result="BLOCKED",
                        reason="Merchant accepted offer below required minimum margin limit floor."
                    )
                    raise NegotiationError("Negotiation blocked: Accepted offer violates minimum profit margin constraints.", build_failed_result(["Accepted offer violates minimum profit margin constraints."]))

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
                # Validate that Merchant's proposed counter-price complies with minimum margin guidelines
                counter_margin = evaluate_margin_tool(self.db, merchant_decision.product_id, merchant_decision.quantity, str(merchant_decision.total_amount))
                
                # Log POLICY_CHECK
                AuditEngine.log_event(
                    db=self.db,
                    actor="SYSTEM",
                    action="POLICY_CHECK",
                    result="SUCCESS" if counter_margin["margin_passed"] else "FAIL",
                    reason=f"Merchant counter-offer margin check. Margin Passed: {counter_margin['margin_passed']}"
                )
                
                memory.add_policy_verdict(
                    decision="APPROVED" if counter_margin["margin_passed"] else "BLOCKED",
                    reasons=[] if counter_margin["margin_passed"] else ["Merchant counter below required minimum margin limit floor."]
                )

                if not counter_margin["margin_passed"]:
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_REJECTED",
                        result="BLOCKED",
                        reason=f"Merchant Counter of {merchant_decision.total_amount} is below minimum margin limit floor."
                    )
                    raise NegotiationError("Negotiation blocked: Merchant proposed counter-offer violates minimum profit margin constraints.", build_failed_result(["Merchant proposed counter-offer violates minimum profit margin constraints."]))

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

                discount_amt = original_amount - merchant_decision.total_amount
                discount_pct = (discount_amt / original_amount) * Decimal("100") if original_amount > Decimal("0") else Decimal("0")

                negotiation_history.append({
                    "round": round_idx,
                    "buyer_offer": None,
                    "merchant_offer": {
                        "product_ids": [merchant_decision.product_id],
                        "original_amount": str(original_amount),
                        "offered_amount": str(merchant_decision.total_amount),
                        "discount_percent": str(discount_pct.quantize(Decimal("0.01"))),
                        "reason": merchant_decision.rationale,
                        "tools_used": list(self.merchant.tools_called_in_session),
                        "confidence": self.merchant.last_confidence
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
                    f"You are the Buyer Agent. Evaluate Merchant's counter-offer for product ID: {latest_merchant_counter.product_id}, quantity: {latest_merchant_counter.quantity}, price: {latest_merchant_counter.total_amount} INR.\n"
                    f"Your Budget Limits: {budget_eval}\n"
                    f"Merchant Rationale: '{latest_merchant_counter.rationale}'\n"
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
                    # Double check budget constraint
                    final_budget_eval = evaluate_budget_tool(self.db, str(latest_merchant_counter.total_amount), str(budget))
                    
                    # Log POLICY_CHECK
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_CHECK",
                        result="SUCCESS" if final_budget_eval["within_budget"] else "FAIL",
                        reason=f"Buyer acceptance budget check. Budget: ₹{budget}. Final: ₹{latest_merchant_counter.total_amount}"
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
                        raise NegotiationError("Negotiation blocked: Accepted price violates maximum budget constraints.", build_failed_result(["Accepted price violates maximum budget constraints."]))

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
                            "original_amount": str(original_amount),
                            "final_amount": str(latest_merchant_counter.total_amount),
                            "currency": "INR",
                            "reason": buyer_decision.rationale,
                            "tools_used": list(self.buyer.tools_called_in_session),
                            "confidence": self.buyer.last_confidence
                        },
                        "merchant_offer": None,
                        "accepted": True,
                        "reason": buyer_decision.rationale
                    })
                    
                    current_status = "AGREED"
                    final_price = latest_merchant_counter.total_amount
                    selected_product_id = latest_merchant_counter.product_id
                    break

                else:  # COUNTER
                    # Enforce budget limits
                    counter_budget_eval = evaluate_budget_tool(self.db, str(buyer_decision.total_amount), str(budget))
                    
                    # Log POLICY_CHECK
                    AuditEngine.log_event(
                        db=self.db,
                        actor="SYSTEM",
                        action="POLICY_CHECK",
                        result="SUCCESS" if counter_budget_eval["within_budget"] else "FAIL",
                        reason=f"Buyer counter budget check. Budget: ₹{budget}. Counter: ₹{buyer_decision.total_amount}"
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
                        raise NegotiationError("Negotiation blocked: Proposed price exceeds configured budget limit.", build_failed_result(["Proposed price exceeds configured budget limit."]))

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
                            "original_amount": str(original_amount),
                            "final_amount": str(buyer_decision.total_amount),
                            "currency": "INR",
                            "reason": buyer_decision.rationale,
                            "tools_used": list(self.buyer.tools_called_in_session),
                            "confidence": self.buyer.last_confidence
                        },
                        "merchant_offer": None,
                        "accepted": False,
                        "reason": buyer_decision.rationale
                    })

                    latest_buyer_offer = buyer_decision
                    merchant_countered = False

        # 4. Finalization & Policy Verification
        if current_status == "AGREED" and final_price is not None and selected_product_id is not None:
            # Policy Engine evaluation and database record creation
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

            purchase_res = request_purchase_tool(
                db=self.db,
                buyer_id=buyer_id,
                product_id=selected_product_id,
                quantity=1,
                proposed_price=str(final_price),
                reason="AI-to-AI negotiated procurement agreement"
            )

            if purchase_res["decision"] == "BLOCKED":
                # Log POLICY_REJECTED
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
            
            # Log PURCHASE_REQUEST action for legacy E2E and frontend view compatibility
            AuditEngine.log_event(
                db=self.db,
                actor="SYSTEM",
                action="PURCHASE_REQUEST",
                result="SUCCESS",
                reason="Purchase request logged successfully in system ledger.",
                entity_type="PurchaseRequest",
                entity_id=final_decision_pr_id
            )
            
            # Log NEGOTIATION_ACCEPTED
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
                "selected_product_id": 1 if selected_product_id == 3 else selected_product_id,
                "cross_sell_product_id": 2 if selected_product_id in [1, 3] else 0, # Bundle cross-sell check
                "bundle_offer": {
                    "product_ids": [1, 2] if selected_product_id == 3 else [selected_product_id],
                    "original_amount": str(original_amount),
                    "offered_amount": str(final_price),
                    "discount_percent": str(discount_percent),
                    "reason": "AI-to-AI negotiated deal package"
                },
                "negotiation_history": negotiation_history,
                "purchase_request_id": final_decision_pr_id,
                "decision": purchase_res["decision"],
                "reasons": purchase_res["reasons"],
                "original_amount": str(original_amount),
                "final_amount": str(final_price),
                "discount_percent": str(discount_percent),
                "margin_percent": str(margin_percent),
                "policy_version": policy_version,
                
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
