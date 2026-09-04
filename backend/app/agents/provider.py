import os
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


class BuyerDecision(BaseModel):
    action: Literal["OFFER", "COUNTER", "ACCEPT", "REJECT"] = Field(..., description="The action taken by the buyer agent.")
    product_id: int = Field(..., description="The product key in the catalog.")
    quantity: int = Field(..., description="The quantity requested.")
    unit_price: Decimal = Field(..., description="The unit price offered/countered.")
    total_amount: Decimal = Field(..., description="The final total amount offered (unit_price * quantity).")
    rationale: str = Field(..., description="Reasoning or explanation for this offer decision.")
    message: Optional[str] = Field(default=None, description="Natural human-like dialogue message for the conversation UI.")
    constraints_checked: List[str] = Field(default_factory=list, description="List of boundary constraints evaluated (e.g. budget, policy, inventory).")
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="The items inside the purchase basket.")


class MerchantDecision(BaseModel):
    action: Literal["COUNTER", "ACCEPT", "REJECT"] = Field(..., description="The action taken by the merchant agent.")
    product_id: int = Field(..., description="The product key in the catalog.")
    quantity: int = Field(..., description="The quantity of units requested.")
    unit_price: Decimal = Field(..., description="The unit price offered/countered.")
    total_amount: Decimal = Field(..., description="The total transaction price (unit_price * quantity).")
    rationale: str = Field(..., description="The reasoning behind the merchant's choice.")
    message: Optional[str] = Field(default=None, description="Natural human-like dialogue message for the conversation UI.")
    margin_check: str = Field(..., description="Detailed verification explanation showing margin guideline check.")
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="The items inside the proposed bundle/basket.")


# --- PROVIDER INTERFACE ---

class LLMProvider(ABC):
    @property
    def agent_mode(self) -> str:
        return "LIVE LLM"

    @property
    def provider_name(self) -> str:
        return "GenericProvider"

    @property
    def model_name(self) -> str:
        return "generic-model"

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

            if target_context == "mobile_phone":
                product_id = 41
                is_strict_low_budget = ("12000" in prompt_lower or "12,000" in prompt_lower or "11500" in prompt_lower) and not ("15000" in prompt_lower or "15,000" in prompt_lower or "14000" in prompt_lower or "14,000" in prompt_lower or "13000" in prompt_lower or "13,000" in prompt_lower)
                is_standalone_req = "standalone" in prompt_lower or "without accessories" in prompt_lower or "only want" in prompt_lower
                
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower:
                    if is_strict_low_budget:
                        # Strict budget around 12,000 - reject 13,596 bundle and counter with phone alone
                        action = "COUNTER"
                        unit_price = Decimal("12000.00")
                        total_amount = Decimal("12000.00")
                        rationale = "Bundle exceeds strict budget of 12,000. Countering with phone standalone."
                        message = "That bundle is above my ₹12,000 budget. I'll take the phone alone if you can do ₹12,000."
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
                    elif is_standalone_req:
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
                                negotiated_price=unit_price,
                                is_primary=True
                            )
                        ]
                    else:
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
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower:
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
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower:
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
                if "proposed basket counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower:
                    is_low_budget = ("around 1500" in prompt_lower or "limit is 1500" in prompt_lower or "budget: 1500" in prompt_lower or "limit is ₹1,500" in prompt_lower or "around ₹1,500" in prompt_lower or "1500 inr" in prompt_lower or "1400" in prompt_lower or "1350" in prompt_lower or "1300" in prompt_lower) and not ("2000" in prompt_lower and not any(k in prompt_lower for k in ["around 1500", "under 1400", "1500 inr", "around ₹1,500"]))
                    is_standalone_req = "without accessories" in prompt_lower or "standalone without" in prompt_lower or "earbuds alone" in prompt_lower or "only want" in prompt_lower
                    
                    if "1450" in prompt_lower or "1440" in prompt_lower:
                        action = "ACCEPT"
                        product_id = 1
                        unit_price = Decimal("1450.00") if "1450" in prompt_lower else Decimal("1440.00")
                        total_amount = unit_price
                        rationale = f"Merchant offer of ₹{unit_price} for standalone earbuds is within budget limit."
                        message = f"₹{unit_price} for the Wireless Earbuds Pro works for me. Deal!"
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=unit_price, is_primary=True)
                        ]
                    elif is_low_budget or is_standalone_req:
                        action = "COUNTER"
                        product_id = 1
                        unit_price = Decimal("1450.00")
                        total_amount = Decimal("1450.00")
                        rationale = "Merchant bundle exceeds budget limit. Countering with standalone earbuds at ₹1,450."
                        message = "The bundle is interesting, but ₹1,899 is over my budget limit. Can you do ₹1,450 for the earbuds alone?"
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1450.00"), is_primary=True)
                        ]
                    else:
                        action = "ACCEPT"
                        product_id = 3  # Bundle
                        unit_price = Decimal("1899.00")
                        total_amount = Decimal("1899.00")
                        rationale = "Merchant counter-offer of 1899 INR for the bundle is within budget limit."
                        message = "₹1,899 for the Wireless Earbuds and Charging Case bundle works for me. Deal!"
                        constraints = ["budget_evaluation", "accessory_need_satisfied"]
                        basket_items = [
                            BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1500.00"), is_primary=True),
                            BasketItemSchema(product_id=2, name="Premium Charging Case", quantity=1, original_price=Decimal("399.00"), negotiated_price=Decimal("399.00"), is_primary=False)
                        ]
                elif "1500" in prompt_lower:
                    action = "OFFER"
                    product_id = 1
                    unit_price = Decimal("1500.00")
                    total_amount = Decimal("1500.00")
                    rationale = "Proposing initial offer for earbuds."
                    message = "Hi, I'm looking for wireless earbuds. My budget limit is ₹1,500. Can you offer a good price?"
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1500.00"), is_primary=True)
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
                    unit_price = Decimal("1500.00")
                    total_amount = Decimal("1500.00")
                    rationale = "Proposing initial buyer offer for earbuds within budget guidelines."
                    message = "Hi, I'm looking for Wireless Earbuds under my ₹2,000 budget cap. Can you offer a competitive price?"
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

            if target_context == "mobile_phone":
                product_id = 41
                is_standalone_req = ("without accessories" in prompt_lower or "standalone without" in prompt_lower or "phone alone" in prompt_lower or "only want" in prompt_lower or "without bundle" in prompt_lower or ("standalone" in prompt_lower and not "recommended standalone price" in prompt_lower and not "for the standalone" in prompt_lower and not "standalone phone" in prompt_lower))
                is_counter_from_buyer = "buyer decision action: counter" in prompt_lower or any(w in prompt_lower for w in ["outside my", "above my", "phone alone", "phone standalone", "take the phone", "exceeds strict budget"])
                
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
                elif is_standalone_req:
                    if "12500.00" in prompt_lower or "12500" in prompt_lower:
                        action = "ACCEPT"
                        unit_price = Decimal("12500.00")
                        total_amount = Decimal("12500.00")
                        rationale = "Accepting standalone phone offer of 12500."
                        message = "Deal! I accept ₹12,500 for the standalone Samsung Galaxy A15."
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
                if "price: 10" in prompt_lower or "amount: 10" in prompt_lower or "malicious" in prompt_lower or "bypass" in prompt_lower:
                    action = "REJECT"
                    product_id = 1
                    unit_price = Decimal("1599.00")
                    total_amount = Decimal("1599.00")
                    rationale = "Offered price of 10 INR is extremely below product cost and min margin limits."
                    message = "I'm sorry, an offer of ₹10 is below our cost. I cannot accept an offer below our minimum price guidelines."
                    margin_check = "Margin check: FAILED (offered price ₹10 is below product cost ₹1050)"
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
                elif ("buyer decision action: counter" in prompt_lower or "buyer decision: counter" in prompt_lower) and ("1450" in prompt_lower or "earbuds alone" in prompt_lower or "1400" in prompt_lower):
                    action = "ACCEPT"
                    product_id = 1
                    unit_price = Decimal("1450.00")
                    total_amount = Decimal("1450.00")
                    rationale = "Accepting buyer counter of 1450 for Wireless Earbuds Pro (exceeds min_selling_price 1349)."
                    message = "Deal! I can accept ₹1,450 for the standalone Wireless Earbuds Pro as my final price."
                    margin_check = "Margin check: PASSED"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1450.00"), is_primary=True)]
                elif "1350" in prompt_lower or "1300" in prompt_lower or "1400" in prompt_lower:
                    action = "COUNTER"
                    product_id = 1
                    unit_price = Decimal("1440.00")
                    total_amount = Decimal("1440.00")
                    rationale = "Countering with lowest allowed price of 1440."
                    message = "I can't go down to ₹1,350, but I can offer ₹1,440 as our absolute best price on the Wireless Earbuds."
                    margin_check = "Margin check: PASSED"
                    basket_items = [BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1440.00"), is_primary=True)]
                else:
                    action = "COUNTER"
                    product_id = 3
                    unit_price = Decimal("1899.00")
                    total_amount = Decimal("1899.00")
                    rationale = "Proposing cross-sell bundle (Earbuds + Charging Case) for a discounted price."
                    message = "I can offer the Wireless Earbuds with a Premium Charging Case for ₹1,899 as a discounted bundle."
                    margin_check = "Margin check: PASSED"
                    basket_items = [
                        BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1500.00"), is_primary=True),
                        BasketItemSchema(product_id=2, name="Premium Charging Case", quantity=1, original_price=Decimal("399.00"), negotiated_price=Decimal("399.00"), is_primary=False)
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
        self.api_key = api_key
        self._model_name = model_name or "gemini-1.5-flash"
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.genai = genai
        except ImportError:
            self.genai = None

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.genai:
            raise ImportError("google-generativeai package is not installed. Run 'pip install google-generativeai'.")
        
        # Non-blocking spacer to respect rate limits
        import time
        time.sleep(0.1)

        # Call Google Gemini API
        model = self.genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
        response = model.generate_content(prompt)
        return {"text": response.text, "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        if not self.genai:
            raise ImportError("google-generativeai package is not installed.")
        
        # Non-blocking spacer to respect rate limits
        import time
        time.sleep(0.1)

        # Clean Pydantic schema dict to match Google Generative AI Schema proto requirements
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
        
        # Gemini supports structured JSON outputs with response_schema
        model = self.genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json", "response_schema": clean_schema}
        )
        data = json.loads(response.text)
        return schema_class(**data)


class OpenAIProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "OpenAI"

    @property
    def model_name(self) -> str:
        return self._model_name

    def __init__(self, api_key: str, model_name: Optional[str] = None):
        self.api_key = api_key
        self._model_name = model_name or "gpt-4o-mini"
        try:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
        except ImportError:
            self.client = None

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client:
            raise ImportError("openai package is not installed. Run 'pip install openai'.")
        # Standard OpenAI ChatCompletion call
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
        )
        return {"text": response.choices[0].message.content or "", "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        if not self.client:
            raise ImportError("openai package is not installed.")
        # OpenAI supports structured outputs with response_format=schema_class
        response = self.client.beta.chat.completions.parse(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            response_format=schema_class
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Failed to parse structured output from OpenAI.")
        return parsed


class FallbackProvider(LLMProvider):
    """
    Robust provider decorator that attempts the primary live provider with a strict timeout.
    If the primary provider fails (e.g. 429 Quota Exhausted, 401 Unauthorized, Network timeout),
    it smoothly falls back to the deterministic MockProvider and records provider metadata.
    """
    def __init__(self, primary: LLMProvider, fallback: Optional[LLMProvider] = None, timeout_seconds: float = 3.5):
        self.primary = primary
        self.fallback = fallback or MockProvider()
        self.timeout_seconds = timeout_seconds
        self.fallback_active = False
        self.fallback_error: Optional[str] = None

    @property
    def agent_mode(self) -> str:
        if self.fallback_active:
            return "FALLBACK MOCK (Live LLM Fallback)"
        return self.primary.agent_mode

    @property
    def provider_name(self) -> str:
        if self.fallback_active:
            return f"{self.primary.provider_name} (Fell back to Mock)"
        return self.primary.provider_name

    @property
    def model_name(self) -> str:
        if self.fallback_active:
            return f"{self.primary.model_name} -> {self.fallback.model_name}"
        return self.primary.model_name

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self.fallback_active:
            return self.fallback.generate_response(prompt, system_instruction, tools)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.primary.generate_response, prompt, system_instruction, tools)
            try:
                return future.result(timeout=self.timeout_seconds)
            except Exception as e:
                logger.warning(f"Primary provider '{self.primary.provider_name}' failed ({type(e).__name__}: {e}). Activating MockProvider fallback.")
                self.fallback_active = True
                self.fallback_error = str(e)
                return self.fallback.generate_response(prompt, system_instruction, tools)

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        if self.fallback_active:
            return self.fallback.generate_structured_response(prompt, system_instruction, schema_class)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.primary.generate_structured_response, prompt, system_instruction, schema_class)
            try:
                return future.result(timeout=self.timeout_seconds)
            except Exception as e:
                logger.warning(f"Primary provider '{self.primary.provider_name}' structured response failed ({type(e).__name__}: {e}). Activating MockProvider fallback.")
                self.fallback_active = True
                self.fallback_error = str(e)
                return self.fallback.generate_structured_response(prompt, system_instruction, schema_class)


def get_provider() -> LLMProvider:
    """
    Factory function to initialize the LLM Provider based on env variables.
    """
    from backend.app.config import settings
    provider_type = os.getenv("LLM_PROVIDER", settings.LLM_PROVIDER).lower()
    
    fallback_env = os.getenv("LLM_FALLBACK_TO_MOCK")
    if fallback_env is not None:
        fallback_allowed = fallback_env.lower() in ("true", "1", "yes")
    else:
        fallback_allowed = settings.LLM_FALLBACK_TO_MOCK
    
    api_key = os.getenv("LLM_API_KEY", settings.LLM_API_KEY)
    model_name = os.getenv("LLM_MODEL", settings.LLM_MODEL)

    if provider_type == "gemini":
        gemini_key = api_key or os.getenv("GEMINI_API_KEY", settings.GEMINI_API_KEY)
        if gemini_key:
            try:
                gemini_inst = GeminiProvider(gemini_key, model_name=model_name)
                if fallback_allowed:
                    return FallbackProvider(primary=gemini_inst, fallback=MockProvider(), timeout_seconds=3.5)
                return gemini_inst
            except Exception as e:
                logger.error(f"Failed to initialize GeminiProvider: {e}")
                if not fallback_allowed:
                    raise e
        else:
            logger.warning("GEMINI_API_KEY not configured. Falling back to MockProvider.")
            if not fallback_allowed:
                raise ValueError("Gemini API key not configured and LLM_FALLBACK_TO_MOCK is disabled.")
            
    elif provider_type == "openai":
        openai_key = api_key or os.getenv("OPENAI_API_KEY", settings.OPENAI_API_KEY)
        if openai_key:
            try:
                openai_inst = OpenAIProvider(openai_key, model_name=model_name)
                if fallback_allowed:
                    return FallbackProvider(primary=openai_inst, fallback=MockProvider(), timeout_seconds=3.5)
                return openai_inst
            except Exception as e:
                logger.error(f"Failed to initialize OpenAIProvider: {e}")
                if not fallback_allowed:
                    raise e
        else:
            logger.warning("OPENAI_API_KEY not configured. Falling back to MockProvider.")
            if not fallback_allowed:
                raise ValueError("OpenAI API key not configured and LLM_FALLBACK_TO_MOCK is disabled.")

    if provider_type != "mock" and not fallback_allowed:
        raise ValueError(f"LLM provider type '{provider_type}' is unavailable and fallback is disabled.")

    return MockProvider()
