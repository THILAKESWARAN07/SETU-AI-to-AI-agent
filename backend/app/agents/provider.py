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


class BuyerDecision(BaseModel):
    action: Literal["OFFER", "COUNTER", "ACCEPT", "REJECT"] = Field(..., description="The action taken by the buyer agent.")
    product_id: int = Field(..., description="The product key in the catalog.")
    quantity: int = Field(..., description="The quantity requested.")
    unit_price: Decimal = Field(..., description="The unit price offered/countered.")
    total_amount: Decimal = Field(..., description="The final total amount offered (unit_price * quantity).")
    rationale: str = Field(..., description="Reasoning or explanation for this offer decision.")
    constraints_checked: List[str] = Field(default_factory=list, description="List of boundary constraints evaluated (e.g. budget, policy, inventory).")


class MerchantDecision(BaseModel):
    action: Literal["COUNTER", "ACCEPT", "REJECT"] = Field(..., description="The action taken by the merchant agent.")
    product_id: int = Field(..., description="The product key in the catalog.")
    quantity: int = Field(..., description="The quantity of units requested.")
    unit_price: Decimal = Field(..., description="The unit price offered/countered.")
    total_amount: Decimal = Field(..., description="The total transaction price (unit_price * quantity).")
    rationale: str = Field(..., description="The reasoning behind the merchant's choice.")
    margin_check: str = Field(..., description="Detailed verification explanation showing margin guideline check.")


# --- PROVIDER INTERFACE ---

class LLMProvider(ABC):
    @property
    def agent_mode(self) -> str:
        return "LIVE LLM"

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

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        prompt_lower = prompt.lower()

        # Handle AgentActionProposal for Step 10 inner reasoning loop
        if schema_class.__name__ == "AgentActionProposal":
            from backend.app.agents.runtime import AgentActionProposal
            
            is_buyer = "search_catalog" in prompt_lower
            
            if is_buyer:
                # Check history of tool executions from the prompt context
                has_searched = "called 'search_catalog'" in prompt_lower
                has_details = "called 'get_product_details'" in prompt_lower
                has_policy = "called 'get_policy_constraints'" in prompt_lower
                
                if not has_searched:
                    return AgentActionProposal(
                        call_tool="search_catalog",
                        tool_args={"query": "earbuds"},
                        reasoning="Search catalog to locate wireless earbuds.",
                        confidence=1.0
                    )
                elif not has_details:
                    return AgentActionProposal(
                        call_tool="get_product_details",
                        tool_args={"product_id": 1},
                        reasoning="Get base price and specs for wireless earbuds.",
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
                            "constraints_checked": decision.constraints_checked
                        },
                        reasoning="Formulate final buyer proposal.",
                        confidence=1.0
                    )
            else:
                # Merchant Agent
                has_constraints = "called 'get_merchant_constraints'" in prompt_lower
                has_inventory = "called 'get_inventory'" in prompt_lower
                
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
                        tool_args={"product_id": 1},
                        reasoning="Verify stock level of product ID 1.",
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
                            "margin_check": decision.margin_check
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

            if "soundbar" in prompt_lower or "4" in prompt_lower:
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
            unit_price = Decimal("1800.00")
            total_amount = Decimal("1800.00")
            rationale = "Proposing initial buyer offer for earbuds within budget guidelines."
            constraints = ["budget_check"]

            if "1500" in prompt_lower:
                unit_price = Decimal("1500.00")
                total_amount = Decimal("1500.00")
            elif "1400" in prompt_lower or "1350" in prompt_lower:
                if "counter" in prompt_lower or "1899" in prompt_lower or "1599" in prompt_lower or "1440" in prompt_lower:
                    action = "COUNTER"
                    product_id = 1
                    unit_price = Decimal("1350.00")
                    total_amount = Decimal("1350.00")
                    rationale = "Merchant counter exceeds budget limit of 1400. Countering with final budget limit."
                else:
                    action = "OFFER"
                    product_id = 1
                    unit_price = Decimal("1300.00")
                    total_amount = Decimal("1300.00")
                    rationale = "Proposing initial low budget earbuds offer."
            elif "1000" in prompt_lower:
                action = "OFFER"
                product_id = 1
                unit_price = Decimal("950.00")
                total_amount = Decimal("950.00")
                rationale = "Proposing extremely low buyer offer."
            elif ("merchant's counter-offer" in prompt_lower or "merchant counter-offer" in prompt_lower) and "will counter-offer" not in prompt_lower:
                action = "ACCEPT"
                product_id = 3  # Bundle
                unit_price = Decimal("1899.00")
                total_amount = Decimal("1899.00")
                rationale = "Merchant counter-offer of 1899 INR for the bundle is within budget limit."
                constraints = ["budget_evaluation", "accessory_need_satisfied"]

            return BuyerDecision(
                action=action,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                rationale=rationale,
                constraints_checked=constraints
            )

        elif schema_class == MerchantDecision:
            action = "COUNTER"
            product_id = 3  # Bundle
            quantity = 1
            unit_price = Decimal("1899.00")
            total_amount = Decimal("1899.00")
            rationale = "Proposing cross-sell bundle (Earbuds + Charging Case) for a discounted price."
            margin_check = "Margin check: PASSED (calculated margin is 34.18% which exceeds min margin 20.00%)"

            if "price: 10" in prompt_lower or "amount: 10" in prompt_lower or "malicious" in prompt_lower or "bypass" in prompt_lower:
                action = "REJECT"
                product_id = 1
                unit_price = Decimal("1599.00")
                total_amount = Decimal("1599.00")
                rationale = "Offered price of 10 INR is extremely below product cost and min margin limits."
                margin_check = "Margin check: FAILED (offered price ₹10 is below product cost ₹1050)"
            elif "319.80" in prompt_lower or "80%" in prompt_lower or "90%" in prompt_lower:
                action = "REJECT"
                product_id = 1
                unit_price = Decimal("1599.00")
                total_amount = Decimal("1599.00")
                rationale = "Proposed price violates max discount limit policies."
                margin_check = "Margin check: FAILED (discount exceeds maximum policy limit)"
            elif "950.00" in prompt_lower:
                action = "REJECT"
                product_id = 1
                unit_price = Decimal("1599.00")
                total_amount = Decimal("1599.00")
                rationale = "Offered price of 950 INR violates minimum margin parameters."
                margin_check = "Margin check: FAILED (offered price ₹950 is below product cost ₹1050)"
            elif "1350.00" in prompt_lower or "1300.00" in prompt_lower:
                # Buyer offered 1300 or 1350 for earbuds - violates policy min discount. Counter with 1440!
                action = "COUNTER"
                product_id = 1
                unit_price = Decimal("1440.00")
                total_amount = Decimal("1440.00")
                rationale = "Offered price is below policy discount cap limits. Counter-offering minimum allowed price ₹1,440.00."
                margin_check = "Margin check: PASSED"
            elif "1440.00" in prompt_lower:
                action = "ACCEPT"
                product_id = 1
                unit_price = Decimal("1440.00")
                total_amount = Decimal("1440.00")
                rationale = "Buyer offer of 1440 INR complies with company profit and discount guidelines."
                margin_check = "Margin check: PASSED"

            return MerchantDecision(
                action=action,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                rationale=rationale,
                margin_check=margin_check
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
    def __init__(self, api_key: str, model_name: Optional[str] = None):
        self.api_key = api_key
        self.model_name = model_name or "gemini-1.5-flash"
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.genai = genai
        except ImportError:
            self.genai = None

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.genai:
            raise ImportError("google-generativeai package is not installed. Run 'pip install google-generativeai'.")
        
        # Rate-limiting spacer to protect free tier quota limits
        import time
        logger.info("Spacing API calls to avoid rate limits: Sleeping for 13 seconds...")
        time.sleep(13)

        # Call Google Gemini API
        model = self.genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
        response = model.generate_content(prompt)
        return {"text": response.text, "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        if not self.genai:
            raise ImportError("google-generativeai package is not installed.")
        
        # Rate-limiting spacer to protect free tier quota limits
        import time
        logger.info("Spacing API calls to avoid rate limits: Sleeping for 13 seconds...")
        time.sleep(13)

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
    def __init__(self, api_key: str, model_name: Optional[str] = None):
        self.api_key = api_key
        self.model_name = model_name or "gpt-4o-mini"
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
                return GeminiProvider(gemini_key, model_name=model_name)
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
                return OpenAIProvider(openai_key, model_name=model_name)
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
