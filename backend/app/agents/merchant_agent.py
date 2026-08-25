import os
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.agents.provider import LLMProvider, MerchantOffer, Negotiation, get_provider
from backend.app.agents.tools import (
    ToolRegistry, search_catalog_tool, search_catalog_schema,
    view_product_tool, view_product_schema,
    identify_related_product_tool, identify_related_product_schema,
    propose_cross_sell_tool, propose_cross_sell_schema,
    create_bundle_offer_tool, create_bundle_offer_schema
)

class MerchantAgent:
    def __init__(self, provider: Optional[LLMProvider] = None):
        self.name = "merchant_agent_beta"
        self.role = "MERCHANT_AGENT"
        
        # Load system instruction
        current_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(current_dir, "prompts", "merchant_system.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r") as f:
                self.system_instruction = f.read().strip()
        else:
            self.system_instruction = (
                "You are a merchant agent. Manage inquiries, recommend related products, "
                "propose cross-sells, create bundle offers, and negotiate transaction offers "
                "matching company pricing margins and policies."
            )
            
        self.provider = provider or get_provider()
        self.registry = ToolRegistry()
        self.registry.register_tool("search_catalog", search_catalog_tool, search_catalog_schema)
        self.registry.register_tool("view_product", view_product_tool, view_product_schema)
        self.registry.register_tool("identify_related_product", identify_related_product_tool, identify_related_product_schema)
        self.registry.register_tool("propose_cross_sell", propose_cross_sell_tool, propose_cross_sell_schema)
        self.registry.register_tool("create_bundle_offer", create_bundle_offer_tool, create_bundle_offer_schema)

    def process_message(self, db: Session, message: str) -> Dict[str, Any]:
        tools_definition = self.registry.get_tool_definitions()
        response = self.provider.generate_response(message, self.system_instruction, tools_definition)
        
        text = response.get("text", "")
        tool_calls = response.get("tool_calls", [])
        executed_tool_results = []

        for call in tool_calls:
            t_name = call.get("name")
            t_args = call.get("args", {})
            try:
                result = self.registry.execute_tool(t_name, db, **t_args)
                executed_tool_results.append({
                    "tool_name": t_name,
                    "args": t_args,
                    "result": result
                })
            except Exception as e:
                executed_tool_results.append({
                    "tool_name": t_name,
                    "args": t_args,
                    "error": str(e)
                })

        return {
            "agent_response": text,
            "tool_executions": executed_tool_results
        }

    # CAPABILITIES
    
    def search_catalog(self, db: Session, query: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        return search_catalog_tool(db, query=query, category=category)
        
    def view_product(self, db: Session, product_id: int) -> Dict[str, Any]:
        return view_product_tool(db, product_id=product_id)
        
    def identify_related_product(self, db: Session, product_id: int) -> Dict[str, Any]:
        return identify_related_product_tool(db, product_id=product_id)
        
    def propose_cross_sell(self, db: Session, product_id: int) -> MerchantOffer:
        prompt = f"Propose a structured cross-sell suggestion for reference product ID {product_id}."
        return self.provider.generate_structured_response(prompt, self.system_instruction, MerchantOffer)
        
    def create_bundle_offer(self, db: Session, product_ids: List[int], discount_percent: Optional[Decimal] = Decimal("5.0")) -> MerchantOffer:
        prompt = f"Create a structured bundle offer for product IDs {product_ids} with {discount_percent}% discount."
        return self.provider.generate_structured_response(prompt, self.system_instruction, MerchantOffer)
        
    def negotiate(self, db: Session, prompt: str) -> Negotiation:
        return self.provider.generate_structured_response(prompt, self.system_instruction, Negotiation)
