import os
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.agents.provider import LLMProvider, PurchaseRequestProposal, Negotiation, get_provider
from backend.app.agents.tools import (
    ToolRegistry, search_catalog_tool, search_catalog_schema,
    view_product_tool, view_product_schema,
    compare_products_tool, compare_products_schema,
    request_purchase_tool, request_purchase_schema
)

class BuyerAgent:
    def __init__(self, provider: Optional[LLMProvider] = None):
        self.name = "buyer_agent_alpha"
        self.role = "BUYER_AGENT"
        
        # Load system instruction
        current_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(current_dir, "prompts", "buyer_system.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r") as f:
                self.system_instruction = f.read().strip()
        else:
            self.system_instruction = (
                "You are a helpful buyer agent. Search the catalog, find the best products, "
                "negotiate reasonable discounts with the merchant, and create purchase requests. "
                "Never attempt to perform payments. You do not have payment tools."
            )
            
        self.provider = provider or get_provider()
        self.registry = ToolRegistry()
        self.registry.register_tool("search_catalog", search_catalog_tool, search_catalog_schema)
        # Register list_products tool name for backward compatibility with old code!
        self.registry.register_tool("list_products", search_catalog_tool, search_catalog_schema)
        self.registry.register_tool("view_product", view_product_tool, view_product_schema)
        self.registry.register_tool("get_product", view_product_tool, view_product_schema)
        self.registry.register_tool("compare_products", compare_products_tool, compare_products_schema)
        self.registry.register_tool("request_purchase", request_purchase_tool, request_purchase_schema)

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
        
    def compare_products(self, db: Session, product_ids: List[int]) -> List[Dict[str, Any]]:
        return compare_products_tool(db, product_ids=product_ids)
        
    def propose_offer(self, db: Session, product_id: int, quantity: int, proposed_price: Decimal, reason: str) -> PurchaseRequestProposal:
        prompt = (
            f"Propose purchase request for product {product_id}, quantity {quantity}, "
            f"proposed total price {proposed_price} INR. Reason: {reason}"
        )
        return self.provider.generate_structured_response(prompt, self.system_instruction, PurchaseRequestProposal)
        
    def negotiate(self, db: Session, prompt: str) -> Negotiation:
        return self.provider.generate_structured_response(prompt, self.system_instruction, Negotiation)
        
    def request_purchase(self, db: Session, buyer_id: str, product_id: int, quantity: int, proposed_price: str, reason: str) -> Dict[str, Any]:
        return request_purchase_tool(db, buyer_id=buyer_id, product_id=product_id, quantity=quantity, proposed_price=proposed_price, reason=reason)
        
    def explain_decision(self, db: Session, decision: str, reasons: List[str]) -> str:
        prompt = f"Explain why the transaction is {decision}. Reasons provided: {', '.join(reasons)}"
        response = self.provider.generate_response(prompt, self.system_instruction, [])
        return response.get("text", f"The transaction was {decision} due to: {', '.join(reasons)}")
