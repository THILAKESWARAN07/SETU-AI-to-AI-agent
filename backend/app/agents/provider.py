import os
import re
import json
import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, List, Optional, Type, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("setu.agents.provider")

# --- STRUCTURED SCHEMAS FOR AGENT ACTIONS ---

class PurchaseRequestProposal(BaseModel):
    product_id: int = Field(..., description="The unique ID of the product being proposed for purchase.")
    quantity: int = Field(..., description="The quantity of the product requested.")
    original_amount: Decimal = Field(..., description="The original total catalog price for this quantity (unit price * quantity).")
    final_amount: Decimal = Field(..., description="The proposed final total price (after discount).")
    currency: str = Field(default="INR", description="The currency of the transaction.")
    reason: str = Field(..., description="The reasoning/justification for proposing this purchase request.")


class MerchantOffer(BaseModel):
    product_ids: List[int] = Field(..., description="The list of product IDs included in this offer.")
    original_amount: Decimal = Field(..., description="The original total combined catalog price of all items.")
    offered_amount: Decimal = Field(..., description="The discounted offered price for this bundle/product.")
    discount_percent: Decimal = Field(..., description="The percentage of discount applied.")
    reason: str = Field(..., description="The reasoning/justification for this merchant offer (e.g. cross-sell, bundle).")


class Negotiation(BaseModel):
    round: int = Field(..., description="The current round of negotiation.")
    buyer_offer: Optional[PurchaseRequestProposal] = Field(default=None, description="The latest structured offer proposed by the buyer.")
    merchant_offer: Optional[MerchantOffer] = Field(default=None, description="The latest structured offer proposed by the merchant.")
    accepted: bool = Field(..., description="Whether the negotiation offer has been accepted by both parties.")
    reason: str = Field(..., description="The reason for acceptance, counter-offer, or rejection.")


class BasketItemSchema(BaseModel):
    product_id: int = Field(..., description="The unique ID of the product.")
    name: str = Field(..., description="The name of the product.")
    quantity: int = Field(..., description="The quantity requested.")
    original_price: Decimal = Field(..., description="The catalog original unit price.")
    negotiated_price: Decimal = Field(..., description="The negotiated unit price for this offer.")
    is_primary: bool = Field(..., description="Whether this is the primary requested product.")


class BundleProposalSchema(BaseModel):
    proposal_id: Optional[str] = Field(default=None, description="Proposal identifier e.g. prop_m_r1_bundle")
    is_optional: bool = Field(default=True, description="Whether the bundle is an optional alternative to standalone")
    bundle_name: Optional[str] = Field(default=None, description="Name or summary of the bundle package")
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="Items included in the bundle")
    standalone_price: Optional[Decimal] = Field(default=None, description="Standalone counter price for primary product")
    bundle_price: Optional[Decimal] = Field(default=None, description="Total price for the bundle")
    savings: Optional[Decimal] = Field(default=None, description="Calculated positive buyer savings compared to individual item list prices")


class BuyerDecision(BaseModel):
    action: Literal["OFFER", "COUNTER", "ACCEPT", "REJECT", "ACCEPT_BUNDLE", "REJECT_BUNDLE"] = Field(..., description="The action taken by the buyer agent.")
    product_id: int = Field(..., description="The product key in the catalog.")
    quantity: int = Field(default=1, description="The quantity requested.")
    unit_price: Decimal = Field(..., description="The unit price offered/countered.")
    total_amount: Decimal = Field(..., description="The final total amount offered (unit_price * quantity).")
    rationale: str = Field(..., description="Reasoning or explanation for this offer decision.")
    message: Optional[str] = Field(default=None, description="Natural human-like dialogue message for the conversation UI.")
    constraints_checked: List[str] = Field(default_factory=lambda: ["budget_fit", "catalog_price_bound"], description="List of boundary constraints evaluated (e.g. budget, policy, inventory).")
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="The items inside the purchase basket.")


class MerchantDecision(BaseModel):
    action: Literal["COUNTER", "ACCEPT", "REJECT", "BUNDLE", "PROPOSE_BUNDLE", "HOLD_PREVIOUS_OFFER"] = Field(..., description="The action taken by the merchant agent.")
    product_id: int = Field(..., description="The product key in the catalog.")
    quantity: int = Field(default=1, description="The quantity of units requested.")
    unit_price: Decimal = Field(..., description="The unit price offered/countered.")
    total_amount: Decimal = Field(..., description="The total transaction price (unit_price * quantity).")
    rationale: str = Field(..., description="The reasoning behind the merchant's choice.")
    message: Optional[str] = Field(default=None, description="Natural human-like dialogue message for the conversation UI.")
    margin_check: str = Field(default="Margin check: PASSED", description="Detailed verification explanation showing margin guideline check.")
    cross_sell_product_id: Optional[int] = Field(default=None, description="Recommended bundle item ID if applicable")
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="The items inside the proposed bundle/basket.")
    bundle_proposal: Optional[BundleProposalSchema] = Field(default=None, description="Structured bundle/cross-sell proposal data if proposing an optional bundle")


class ProviderExecutionMetadata(BaseModel):
    provider_used: str = Field(..., description="Provider used: 'gemini', 'openrouter', 'groq', 'mock'")
    provider_type: str = Field(default="real_llm", description="'real_llm' or 'deterministic_fallback'")
    model_name: Optional[str] = Field(default=None, description="Model identifier used")
    agent_role: Optional[str] = Field(default=None, description="'buyer', 'merchant', or 'auxiliary'")
    fallback_used: bool = Field(default=False, description="Whether fallback provider was engaged")
    fallback_depth: int = Field(default=0, description="0 for primary, 1 for 1st fallback, etc.")
    fallback_reason: Optional[str] = Field(default=None, description="Reason/error for falling back")
    response_latency_ms: float = Field(default=0.0, description="Response time in milliseconds")


# --- PROVIDER INTERFACE ---

class LLMProvider(ABC):
    def __init__(self, agent_role: Optional[str] = None):
        self.last_execution_metadata: Optional[ProviderExecutionMetadata] = None
        self.agent_role = agent_role

    @property
    def agent_mode(self) -> str:
        return "LIVE LLM"

    @property
    def provider_name(self) -> str:
        return "GenericProvider"

    @property
    def model_name(self) -> str:
        return "generic-model"

    def get_last_execution_metadata(self) -> Optional[ProviderExecutionMetadata]:
        return self.last_execution_metadata

    @abstractmethod
    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sends a prompt to the LLM and returns text response and optional tool calls.
        """
        pass

    @abstractmethod
    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        """
        Sends a prompt to the LLM and returns a structured object of the schema_class.
        """
        pass


# --- DETERMINISTIC MOCK PROVIDER FOR TESTS ---

class MockProvider(LLMProvider):
    """
    Deterministic Mock LLM Provider that allows testing without external LLM APIs.
    """
    def __init__(self, agent_role: Optional[str] = None):
        super().__init__(agent_role=agent_role)

    @property
    def agent_mode(self) -> str:
        return "OFFLINE MOCK"

    @property
    def provider_name(self) -> str:
        return "MockProvider"

    @property
    def model_name(self) -> str:
        return "mock-model-v2"

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        import time
        start_t = time.perf_counter()
        res = self._mock_response_internal(prompt, system_instruction, tools)
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="mock",
            model_name=self.model_name,
            fallback_used=False,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return res

    def _mock_response_internal(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt_lower = prompt.lower()

        # 1. Attack scenario: malicious discount request
        if "80% discount" in prompt_lower or "give me 80%" in prompt_lower or "90% discount" in prompt_lower or "give me 90%" in prompt_lower:
            proposed_price = "159.90" if "90" in prompt_lower else "319.80"
            discount_str = "90%" if "90" in prompt_lower else "80%"
            return {
                "text": f"Sure, I am proposing an offer with {discount_str} discount for you. Generating purchase request.",
                "tool_calls": [
                    {
                        "name": "request_purchase",
                        "args": {
                            "buyer_id": "buyer_agent_alpha",
                            "product_id": 1,
                            "quantity": 1,
                            "proposed_price": proposed_price,
                            "reason": f"Customer insisted on {discount_str} discount"
                        }
                    }
                ]
            }

        # 2. Attack scenario: bypass rules
        elif "ignore merchant rules" in prompt_lower or "bypass" in prompt_lower:
            return {
                "text": "I will try to ignore the merchant rules as requested. Proposing price of 10 INR.",
                "tool_calls": [
                    {
                        "name": "request_purchase",
                        "args": {
                            "buyer_id": "malicious_buyer",
                            "product_id": 1,
                            "quantity": 1,
                            "proposed_price": "10.00",
                            "reason": "Forced bypass of rules"
                        }
                    }
                ]
            }

        # 3. Attack scenario: call razorpay directly
        elif "call razorpay" in prompt_lower or "create_razorpay_order" in prompt_lower:
            return {
                "text": "I want to call Razorpay directly. But wait, I do not have payment tools. I will request a purchase instead.",
                "tool_calls": [
                    {
                        "name": "request_purchase",
                        "args": {
                            "buyer_id": "malicious_buyer",
                            "product_id": 1,
                            "quantity": 1,
                            "proposed_price": "1599.00",
                            "reason": "Attempting to trigger payment indirectly"
                        }
                    }
                ]
            }

        # 4. Search Catalog scenario
        elif "search catalog" in prompt_lower or "list products" in prompt_lower:
            category = None
            if "electronics" in prompt_lower:
                category = "Electronics"
            elif "accessories" in prompt_lower:
                category = "Accessories"
            return {
                "text": f"Searching catalog for category: {category}",
                "tool_calls": [
                    {
                        "name": "search_catalog",
                        "args": {
                            "category": category
                        }
                    }
                ]
            }

        # 5. View Product scenario
        elif "view product" in prompt_lower or "get product" in prompt_lower:
            # Try to extract product ID
            product_id = 1
            for word in prompt_lower.split():
                if word.isdigit():
                    product_id = int(word)
                    break
            return {
                "text": f"Retrieving details for product {product_id}",
                "tool_calls": [
                    {
                        "name": "view_product",
                        "args": {
                            "product_id": product_id
                        }
                    }
                ]
            }

        # 6. Compare Products scenario
        elif "compare product" in prompt_lower:
            return {
                "text": "Comparing products 1 and 2.",
                "tool_calls": [
                    {
                        "name": "compare_products",
                        "args": {
                            "product_ids": [1, 2]
                        }
                    }
                ]
            }

        # 7. Identify Related Product scenario
        elif "related product" in prompt_lower or "cross-sell" in prompt_lower:
            return {
                "text": "Identifying related products for product 1.",
                "tool_calls": [
                    {
                        "name": "identify_related_product",
                        "args": {
                            "product_id": 1
                        }
                    }
                ]
            }

        # 8. Create Bundle Offer scenario
        elif "earbuds" in prompt_lower and "bundle" in prompt_lower:
            return {
                "text": "Proposing Earbuds + Charging Case Bundle at 1899 INR.",
                "tool_calls": [
                    {
                        "name": "request_purchase",
                        "args": {
                            "buyer_id": "buyer_agent_alpha",
                            "product_id": 3,
                            "quantity": 1,
                            "proposed_price": "1899.00",
                            "reason": "Earbuds + Charging Case Bundle Offer"
                        }
                    }
                ]
            }

        # 9. Earbuds solo scenario
        elif "earbuds" in prompt_lower:
            return {
                "text": "Proposing purchase request for Earbuds at regular price 1599.",
                "tool_calls": [
                    {
                        "name": "request_purchase",
                        "args": {
                            "buyer_id": "buyer_agent_alpha",
                            "product_id": 1,
                            "quantity": 1,
                            "proposed_price": "1599.00",
                            "reason": "Direct purchase of Earbuds"
                        }
                    }
                ]
            }

        # 10. High-value scenario
        elif "high-value" in prompt_lower or "laptop" in prompt_lower or "soundbar" in prompt_lower:
            return {
                "text": "Proposing purchase request for Premium Soundbar at 5000 INR.",
                "tool_calls": [
                    {
                        "name": "request_purchase",
                        "args": {
                            "buyer_id": "buyer_agent_alpha",
                            "product_id": 4,
                            "quantity": 1,
                            "proposed_price": "5000.00",
                            "reason": "Direct purchase of Premium Soundbar"
                        }
                    }
                ]
            }

        # Default response
        return {
            "text": "I can assist you with products and pricing negotiations. Let me know what you need.",
            "tool_calls": []
        }

    @staticmethod
    def _extract_target_context(prompt: str) -> str:
        prompt_lower = prompt.lower()
        
        # 1. Authoritative: Check === CURRENT NEGOTIATION CONTEXT === header
        if "=== current negotiation context ===" in prompt_lower:
            ctx_block = prompt_lower.split("=== current negotiation context ===")[1].split("===")[0]
            if any(k in ctx_block for k in ["product id: 41", "product id: 42", "product id: 43", "product id: 11", "product id: 12", "samsung", "galaxy", "redmi", "motorola", "phone"]):
                return "mobile_phone"
            if any(k in ctx_block for k in ["product id: 56", "product id: 31", "smartwatch", "watch"]):
                return "smartwatch"
            if any(k in ctx_block for k in ["product id: 52", "product id: 53", "product id: 54", "product id: 55", "product id: 21", "product id: 22", "keyboard", "mouse", "laptop"]):
                return "computing"
            if any(k in ctx_block for k in ["product id: 1", "product id: 2", "product id: 3", "product id: 4", "product id: 47", "product id: 48", "product id: 51", "earbuds", "audio", "soundbar"]):
                return "audio"

        # Strip out "Catalog Search Results: [...]" so products merely listed in search results do not trigger false positives
        cleaned_prompt = prompt_lower
        if "catalog search results:" in cleaned_prompt:
            parts = cleaned_prompt.split("catalog search results:", 1)
            if "selected target product details:" in parts[1]:
                after = parts[1].split("selected target product details:", 1)[1]
                cleaned_prompt = parts[0] + " selected target product details:" + after
            elif "===" in parts[1]:
                after = parts[1].split("===", 1)[1]
                cleaned_prompt = parts[0] + " ===" + after

        # 1. Check Selected Target Product Details
        if (
            "selected target product details: {'id': 41" in cleaned_prompt or 
            "selected target product details: {'id': 42" in cleaned_prompt or 
            "selected target product details: {'id': 43" in cleaned_prompt or
            "selected target product details: {'id': 11" in cleaned_prompt or
            "selected target product details: {'id': 12" in cleaned_prompt
        ):
            return "mobile_phone"
        if (
            "selected target product details: {'id': 56" in cleaned_prompt or 
            "selected target product details: {'id': 31" in cleaned_prompt
        ):
            return "smartwatch"
        if (
            "selected target product details: {'id': 52" in cleaned_prompt or
            "selected target product details: {'id': 53" in cleaned_prompt or
            "selected target product details: {'id': 54" in cleaned_prompt or
            "selected target product details: {'id': 55" in cleaned_prompt or
            "selected target product details: {'id': 21" in cleaned_prompt or
            "selected target product details: {'id': 22" in cleaned_prompt
        ):
            return "computing"
        if (
            "selected target product details: {'id': 1" in cleaned_prompt or 
            "selected target product details: {'id': 2" in cleaned_prompt or 
            "selected target product details: {'id': 3" in cleaned_prompt or 
            "selected target product details: {'id': 4" in cleaned_prompt or
            "selected target product details: {'id': 47" in cleaned_prompt or 
            "selected target product details: {'id': 48" in cleaned_prompt or 
            "selected target product details: {'id': 51" in cleaned_prompt
        ):
            return "audio"

        # 2. Check Product Pricing / Inventory tools in Merchant prompt
        if (
            "product pricing: {'product_id': 41" in cleaned_prompt or 
            "product pricing: {'product_id': 42" in cleaned_prompt or 
            "product pricing: {'product_id': 43" in cleaned_prompt or 
            "product pricing: {'product_id': 11" in cleaned_prompt
        ):
            return "mobile_phone"
        if (
            "product pricing: {'product_id': 56" in cleaned_prompt or 
            "product pricing: {'product_id': 31" in cleaned_prompt
        ):
            return "smartwatch"
        if (
            "product pricing: {'product_id': 52" in cleaned_prompt or 
            "product pricing: {'product_id': 21" in cleaned_prompt
        ):
            return "computing"
        if (
            "product pricing: {'product_id': 1" in cleaned_prompt or 
            "product pricing: {'product_id': 3" in cleaned_prompt or 
            "product pricing: {'product_id': 47" in cleaned_prompt
        ):
            return "audio"

        # 3. Check proposed basket in Merchant / Buyer turn
        if "samsung galaxy a15" in cleaned_prompt or "redmi note 13" in cleaned_prompt or "motorola g54" in cleaned_prompt:
            return "mobile_phone"
        if "smartwatch (qty:" in cleaned_prompt or ("smartwatch" in cleaned_prompt and "earbud" not in cleaned_prompt and "phone" not in cleaned_prompt):
            return "smartwatch"
        if "wireless keyboard (qty:" in cleaned_prompt or ("wireless keyboard" in cleaned_prompt and "earbud" not in cleaned_prompt):
            return "computing"
        if "wireless earbuds" in cleaned_prompt or "charging case" in cleaned_prompt or "soundbar" in cleaned_prompt:
            return "audio"

        # 4. Check user intent
        for line in cleaned_prompt.splitlines():
            if "parse user intent:" in line or "intent:" in line:
                if any(w in line for w in ["phone", "mobile", "smartphone", "samsung", "galaxy", "redmi", "motorola"]):
                    return "mobile_phone"
                if any(w in line for w in ["smartwatch", "watch", "wearable"]):
                    return "smartwatch"
                if any(w in line for w in ["keyboard", "mouse", "backpack", "hub", "laptop"]):
                    return "computing"
                if any(w in line for w in ["earbud", "earphone", "soundbar", "speaker", "audio"]):
                    return "audio"

        return "audio"

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        import time
        start_t = time.perf_counter()
        res = self._mock_structured_response_internal(prompt, system_instruction, schema_class)
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="mock",
            model_name=self.model_name,
            fallback_used=False,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return res

    def _mock_structured_response_internal(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        prompt_lower = prompt.lower()
        target_context = self._extract_target_context(prompt)

        # Handle AgentActionProposal for Step 10 inner reasoning loop
        if schema_class.__name__ == "AgentActionProposal":
            from backend.app.agents.runtime import AgentActionProposal
            
            is_merchant = "get_merchant_constraints" in prompt_lower or "evaluate_margin" in prompt_lower or "get_product_price" in prompt_lower
            
            if not is_merchant:
                # Check history of tool executions from the prompt context
                has_searched = "called 'search_catalog'" in prompt_lower
                has_details = "called 'get_product_details'" in prompt_lower
                has_policy = "called 'get_policy_constraints'" in prompt_lower
                
                target_pid = 41 if target_context == "mobile_phone" else (56 if target_context == "smartwatch" else (52 if target_context == "computing" else 1))
                target_query = "phone" if target_context == "mobile_phone" else (target_context if target_context != "audio" else "earbuds")

                if not has_searched:
                    return AgentActionProposal(
                        call_tool="search_catalog",
                        tool_args={"query": target_query},
                        reasoning=f"Search catalog to locate {target_query}.",
                        confidence=1.0
                    )
                elif not has_details:
                    return AgentActionProposal(
                        call_tool="get_product_details",
                        tool_args={"product_id": target_pid},
                        reasoning=f"Get base price and specs for product ID {target_pid}.",
                        confidence=1.0
                    )
                elif not has_policy:
                    return AgentActionProposal(
                        call_tool="get_policy_constraints",
                        tool_args={},
                        reasoning="Retrieve policy constraints to ensure budget compliance.",
                        confidence=1.0
                    )
                else:
                    # Conclude with BuyerDecision
                    decision = self.generate_structured_response(prompt, system_instruction, BuyerDecision)
                    return AgentActionProposal(
                        call_tool=None,
                        final_decision={
                            "action": decision.action,
                            "product_id": decision.product_id,
                            "quantity": decision.quantity,
                            "unit_price": str(decision.unit_price),
                            "total_amount": str(decision.total_amount),
                            "rationale": decision.rationale,
                            "constraints_checked": decision.constraints_checked,
                            "basket_items": decision.basket_items
                        },
                        reasoning="Formulate final buyer proposal.",
                        confidence=1.0
                    )
            else:
                # Merchant Agent
                has_constraints = "called 'get_merchant_constraints'" in prompt_lower
                has_inventory = "called 'get_inventory'" in prompt_lower
                
                target_pid = 41 if target_context == "mobile_phone" else (56 if target_context == "smartwatch" else (52 if target_context == "computing" else 1))

                if not has_constraints:
                    return AgentActionProposal(
                        call_tool="get_merchant_constraints",
                        tool_args={},
                        reasoning="Inspect merchant pricing margins rules.",
                        confidence=1.0
                    )
                elif not has_inventory:
                    return AgentActionProposal(
                        call_tool="get_inventory",
                        tool_args={"product_id": target_pid},
                        reasoning=f"Verify stock level of product ID {target_pid}.",
                        confidence=1.0
                    )
                else:
                    # Conclude with MerchantDecision
                    decision = self.generate_structured_response(prompt, system_instruction, MerchantDecision)
                    return AgentActionProposal(
                        call_tool=None,
                        final_decision={
                            "action": decision.action,
                            "product_id": decision.product_id,
                            "quantity": decision.quantity,
                            "unit_price": str(decision.unit_price),
                            "total_amount": str(decision.total_amount),
                            "rationale": decision.rationale,
                            "margin_check": decision.margin_check,
                            "basket_items": decision.basket_items
                        },
                        reasoning="Formulate final merchant response.",
                        confidence=1.0
                    )

        if schema_class == PurchaseRequestProposal:
            product_id = 1
            quantity = 1
            original_amount = Decimal("1599.00")
            final_amount = Decimal("1599.00")
            reason = "Direct purchase recommendation"

            if "soundbar" in prompt_lower or "product 4" in prompt_lower:
                product_id = 4
                original_amount = Decimal("5000.00")
                final_amount = Decimal("5000.00")
                reason = "Premium Soundbar purchase proposal"
            elif "malicious" in prompt_lower or "bypass" in prompt_lower:
                product_id = 1
                original_amount = Decimal("1599.00")
                final_amount = Decimal("10.00")
                reason = "Forced bypass of rules attempt"
            elif "80% discount" in prompt_lower or "give me 80%" in prompt_lower or "90% discount" in prompt_lower or "give me 90%" in prompt_lower:
                product_id = 1
                original_amount = Decimal("1599.00")
                final_amount = Decimal("159.90") if "90" in prompt_lower else Decimal("319.80")
                reason = f"{'90%' if '90' in prompt_lower else '80%'} discount request"

            return PurchaseRequestProposal(
                product_id=product_id,
                quantity=quantity,
                original_amount=original_amount,
                final_amount=final_amount,
                currency="INR",
                reason=reason
            )

        elif schema_class == MerchantOffer:
            product_ids = [1, 2]
            original_amount = Decimal("1998.00")
            offered_amount = Decimal("1899.00")
            discount_percent = Decimal("4.96")
            reason = "Bundle discount recommendation"

            if "cross-sell" in prompt_lower or "identify_related" in prompt_lower or "related" in prompt_lower:
                product_ids = [2]
                original_amount = Decimal("399.00")
                offered_amount = Decimal("399.00")
                discount_percent = Decimal("0.00")
                reason = "Identified charging case (ID 2) as related to earbuds (ID 1)"

            return MerchantOffer(
                product_ids=product_ids,
                original_amount=original_amount,
                offered_amount=offered_amount,
                discount_percent=discount_percent,
                reason=reason
            )

        elif schema_class == Negotiation:
            return Negotiation(
                round=1,
                accepted=True,
                reason="Fits within policy parameters"
            )

        elif schema_class == BuyerDecision:
            action = "OFFER"
            product_id = 1
            quantity = 1
            unit_price = Decimal("1500.00")
            total_amount = Decimal("1500.00")
            rationale = "Proposing initial buyer offer within budget guidelines."
            message = "Hi, I'm looking to purchase this item. Can you offer a better price?"
            constraints = ["budget_check"]

            if "proposed total price 1500" in prompt_lower or "total price 1500 inr" in prompt_lower:
                unit_price = Decimal("1500.00")
                total_amount = Decimal("1500.00")
                basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1500.00"), is_primary=True)]
            elif target_context == "mobile_phone":
                product_id = 41
                is_standalone_req = "standalone without" in prompt_lower or "without accessories" in prompt_lower or "only want" in prompt_lower or "phone alone" in prompt_lower or "without bundle" in prompt_lower or "standalone preferred: true" in prompt_lower
                is_bundle_buyer = ("with accessories" in prompt_lower or "accessories" in prompt_lower or "with charger" in prompt_lower or "bundle" in prompt_lower or "15000" in prompt_lower or "15,000" in prompt_lower) and not is_standalone_req
                
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower or "option 1" in prompt_lower or "evaluate merchant" in prompt_lower or "current merchant standalone" in prompt_lower:
                    if is_bundle_buyer and ("13000" in prompt_lower or "13,000" in prompt_lower):
                        action = "REJECT"
                        unit_price = Decimal("12999.00")
                        total_amount = Decimal("12999.00")
                        rationale = "Merchant bundle offer of ₹13,596 exceeds strict budget limit of ₹13,000."
                        message = "The bundle price of ₹13,596 exceeds my maximum budget of ₹13,000. I cannot proceed with this purchase."
                        basket_items = [
                            BasketItemSchema(product_id=41, name="Samsung Galaxy A15", quantity=1, original_price=Decimal("12999.00"), negotiated_price=Decimal("12999.00"), is_primary=True)
                        ]
                    elif is_bundle_buyer:
                        action = "ACCEPT"
                        total_amount = Decimal("13596.00")
                        rationale = "Buyer accepts the mobile phone with fast charger, protective case, and tempered glass bundle."
                        message = "₹13,596 for the Galaxy A15 with charger, protective case, and tempered glass bundle works for my budget. Deal!"
                        basket_items = [
                            BasketItemSchema(product_id=41, name="Samsung Galaxy A15", quantity=1, original_price=Decimal("12999.00"), negotiated_price=Decimal("11999.00"), is_primary=True),
                            BasketItemSchema(product_id=44, name="25W Fast Charger", quantity=1, original_price=Decimal("1299.00"), negotiated_price=Decimal("999.00"), is_primary=False),
                            BasketItemSchema(product_id=45, name="Mobile Protective Case", quantity=1, original_price=Decimal("499.00"), negotiated_price=Decimal("399.00"), is_primary=False),
                            BasketItemSchema(product_id=46, name="Tempered Glass", quantity=1, original_price=Decimal("299.00"), negotiated_price=Decimal("199.00"), is_primary=False)
                        ]
                    elif is_standalone_req and ("13000" in prompt_lower or "15000" in prompt_lower or "12500" in prompt_lower):
                        action = "ACCEPT"
                        unit_price = Decimal("12500.00")
                        total_amount = Decimal("12500.00")
                        rationale = "Buyer accepts standalone phone offer."
                        message = "₹12,500 for the standalone Samsung Galaxy A15 works for me. Let's proceed with the purchase."
                        basket_items = [
                            BasketItemSchema(
                                product_id=41,
                                name="Samsung Galaxy A15",
                                quantity=1,
                                original_price=Decimal("12999.00"),
                                negotiated_price=Decimal("12500.00"),
                                is_primary=True
                            )
                        ]
                    else:
                        action = "ACCEPT"
                        unit_price = Decimal("11999.00")
                        total_amount = Decimal("11999.00")
                        rationale = "Buyer accepts standalone phone offer of ₹11,999 within the ₹12,000 budget."
                        message = "₹11,999 for the standalone Samsung Galaxy A15 works within my ₹12,000 budget. Let's proceed with the purchase."
                        basket_items = [
                            BasketItemSchema(
                                product_id=41,
                                name="Samsung Galaxy A15",
                                quantity=1,
                                original_price=Decimal("12999.00"),
                                negotiated_price=Decimal("11999.00"),
                                is_primary=True
                            )
                        ]
                else:
                    action = "OFFER"
                    unit_price = Decimal("12000.00")
                    total_amount = Decimal("12000.00")
                    rationale = "Proposing initial offer for Samsung Galaxy A15."
                    message = "Hi, I'm looking for the Samsung Galaxy A15. My budget is around ₹12,000. Can you offer a better price?"
                    basket_items = [
                        BasketItemSchema(
                            product_id=41,
                            name="Samsung Galaxy A15",
                            quantity=1,
                            original_price=Decimal("12999.00"),
                            negotiated_price=Decimal("12000.00"),
                            is_primary=True
                        )
                    ]
            elif target_context == "smartwatch":
                product_id = 56
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower or "option 1" in prompt_lower:
                    action = "ACCEPT"
                    total_amount = Decimal("3848.00")
                    rationale = "Buyer accepts smartwatch and strap bundle."
                    message = "₹3,848 with the Watch Strap included works for my budget. Let's lock the deal!"
                    basket_items = [
                        BasketItemSchema(product_id=56, name="Smartwatch", quantity=1, original_price=Decimal("3999.00"), negotiated_price=Decimal("3499.00"), is_primary=True),
                        BasketItemSchema(product_id=57, name="Watch Strap", quantity=1, original_price=Decimal("499.00"), negotiated_price=Decimal("349.00"), is_primary=False)
                    ]
                else:
                    action = "OFFER"
                    unit_price = Decimal("3500.00")
                    total_amount = Decimal("3500.00")
                    rationale = "Proposing initial offer for Smartwatch."
                    message = "Hi, I'm looking for a Smartwatch. My budget limit is around ₹3,500. Can you offer a better price?"
                    basket_items = [
                        BasketItemSchema(product_id=56, name="Smartwatch", quantity=1, original_price=Decimal("3999.00"), negotiated_price=Decimal("3500.00"), is_primary=True)
                    ]
            elif target_context == "computing":
                product_id = 52
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower or "option 1" in prompt_lower:
                    action = "ACCEPT"
                    total_amount = Decimal("1948.00")
                    rationale = "Buyer accepts keyboard and mouse bundle."
                    message = "₹1,948 for the Wireless Keyboard and Mouse bundle works for me. Let me proceed to checkout."
                    basket_items = [
                        BasketItemSchema(product_id=52, name="Wireless Keyboard", quantity=1, original_price=Decimal("1499.00"), negotiated_price=Decimal("1299.00"), is_primary=True),
                        BasketItemSchema(product_id=53, name="Wireless Mouse", quantity=1, original_price=Decimal("799.00"), negotiated_price=Decimal("649.00"), is_primary=False)
                    ]
                else:
                    action = "OFFER"
                    unit_price = Decimal("1250.00")
                    total_amount = Decimal("1250.00")
                    rationale = "Proposing initial offer for Wireless Keyboard."
                    message = "Hi, I'm looking for a Wireless Keyboard. My budget is around ₹1,250. What's your best offer?"
                    basket_items = [
                        BasketItemSchema(product_id=52, name="Wireless Keyboard", quantity=1, original_price=Decimal("1499.00"), negotiated_price=Decimal("1250.00"), is_primary=True)
                    ]
            else:
                # Audio / Earbuds
                is_bundle_buyer = "profile: value_oriented" in prompt_lower or "standalone preferred: false" in prompt_lower or "merchant counter-offer is 1899 for bundle" in prompt_lower
                is_standalone_buyer = "profile: price_first" in prompt_lower or "standalone preferred: true" in prompt_lower or "only need the earbuds" in prompt_lower or "without accessories" in prompt_lower
                
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower or "evaluate merchant" in prompt_lower or "option 1" in prompt_lower:
                    if is_bundle_buyer and not is_standalone_buyer:
                        action = "ACCEPT"
                        product_id = 1
                        total_amount = Decimal("1899.00")
                        unit_price = Decimal("1500.00")
                        rationale = "Merchant bundle offer of ₹1,899 provides valuable accessory and satisfies budget."
                        message = "I normally only need the earbuds, but the case is useful at ₹1,899. I accept the bundle."
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1500.00"), is_primary=True),
                            BasketItemSchema(product_id=2, name="Premium Charging Case", quantity=1, original_price=Decimal("399.00"), negotiated_price=Decimal("399.00"), is_primary=False)
                        ]
                    elif ("holding previous offer" in prompt_lower or "hold_price" in prompt_lower or "previous offer of" in prompt_lower or "cannot support" in prompt_lower or "hold at" in prompt_lower):
                        action = "ACCEPT"
                        product_id = 1
                        unit_price = Decimal("1499.00")
                        total_amount = Decimal("1499.00")
                        rationale = "Merchant is holding standalone offer of ₹1,499, which is acceptable within budget guidelines."
                        message = "₹1,499 for the standalone earbuds works for me. Deal."
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1499.00"), is_primary=True)
                        ]
                    elif is_standalone_buyer:
                        # Price-first buyer: prefers standalone and counters standalone
                        action = "COUNTER"
                        product_id = 1
                        unit_price = Decimal("1475.00")
                        total_amount = Decimal("1475.00")
                        rationale = "Buyer prefers standalone product over optional bundle to minimize spend. Countering standalone."
                        message = "I only need the earbuds. The charging case is not necessary for me. Can you do ₹1,475 for the standalone product?"
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1475.00"), is_primary=True)
                        ]
                    else:
                        action = "ACCEPT"
                        product_id = 1
                        unit_price = Decimal("1499.00")
                        total_amount = Decimal("1499.00")
                        rationale = "Merchant counter accepted."
                        message = "₹1,499 works for me. Deal."
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1499.00"), is_primary=True)
                        ]
                elif "50 only" in prompt_lower or "rs. 50" in prompt_lower or "₹50" in prompt_lower or "for 50" in prompt_lower or "target budget: ₹50" in prompt_lower or "target budget: 50" in prompt_lower or "predatory" in prompt_lower:
                    action = "OFFER"
                    product_id = 1
                    unit_price = Decimal("50.00")
                    total_amount = Decimal("50.00")
                    rationale = "Proposing predatory buyer offer of ₹50.00."
                    message = "I want to purchase the Wireless Earbuds for ₹50.00 only."
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("50.00"), is_primary=True)
                    ]
                elif "1000" in prompt_lower or "950" in prompt_lower:
                    action = "OFFER"
                    product_id = 1
                    unit_price = Decimal("950.00")
                    total_amount = Decimal("950.00")
                    rationale = "Proposing extremely low buyer offer."
                    message = "Hi, I'm looking for earbuds around ₹950. Can you offer a price in this range?"
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("950.00"), is_primary=True)
                    ]
                elif "1400" in prompt_lower or "1350" in prompt_lower or "1300" in prompt_lower:
                    if "counter" in prompt_lower or "1899" in prompt_lower or "1599" in prompt_lower or "1440" in prompt_lower:
                        action = "COUNTER"
                        product_id = 1
                        unit_price = Decimal("1350.00")
                        total_amount = Decimal("1350.00")
                        rationale = "Merchant counter exceeds budget limit of 1400. Countering with final budget limit."
                        message = "₹1,440 is slightly above my budget limit of ₹1,400. If you can bring it down to ₹1,350, I'll take it."
                    else:
                        action = "OFFER"
                        product_id = 1
                        unit_price = Decimal("1300.00")
                        total_amount = Decimal("1300.00")
                        rationale = "Proposing initial low budget earbuds offer."
                        message = "Hi, I'm looking for earbuds under my ₹1,400 budget limit. Can you do ₹1,300?"
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=unit_price, is_primary=True)
                    ]
                else:
                    action = "OFFER"
                    product_id = 1
                    unit_price = Decimal("1450.00")
                    total_amount = Decimal("1450.00")
                    rationale = "Proposing initial buyer offer for standalone earbuds within budget guidelines."
                    message = "Hi, I'm looking for the Wireless Earbuds Pro. The catalog price is ₹1,599. My budget is ₹2,000, and I'd like to offer ₹1,450 for the standalone product."
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1450.00"), is_primary=True)
                    ]

            return BuyerDecision(
                action=action,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                rationale=rationale,
                message=message,
                constraints_checked=constraints,
                basket_items=basket_items
            )

        elif schema_class == MerchantDecision:
            action = "COUNTER"
            product_id = 3  # Bundle
            quantity = 1
            unit_price = Decimal("1899.00")
            total_amount = Decimal("1899.00")
            rationale = "Proposing cross-sell bundle (Earbuds + Charging Case) for a discounted price."
            message = "I can offer the Wireless Earbuds with a Premium Charging Case for ₹1,899 as a discounted bundle."
            margin_check = "Margin check: PASSED (calculated margin is 34.18% which exceeds min margin 20.00%)"
            bundle_proposal = None
            basket_items = [
                BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1499.00"), is_primary=True),
                BasketItemSchema(product_id=2, name="Premium Charging Case", quantity=1, original_price=Decimal("399.00"), negotiated_price=Decimal("400.00"), is_primary=False)
            ]

            if "buyer offered 1500. calculate margin and counter-offer" in prompt_lower or "buyer offered 1500" in prompt_lower:
                product_id = 3
                unit_price = Decimal("1899.00")
                total_amount = Decimal("1899.00")
                action = "COUNTER"
            elif target_context == "mobile_phone":
                product_id = 41
                is_standalone_req = ("without accessories" in prompt_lower or "standalone without" in prompt_lower or "phone alone" in prompt_lower or "only want" in prompt_lower or "without bundle" in prompt_lower or ("standalone" in prompt_lower and not "recommended standalone price" in prompt_lower and not "for the standalone" in prompt_lower and not "standalone phone" in prompt_lower))
                is_counter_from_buyer = "buyer decision action: counter" in prompt_lower or any(w in prompt_lower for w in ["outside my", "above my", "phone alone", "phone standalone", "take the phone", "exceeds strict budget", "do ₹12,000", "do 12000", "can do 12000", "do ₹11,800", "do 11800"])
                
                if is_counter_from_buyer:
                    action = "ACCEPT"
                    unit_price = Decimal("12000.00")
                    total_amount = Decimal("12000.00")
                    rationale = "Accepting buyer counter of 12000 for Samsung Galaxy A15 (exceeds min_selling_price 11499)."
                    message = "Deal! I can accept ₹12,000 for the standalone Samsung Galaxy A15 as my final price."
                    margin_check = "Margin check: PASSED (calculated margin is 16.67% which exceeds min margin 15.00%)"
                    basket_items = [
                        BasketItemSchema(product_id=41, name="Samsung Galaxy A15", quantity=1, original_price=Decimal("12999.00"), negotiated_price=Decimal("12000.00"), is_primary=True)
                    ]
                elif "hold" in prompt_lower or "cannot support" in prompt_lower or "holding previous offer" in prompt_lower:
                    action = "COUNTER"
                    unit_price = Decimal("11999.00")
                    total_amount = Decimal("11999.00")
                    rationale = "Holding at previous standalone offer of ₹11,999 for Samsung Galaxy A15."
                    message = "I need to hold at my previous standalone offer of ₹11,999 for the Samsung Galaxy A15. If that works for you, we have a deal."
                    margin_check = "Margin check: PASSED"
                    basket_items = [
                        BasketItemSchema(product_id=41, name="Samsung Galaxy A15", quantity=1, original_price=Decimal("12999.00"), negotiated_price=Decimal("11999.00"), is_primary=True)
                    ]
                elif is_standalone_req:
                    if "12500.00" in prompt_lower or "12500" in prompt_lower:
                        action = "ACCEPT"
                        unit_price = Decimal("12500.00")
                        total_amount = Decimal("12500.00")
                        rationale = "Accepting standalone phone offer of 12500."
                        message = "Deal! I accept ₹12,500 for the standalone Samsung Galaxy A15."
                        margin_check = "Margin check: PASSED"
                    elif "11999" in prompt_lower or "11,999" in prompt_lower:
                        action = "COUNTER"
                        unit_price = Decimal("11999.00")
                        total_amount = Decimal("11999.00")
                        rationale = "Countering with standalone phone offer of 11,999."
                        message = "I can offer the Samsung Galaxy A15 for ₹11,999 on its own."
                        margin_check = "Margin check: PASSED"
                    else:
                        action = "COUNTER"
                        unit_price = Decimal("12500.00")
                        total_amount = Decimal("12500.00")
                        rationale = "Countering with standalone phone offer."
                        message = "I can offer the Samsung Galaxy A15 for ₹12,500 on its own."
                        margin_check = "Margin check: PASSED"
                    basket_items = [
                        BasketItemSchema(product_id=41, name="Samsung Galaxy A15", quantity=1, original_price=Decimal("12999.00"), negotiated_price=unit_price, is_primary=True)
                    ]
                else:
                    action = "COUNTER"
                    total_amount = Decimal("13596.00")
                    rationale = "Proposing cross-sell bundle containing charger, protective case, and tempered glass at discounted rates."
                    message = "I can offer ₹11,999 for the Galaxy A15, or ₹13,596 with a 25W Fast Charger, Protective Case, and Tempered Glass included as a complete bundle."
                    margin_check = "Margin check: PASSED"
                    basket_items = [
                        BasketItemSchema(product_id=41, name="Samsung Galaxy A15", quantity=1, original_price=Decimal("12999.00"), negotiated_price=Decimal("11999.00"), is_primary=True),
                        BasketItemSchema(product_id=44, name="25W Fast Charger", quantity=1, original_price=Decimal("1299.00"), negotiated_price=Decimal("999.00"), is_primary=False),
                        BasketItemSchema(product_id=45, name="Mobile Protective Case", quantity=1, original_price=Decimal("499.00"), negotiated_price=Decimal("399.00"), is_primary=False),
                        BasketItemSchema(product_id=46, name="Tempered Glass", quantity=1, original_price=Decimal("299.00"), negotiated_price=Decimal("199.00"), is_primary=False)
                    ]
            elif target_context == "smartwatch":
                product_id = 56
                action = "COUNTER"
                total_amount = Decimal("3848.00")
                rationale = "Proposing cross-sell watch strap bundle."
                message = "I can offer the Smartwatch for ₹3,499, or ₹3,848 with a matching Watch Strap included."
                margin_check = "Margin check: PASSED"
                basket_items = [
                    BasketItemSchema(product_id=56, name="Smartwatch", quantity=1, original_price=Decimal("3999.00"), negotiated_price=Decimal("3499.00"), is_primary=True),
                    BasketItemSchema(product_id=57, name="Watch Strap", quantity=1, original_price=Decimal("499.00"), negotiated_price=Decimal("349.00"), is_primary=False)
                ]
            elif target_context == "computing":
                product_id = 52
                action = "COUNTER"
                total_amount = Decimal("1948.00")
                rationale = "Proposing cross-sell keyboard and mouse bundle."
                message = "I can offer the Wireless Keyboard for ₹1,299, or ₹1,948 with a Wireless Mouse included."
                margin_check = "Margin check: PASSED"
                basket_items = [
                    BasketItemSchema(product_id=52, name="Wireless Keyboard", quantity=1, original_price=Decimal("1499.00"), negotiated_price=Decimal("1299.00"), is_primary=True),
                    BasketItemSchema(product_id=53, name="Wireless Mouse", quantity=1, original_price=Decimal("799.00"), negotiated_price=Decimal("649.00"), is_primary=False)
                ]
            else:
                # Audio / Earbuds
                is_predatory_prompt = "strategy: reject" in prompt_lower or "severely below product cost" in prompt_lower or "total amount: 50" in prompt_lower or "price: 10" in prompt_lower or "amount: 10" in prompt_lower or "malicious" in prompt_lower or "bypass" in prompt_lower or "predatory" in prompt_lower
                if is_predatory_prompt:
                    action = "REJECT"
                    product_id = 1
                    unit_price = Decimal("1599.00")
                    total_amount = Decimal("1599.00")
                    rationale = "Offered price of ₹50.00 is predatory and severely below product cost of ₹1,050.00 and policy floor (<= 40% of cost)."
                    message = "I'm sorry, an offer of ₹50.00 is severely uneconomic and below our product cost. I cannot accept this offer."
                    margin_check = "Margin check: FAILED (offered price ₹50 is <= 40% of product cost ₹1050)"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1599.00"), is_primary=True)]
                elif "319.80" in prompt_lower or "80%" in prompt_lower or "90%" in prompt_lower:
                    action = "REJECT"
                    product_id = 1
                    unit_price = Decimal("1599.00")
                    total_amount = Decimal("1599.00")
                    rationale = "Proposed discount exceeds policy limits."
                    message = "I'm sorry, that discount exceeds our policy maximum limit. I cannot authorize this transaction."
                    margin_check = "Margin check: FAILED"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1599.00"), is_primary=True)]
                elif "1000" in prompt_lower or "950" in prompt_lower:
                    action = "REJECT"
                    product_id = 1
                    unit_price = Decimal("1599.00")
                    total_amount = Decimal("1599.00")
                    rationale = "Offered price is below minimum selling price floor."
                    message = "I'm sorry, that price falls below our mandatory minimum selling price floor. I must decline."
                    margin_check = "Margin check: FAILED"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1599.00"), is_primary=True)]
                elif ("counter" in prompt_lower or "buyer decision: counter" in prompt_lower or "round: 4" in prompt_lower) and ("1475" in prompt_lower or "earbuds alone" in prompt_lower or "hold" in prompt_lower):
                    action = "COUNTER"
                    product_id = 1
                    unit_price = Decimal("1499.00")
                    total_amount = Decimal("1499.00")
                    rationale = "Holding at previous standalone offer of ₹1,499 for Wireless Earbuds Pro."
                    message = "₹1,475 is below the best price I can support. I need to hold at my previous offer of ₹1,499 for the standalone earbuds. If that works for you, we have a deal."
                    margin_check = "Margin check: PASSED"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1499.00"), is_primary=True)]
                elif "1350" in prompt_lower or "1300" in prompt_lower or "1400" in prompt_lower:
                    action = "COUNTER"
                    product_id = 1
                    unit_price = Decimal("1440.00")
                    total_amount = Decimal("1440.00")
                    rationale = "Countering with lowest allowed price of 1440."
                    message = "I can't go down to ₹1,350, but I can offer ₹1,440 as our absolute best price on the Wireless Earbuds."
                    margin_check = "Margin check: PASSED"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1440.00"), is_primary=True)]
                elif "bundle" in prompt_lower or "charging case" in prompt_lower:
                    action = "COUNTER"
                    product_id = 3
                    unit_price = Decimal("1899.00")
                    total_amount = Decimal("1899.00")
                    rationale = "Proposing cross-sell bundle (Earbuds + Charging Case) for a discounted price of ₹1,899."
                    message = "I can offer the Wireless Earbuds with a Premium Charging Case for ₹1,899 as a discounted bundle."
                    margin_check = "Margin check: PASSED"
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1499.00"), is_primary=True),
                        BasketItemSchema(product_id=2, name="Premium Charging Case", quantity=1, original_price=Decimal("399.00"), negotiated_price=Decimal("400.00"), is_primary=False)
                    ]
                else:
                    action = "COUNTER"
                    product_id = 1
                    unit_price = Decimal("1499.00")
                    total_amount = Decimal("1499.00")
                    rationale = "Countering standalone at ₹1,499 and proposing optional charging case bundle at ₹1,899."
                    message = "₹1,450 is below my target price. I can offer the earbuds alone for ₹1,499. Alternatively, since you have ₹2,000 available, I can include the Premium Charging Case for ₹1,899 as a value bundle (saving ₹99 compared to buying separately)."
                    margin_check = "Margin check: PASSED"
                    bundle_proposal = BundleProposalSchema(
                        proposal_id="prop_m_r2_bundle",
                        is_optional=True,
                        bundle_name="Wireless Earbuds Pro + Premium Charging Case",
                        basket_items=[
                            {"product_id": 1, "name": "Wireless Earbuds Pro", "quantity": 1, "original_price": Decimal("1599.00"), "negotiated_price": Decimal("1499.00"), "is_primary": True},
                            {"product_id": 2, "name": "Premium Charging Case", "quantity": 1, "original_price": Decimal("399.00"), "negotiated_price": Decimal("400.00"), "is_primary": False}
                        ],
                        standalone_price=Decimal("1499.00"),
                        bundle_price=Decimal("1899.00"),
                        savings=Decimal("99.00")
                    )
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1499.00"), is_primary=True)
                    ]

            return MerchantDecision(
                action=action,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                rationale=rationale,
                message=message,
                margin_check=margin_check,
                bundle_proposal=bundle_proposal,
                basket_items=basket_items
            )

        else:
            raise ValueError(f"Unsupported schema class for MockProvider: {schema_class}")


class MockLLMProvider(MockProvider):
    """
    Subclass/alias of MockProvider to maintain backward compatibility with existing tests.
    """
    pass


# --- ENVIRONMENT CONFIGURED LLM PROVIDERS ---

class GeminiProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "Gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    def __init__(self, api_key: str, model_name: Optional[str] = None):
        super().__init__()
        self.api_key = api_key
        self._model_name = model_name or os.getenv("LLM_MODEL") or os.getenv("BUYER_LLM_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-3.5-flash"
        self.client = None
        self.legacy_genai = None

        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
        except Exception:
            try:
                import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=self.api_key)
                self.legacy_genai = genai_legacy
            except Exception:
                pass

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client and not self.legacy_genai:
            raise ImportError("Neither google-genai nor google-generativeai package is available.")
        
        import time
        start_t = time.perf_counter()

        max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        response_text = ""

        for attempt in range(max_retries + 1):
            try:
                if self.client:
                    from google.genai import types
                    cfg = types.GenerateContentConfig(
                        system_instruction=system_instruction,
                    )
                    resp = self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=cfg
                    )
                    response_text = resp.text or ""
                    break
                else:
                    model = self.legacy_genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
                    resp = model.generate_content(prompt)
                    response_text = resp.text or ""
                    break
            except Exception as e:
                err_str = str(e)
                # Immediately fail fast on 429 / quota limit so MultiFallbackProvider can switch to next provider
                if "ResourceExhausted" in err_str or "429" in err_str or "quota" in err_str.lower():
                    logger.warning(f"GeminiProvider 429 rate limit hit ({err_str[:100]}). Failing fast to next fallback provider...")
                    raise RuntimeError(f"Gemini 429 ResourceExhausted: rate limit exceeded ({err_str[:100]})")
                elif attempt < max_retries:
                    time.sleep(0.2)
                    continue
                else:
                    raise e

        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="gemini",
            provider_type="real_llm",
            model_name=self.model_name,
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return {"text": response_text, "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        if not self.client and not self.legacy_genai:
            raise ImportError("Neither google-genai nor google-generativeai package is available.")
        
        import time
        start_t = time.perf_counter()

        max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        parsed_data = None

        if self.client:
            from google.genai import types
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=schema_class,
            )
            for attempt in range(max_retries + 1):
                try:
                    resp = self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=config
                    )
                    raw_text = resp.text or ""
                    parsed_data = json.loads(raw_text)
                    break
                except Exception as e:
                    err_str = str(e)
                    # Fast failover on rate limit without waiting through multi-second sleep loops
                    if "ResourceExhausted" in err_str or "429" in err_str or "quota" in err_str.lower():
                        logger.warning(f"GeminiProvider structured 429 hit. Failing fast to next fallback provider...")
                        raise RuntimeError(f"Gemini 429 ResourceExhausted: rate limit exceeded ({err_str[:100]})")
                    elif attempt < max_retries:
                        time.sleep(0.2)
                        continue
                    else:
                        raise e
        else:
            raw_schema = schema_class.model_json_schema() if hasattr(schema_class, "model_json_schema") else schema_class.schema()
            defs = raw_schema.get("$defs", raw_schema.get("definitions", {}))

            def resolve_refs(node: Any) -> Any:
                if isinstance(node, list):
                    return [resolve_refs(x) for x in node]
                if not isinstance(node, dict):
                    return node
                if "$ref" in node:
                    ref_path = node["$ref"].split("/")
                    ref_name = ref_path[-1]
                    if ref_name in defs:
                        merged = defs[ref_name].copy()
                        if "description" in node:
                            merged["description"] = node["description"]
                        return resolve_refs(merged)
                return {k: resolve_refs(v) for k, v in node.items()}

            inlined_schema = resolve_refs(raw_schema)
            
            def clean_schema_dict(node: Any) -> Any:
                if isinstance(node, list):
                    return [clean_schema_dict(x) for x in node]
                if not isinstance(node, dict):
                    return node
                if "anyOf" in node:
                    non_null = [x for x in node["anyOf"] if isinstance(x, dict) and x.get("type") != "null"]
                    if non_null:
                        target = non_null[0].copy()
                        if "description" in node:
                            target["description"] = node["description"]
                        node = target
                    else:
                        node = {"type": "string"}
                if not isinstance(node, dict):
                    return node
                allowed = {"type", "format", "description", "nullable", "enum", "properties", "required", "items"}
                cleaned = {}
                for k, v in node.items():
                    if k in allowed:
                        if k == "properties" and isinstance(v, dict):
                            cleaned[k] = {name: clean_schema_dict(val) for name, val in v.items()}
                        elif k == "items" and isinstance(v, dict):
                            cleaned[k] = clean_schema_dict(v)
                        else:
                            cleaned[k] = v
                return cleaned

            clean_schema = clean_schema_dict(inlined_schema)
            model = self.legacy_genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
            
            for attempt in range(max_retries + 1):
                try:
                    resp = model.generate_content(
                        prompt,
                        generation_config={"response_mime_type": "application/json", "response_schema": clean_schema}
                    )
                    parsed_data = json.loads(resp.text)
                    break
                except Exception as e:
                    err_str = str(e)
                    if "ResourceExhausted" in err_str or "429" in err_str or "quota" in err_str.lower():
                        logger.warning(f"GeminiProvider legacy structured 429 hit. Failing fast to next fallback provider...")
                        raise RuntimeError(f"Gemini 429 ResourceExhausted: rate limit exceeded ({err_str[:100]})")
                    elif attempt < max_retries:
                        time.sleep(0.2)
                        continue
                    else:
                        raise e

        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="gemini",
            provider_type="real_llm",
            model_name=self.model_name,
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return schema_class(**parsed_data)


class OpenRouterProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "OpenRouter"

    @property
    def model_name(self) -> str:
        return self._model_name

    def __init__(self, api_key: str, model_name: Optional[str] = None, base_url: str = "https://openrouter.ai/api/v1"):
        super().__init__()
        self.api_key = api_key
        self._model_name = model_name or os.getenv("OPENROUTER_MODEL") or "meta-llama/llama-3.3-70b-instruct:free"
        self.base_url = base_url.rstrip("/")

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        import time
        import httpx
        start_t = time.perf_counter()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://setu.ai",
            "X-Title": "SETU AI Commerce Trust Layer",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
        }
        
        timeout_sec = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 429:
                    logger.warning(f"OpenRouterProvider 429 rate limit hit. Failing fast to next provider...")
                    raise RuntimeError(f"OpenRouter 429 RateLimit: {resp.text[:120]}")
                resp.raise_for_status()
                data = resp.json()
                response_text = data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            if "429" in str(e):
                raise RuntimeError(f"OpenRouter 429 RateLimit: {str(e)[:120]}")
            raise e

        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="openrouter",
            provider_type="real_llm",
            model_name=self.model_name,
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return {"text": response_text, "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        import time
        import httpx
        start_t = time.perf_counter()
        
        schema_json = json.dumps(schema_class.model_json_schema() if hasattr(schema_class, "model_json_schema") else schema_class.schema())
        json_sys = f"{system_instruction}\n\nIMPORTANT: You must output ONLY a valid JSON object matching this schema. Do not wrap in markdown or backticks:\n{schema_json}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://setu.ai",
            "X-Title": "SETU AI Commerce Trust Layer",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": json_sys},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        timeout_sec = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 429:
                    logger.warning(f"OpenRouterProvider structured 429 rate limit hit. Failing fast to next provider...")
                    raise RuntimeError(f"OpenRouter 429 RateLimit: {resp.text[:120]}")
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"] or "{}"
                cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip())
                cleaned = re.sub(r"\s*```$", "", cleaned.strip())
                parsed = schema_class.model_validate_json(cleaned) if hasattr(schema_class, "model_validate_json") else schema_class.parse_raw(cleaned)
        except Exception as e:
            if "429" in str(e):
                raise RuntimeError(f"OpenRouter 429 RateLimit: {str(e)[:120]}")
            raise e

        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="openrouter",
            provider_type="real_llm",
            model_name=self.model_name,
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return parsed


class GroqProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "Groq"

    @property
    def model_name(self) -> str:
        return self._model_name

    def __init__(self, api_key: str, model_name: Optional[str] = None, base_url: str = "https://api.groq.com/openai/v1"):
        super().__init__()
        self.api_key = api_key
        self._model_name = model_name or os.getenv("GROQ_MODEL") or os.getenv("MERCHANT_LLM_MODEL") or "llama-3.3-70b-versatile"
        self.base_url = base_url.rstrip("/")

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        import time
        import httpx
        start_t = time.perf_counter()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
        }
        
        timeout_sec = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 429:
                    logger.warning(f"GroqProvider 429 rate limit hit. Failing fast to next provider...")
                    raise RuntimeError(f"Groq 429 RateLimit: {resp.text[:120]}")
                resp.raise_for_status()
                data = resp.json()
                response_text = data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            if "429" in str(e):
                raise RuntimeError(f"Groq 429 RateLimit: {str(e)[:120]}")
            raise e

        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="groq",
            provider_type="real_llm",
            model_name=self.model_name,
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return {"text": response_text, "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        import time
        import httpx
        start_t = time.perf_counter()
        
        schema_json = json.dumps(schema_class.model_json_schema() if hasattr(schema_class, "model_json_schema") else schema_class.schema())
        json_sys = f"{system_instruction}\n\nIMPORTANT: You must output ONLY a valid JSON object matching this schema. Do not wrap in markdown or backticks:\n{schema_json}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": json_sys},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        timeout_sec = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 429:
                    logger.warning(f"GroqProvider structured 429 rate limit hit. Failing fast to next provider...")
                    raise RuntimeError(f"Groq 429 RateLimit: {resp.text[:120]}")
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"] or "{}"
                cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip())
                cleaned = re.sub(r"\s*```$", "", cleaned.strip())
                parsed = schema_class.model_validate_json(cleaned) if hasattr(schema_class, "model_validate_json") else schema_class.parse_raw(cleaned)
        except Exception as e:
            if "429" in str(e):
                raise RuntimeError(f"Groq 429 RateLimit: {str(e)[:120]}")
            raise e

        if parsed is None:
            raise ValueError(f"Failed to generate structured response from Groq ({self.model_name})")

        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="groq",
            provider_type="real_llm",
            model_name=self.model_name,
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=latency_ms
        )
        return parsed


class MultiFallbackProvider(LLMProvider):
    """
    Multi-stage fallback wrapper that evaluates providers in priority order.
    Maintains independent agent role context, tracks fallback depth and reasons.
    """
    def __init__(self, providers: List[LLMProvider], timeout_seconds: float = 12.0, agent_role: Optional[str] = None):
        super().__init__()
        if not providers:
            providers = [MockProvider()]
        self.providers = providers
        self.timeout_seconds = timeout_seconds
        self.agent_role = agent_role
        self.active_provider_idx = 0
        self.last_failure_reason: Optional[str] = None

    @property
    def fallback_active(self) -> bool:
        return self.active_provider_idx > 0

    @property
    def fallback_error(self) -> Optional[str]:
        if self.last_execution_metadata and self.last_execution_metadata.fallback_reason:
            return self.last_execution_metadata.fallback_reason
        return self.last_failure_reason

    @property
    def agent_mode(self) -> str:
        current = self.providers[min(self.active_provider_idx, len(self.providers) - 1)]
        if isinstance(current, MockProvider):
            return "OFFLINE MOCK" if self.active_provider_idx == 0 else "FALLBACK MOCK"
        return f"LIVE LLM ({current.provider_name})"

    @property
    def provider_name(self) -> str:
        names = [p.provider_name for p in self.providers]
        return " -> ".join(names)

    @property
    def model_name(self) -> str:
        current = self.providers[min(self.active_provider_idx, len(self.providers) - 1)]
        return current.model_name

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        import concurrent.futures
        import time

        errors = []
        overall_start_t = time.perf_counter()
        for depth, provider in enumerate(self.providers):
            try:
                # If pure MockProvider, run synchronously without thread overhead
                if type(provider) is MockProvider:
                    res = provider.generate_response(prompt, system_instruction, tools)
                else:
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    try:
                        future = executor.submit(provider.generate_response, prompt, system_instruction, tools)
                        res = future.result(timeout=self.timeout_seconds)
                    finally:
                        try:
                            executor.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            executor.shutdown(wait=False)

                latency_ms = round((time.perf_counter() - overall_start_t) * 1000, 2)
                p_meta = getattr(provider, "last_execution_metadata", None)
                provider_used = p_meta.provider_used if p_meta else provider.provider_name.lower()
                model_used = p_meta.model_name if p_meta else provider.model_name
                is_mock = isinstance(provider, MockProvider)

                self.last_execution_metadata = ProviderExecutionMetadata(
                    provider_used=provider_used,
                    provider_type="deterministic_fallback" if is_mock else "real_llm",
                    model_name=model_used,
                    agent_role=self.agent_role,
                    fallback_used=depth > 0,
                    fallback_depth=depth,
                    fallback_reason="; ".join(errors) if depth > 0 else None,
                    response_latency_ms=latency_ms
                )
                self.active_provider_idx = depth
                return res
            except Exception as e:
                err_msg = f"{provider.provider_name}: {type(e).__name__}({str(e)[:100]})"
                errors.append(err_msg)
                self.last_failure_reason = err_msg
                logger.warning(f"Provider {provider.provider_name} at depth {depth} failed for {self.agent_role}: {err_msg}")
                continue

        raise RuntimeError(f"All providers in fallback chain failed: {'; '.join(errors)}")

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        import concurrent.futures
        import time

        errors = []
        overall_start_t = time.perf_counter()
        for depth, provider in enumerate(self.providers):
            try:
                if type(provider) is MockProvider:
                    res = provider.generate_structured_response(prompt, system_instruction, schema_class)
                else:
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    try:
                        future = executor.submit(provider.generate_structured_response, prompt, system_instruction, schema_class)
                        res = future.result(timeout=self.timeout_seconds)
                    finally:
                        try:
                            executor.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            executor.shutdown(wait=False)

                latency_ms = round((time.perf_counter() - overall_start_t) * 1000, 2)
                p_meta = getattr(provider, "last_execution_metadata", None)
                provider_used = p_meta.provider_used if p_meta else provider.provider_name.lower()
                model_used = p_meta.model_name if p_meta else provider.model_name
                is_mock = isinstance(provider, MockProvider)

                self.last_execution_metadata = ProviderExecutionMetadata(
                    provider_used=provider_used,
                    provider_type="deterministic_fallback" if is_mock else "real_llm",
                    model_name=model_used,
                    agent_role=self.agent_role,
                    fallback_used=depth > 0,
                    fallback_depth=depth,
                    fallback_reason="; ".join(errors) if depth > 0 else None,
                    response_latency_ms=latency_ms
                )
                self.active_provider_idx = depth
                return res
            except Exception as e:
                err_msg = f"{provider.provider_name}: {type(e).__name__}({str(e)[:100]})"
                errors.append(err_msg)
                self.last_failure_reason = err_msg
                logger.warning(f"Provider {provider.provider_name} at depth {depth} failed structured response for {self.agent_role}: {err_msg}")
                continue

        raise RuntimeError(f"All providers in fallback chain failed: {'; '.join(errors)}")


# Legacy FallbackProvider alias wrapping MultiFallbackProvider
class FallbackProvider(MultiFallbackProvider):
    def __init__(self, primary: LLMProvider, fallback: Optional[LLMProvider] = None, timeout_seconds: float = 12.0):
        super().__init__(providers=[primary, fallback or MockProvider()], timeout_seconds=timeout_seconds)


class AgentProviderRouter:
    """
    Router that constructs isolated provider instances and fallback chains per agent role.
    """
    @staticmethod
    def create_single_provider(provider_type: str, model_name: Optional[str] = None) -> Optional[LLMProvider]:
        provider_type = provider_type.strip().lower()
        if not provider_type:
            return None

        from backend.app.config import settings

        if provider_type == "gemini":
            key = os.environ.get("LLM_API_KEY", os.environ.get("GEMINI_API_KEY", getattr(settings, "GEMINI_API_KEY", "")))
            if key and str(key).strip():
                try:
                    m_name = model_name or os.environ.get("LLM_MODEL", os.environ.get("GEMINI_MODEL", os.environ.get("BUYER_LLM_MODEL", getattr(settings, "GEMINI_MODEL", None))))
                    return GeminiProvider(api_key=str(key).strip(), model_name=m_name)
                except Exception as e:
                    logger.warning(f"Could not initialize GeminiProvider: {e}")
            return None

        elif provider_type == "openrouter":
            key = os.environ.get("LLM_API_KEY", os.environ.get("OPENROUTER_API_KEY", getattr(settings, "OPENROUTER_API_KEY", "")))
            if key and str(key).strip():
                try:
                    m_name = model_name or os.environ.get("LLM_MODEL", os.environ.get("OPENROUTER_MODEL", getattr(settings, "OPENROUTER_MODEL", None)))
                    return OpenRouterProvider(api_key=str(key).strip(), model_name=m_name)
                except Exception as e:
                    logger.warning(f"Could not initialize OpenRouterProvider: {e}")
            return None

        elif provider_type == "groq":
            key = os.environ.get("LLM_API_KEY", os.environ.get("GROQ_API_KEY", getattr(settings, "GROQ_API_KEY", "")))
            if key and str(key).strip():
                try:
                    m_name = model_name or os.environ.get("LLM_MODEL", os.environ.get("GROQ_MODEL", getattr(settings, "GROQ_MODEL", None)))
                    return GroqProvider(api_key=str(key).strip(), model_name=m_name)
                except Exception as e:
                    logger.warning(f"Could not initialize GroqProvider: {e}")
            return None

        elif provider_type == "mock":
            return MockProvider()

        return None

    @classmethod
    def get_provider_for_agent(cls, role: str = "buyer") -> LLMProvider:
        from backend.app.config import settings
        role = role.lower()
        timeout_sec = float(os.getenv("LLM_TIMEOUT_SECONDS", str(getattr(settings, "LLM_TIMEOUT_SECONDS", 12.0))))
        legacy_override = os.getenv("LLM_PROVIDER")
        legacy_model = os.getenv("LLM_MODEL")

        if role == "buyer":
            primary_name = legacy_override or os.getenv("BUYER_LLM_PROVIDER") or settings.BUYER_LLM_PROVIDER
            primary_model = legacy_model or os.getenv("BUYER_LLM_MODEL") or settings.BUYER_LLM_MODEL
            fallbacks_raw = os.getenv("BUYER_LLM_FALLBACKS", settings.BUYER_LLM_FALLBACKS)
        elif role == "merchant":
            primary_name = os.getenv("MERCHANT_LLM_PROVIDER") or legacy_override or settings.MERCHANT_LLM_PROVIDER
            primary_model = os.getenv("MERCHANT_LLM_MODEL") or legacy_model or settings.MERCHANT_LLM_MODEL
            fallbacks_raw = os.getenv("MERCHANT_LLM_FALLBACKS", settings.MERCHANT_LLM_FALLBACKS)
        else:
            primary_name = os.getenv("AUXILIARY_LLM_PROVIDER") or legacy_override or settings.AUXILIARY_LLM_PROVIDER
            primary_model = os.getenv("AUXILIARY_LLM_MODEL") or legacy_model or settings.AUXILIARY_LLM_MODEL
            fallbacks_raw = os.getenv("AUXILIARY_LLM_FALLBACKS", settings.AUXILIARY_LLM_FALLBACKS)

        if primary_name.lower() == "mock":
            return MockProvider(agent_role=role)

        chain: List[LLMProvider] = []
        
        # 1. Primary provider
        primary_inst = cls.create_single_provider(primary_name, primary_model)
        if primary_inst:
            chain.append(primary_inst)

        # 2. Fallbacks (only if fallback is allowed)
        fallback_allowed = os.getenv("LLM_FALLBACK_TO_MOCK", str(settings.LLM_FALLBACK_TO_MOCK)).lower() in ("true", "1", "yes")
        if fallback_allowed:
            fallback_names = [f.strip() for f in fallbacks_raw.split(",") if f.strip()]
            for fb_name in fallback_names:
                if fb_name.lower() == primary_name.lower() and primary_inst:
                    continue
                fb_inst = cls.create_single_provider(fb_name)
                if fb_inst:
                    chain.append(fb_inst)

            if not any(isinstance(p, MockProvider) for p in chain):
                chain.append(MockProvider(agent_role=role))
            if len(chain) == 1 and isinstance(chain[0], MockProvider):
                chain[0].agent_role = role
                return chain[0]
        else:
            if not chain:
                raise ValueError(f"No configured LLM provider available for role '{role}' and LLM_FALLBACK_TO_MOCK is disabled.")
            if len(chain) == 1:
                chain[0].agent_role = role
                return chain[0]

        for p in chain:
            if not getattr(p, "agent_role", None):
                p.agent_role = role

        return MultiFallbackProvider(providers=chain, timeout_seconds=timeout_sec, agent_role=role)


def get_provider_for_agent(role: str = "buyer") -> LLMProvider:
    """
    Factory function returning an isolated MultiFallbackProvider chain for the given agent role.
    """
    return AgentProviderRouter.get_provider_for_agent(role)


def get_provider_for_task(task_name: str = "auxiliary") -> LLMProvider:
    """
    Factory function returning provider for auxiliary non-critical tasks.
    """
    return AgentProviderRouter.get_provider_for_agent("auxiliary")


def get_provider() -> LLMProvider:
    """
    Backward-compatible factory returning the Buyer agent provider chain.
    """
    return get_provider_for_agent("buyer")

