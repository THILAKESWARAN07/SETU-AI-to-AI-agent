import os
import json
import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, List, Optional, Type

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


# --- PROVIDER INTERFACE ---

class LLMProvider(ABC):
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

        else:
            raise ValueError(f"Unsupported schema class for MockProvider: {schema_class}")


class MockLLMProvider(MockProvider):
    """
    Subclass/alias of MockProvider to maintain backward compatibility with existing tests.
    """
    pass


# --- ENVIRONMENT CONFIGURED LLM PROVIDERS ---

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.genai = genai
        except ImportError:
            self.genai = None

    def generate_response(self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.genai:
            raise ImportError("google-generativeai package is not installed. Run 'pip install google-generativeai'.")
        # Call Google Gemini API (model gemini-1.5-flash)
        model = self.genai.GenerativeModel("gemini-1.5-flash", system_instruction=system_instruction)
        # Handle tools conversion if needed or basic text gen
        response = model.generate_content(prompt)
        return {"text": response.text, "tool_calls": []}

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class: Type[BaseModel]) -> BaseModel:
        if not self.genai:
            raise ImportError("google-generativeai package is not installed.")
        
        # Gemini 1.5 Pro/Flash supports structured JSON outputs with response_schema
        model = self.genai.GenerativeModel("gemini-1.5-flash", system_instruction=system_instruction)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json", "response_schema": schema_class}
        )
        data = json.loads(response.text)
        return schema_class(**data)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
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
            model="gpt-4o-mini",
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
            model="gpt-4o-mini",
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
    provider_type = os.getenv("LLM_PROVIDER", "mock").lower()
    
    if provider_type == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "")
        if api_key:
            return GeminiProvider(api_key)
        else:
            logger.warning("GEMINI_API_KEY not configured. Falling back to MockProvider.")
            
    elif provider_type == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            return OpenAIProvider(api_key)
        else:
            logger.warning("OPENAI_API_KEY not configured. Falling back to MockProvider.")
            
    return MockProvider()
