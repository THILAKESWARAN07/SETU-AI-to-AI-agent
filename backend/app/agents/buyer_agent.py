import os
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.app.agents.provider import LLMProvider, PurchaseRequestProposal, Negotiation, BuyerDecision, get_provider, get_provider_for_agent
from backend.app.agents.tools import (
    ToolRegistry, search_catalog_tool, search_catalog_schema,
    view_product_tool, get_product_details_schema,
    get_policy_constraints_tool, get_policy_constraints_schema,
    evaluate_budget_tool, evaluate_budget_schema,
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
            
        self.provider = provider or get_provider_for_agent("buyer")
        self.registry = ToolRegistry()
        self.registry.register_tool("search_catalog", search_catalog_tool, search_catalog_schema)
        self.registry.register_tool("get_product_details", view_product_tool, get_product_details_schema)
        self.registry.register_tool("get_policy_constraints", get_policy_constraints_tool, get_policy_constraints_schema)
        self.registry.register_tool("evaluate_budget", evaluate_budget_tool, evaluate_budget_schema)
        
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
                if t_name == "request_purchase":
                    result = request_purchase_tool(db, **t_args)
                else:
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

    def negotiate_decision(self, db: Session, prompt: str, memory: Optional[Any] = None, context: Optional[Any] = None) -> BuyerDecision:
        if memory is None:
            from backend.app.agents.memory import NegotiationMemory
            memory = NegotiationMemory(session_id="dummy_session_buyer", product_id=1)
        from backend.app.agents.runtime import execute_agent_loop
        return execute_agent_loop(db, self, self.provider, memory, prompt, BuyerDecision, context=context)
        
    def request_purchase(self, db: Session, buyer_id: str, product_id: int, quantity: int, proposed_price: str, reason: str) -> Dict[str, Any]:
        return request_purchase_tool(db, buyer_id=buyer_id, product_id=product_id, quantity=quantity, proposed_price=proposed_price, reason=reason)
        
    def explain_decision(self, db: Session, decision: str, reasons: List[str]) -> str:
        prompt = f"Explain why the transaction is {decision}. Reasons provided: {', '.join(reasons)}"
        response = self.provider.generate_response(prompt, self.system_instruction, [])
        return response.get("text", f"The transaction was {decision} due to: {', '.join(reasons)}")
