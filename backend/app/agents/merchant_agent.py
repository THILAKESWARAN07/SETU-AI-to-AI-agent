import os
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.agents.provider import LLMProvider, MerchantOffer, Negotiation, MerchantDecision, get_provider, get_provider_for_agent
from backend.app.agents.tools import (
    ToolRegistry, search_catalog_tool, search_catalog_schema,
    view_product_tool, get_product_details_schema,
    get_inventory_tool, get_inventory_schema,
    get_product_price_tool, get_product_price_schema,
    get_merchant_constraints_tool, get_merchant_constraints_schema,
    evaluate_margin_tool, evaluate_margin_schema,
    identify_related_product_tool, propose_cross_sell_tool, create_bundle_offer_tool
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
            
        self.provider = provider or get_provider_for_agent("merchant")
        self.registry = ToolRegistry()
        self.registry.register_tool("get_inventory", get_inventory_tool, get_inventory_schema)
        self.registry.register_tool("get_product_price", get_product_price_tool, get_product_price_schema)
        self.registry.register_tool("get_merchant_constraints", get_merchant_constraints_tool, get_merchant_constraints_schema)
        self.registry.register_tool("evaluate_margin", evaluate_margin_tool, evaluate_margin_schema)

        # Session trace variables
        self.last_confidence: float = 1.0
        self.last_reasoning: str = ""
        self.tools_called_in_session: List[str] = []

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

    def negotiate_decision(self, db: Session, prompt: str, memory: Optional[Any] = None, context: Optional[Any] = None) -> MerchantDecision:
        if memory is None:
            from backend.app.agents.memory import NegotiationMemory
            memory = NegotiationMemory(session_id="dummy_session_merchant", product_id=1)
        from backend.app.agents.runtime import execute_agent_loop
        return execute_agent_loop(db, self, self.provider, memory, prompt, MerchantDecision, context=context)
