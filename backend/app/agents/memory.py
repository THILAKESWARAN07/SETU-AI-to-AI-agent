import logging
from typing import Dict, Any, List, Optional
from decimal import Decimal

logger = logging.getLogger("setu.agents.memory")

class NegotiationMemory:
    def __init__(self, session_id: str, product_id: int):
        self.session_id = session_id
        self.product_id = product_id
        self.buyer_goal: str = ""
        self.merchant_goal: str = ""
        self.round_number: int = 1
        
        # Chronological traces
        self.offers: List[Decimal] = []
        self.counter_offers: List[Decimal] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self.policy_verdicts: List[Dict[str, Any]] = []
        self.final_outcome: Optional[str] = None

    def add_tool_call(self, agent: str, tool_name: str, args: Dict[str, Any]):
        event = {
            "agent": agent,
            "tool_name": tool_name,
            "args": args,
            "round": self.round_number
        }
        self.tool_calls.append(event)
        logger.info(f"Memory [{self.session_id}]: {agent} called tool {tool_name}")

    def add_observation(self, agent: str, tool_name: str, result: Any):
        event = {
            "agent": agent,
            "tool_name": tool_name,
            "result": result,
            "round": self.round_number
        }
        self.observations.append(event)
        logger.info(f"Memory [{self.session_id}]: {agent} observed tool result for {tool_name}")

    def add_decision(self, agent: str, action: str, amount: Decimal, rationale: str, confidence: float = 1.0):
        decision = {
            "agent": agent,
            "action": action,
            "amount": str(amount),
            "rationale": rationale,
            "confidence": confidence,
            "round": self.round_number
        }
        self.decisions.append(decision)
        if agent == "BUYER_AGENT":
            self.offers.append(amount)
        else:
            self.counter_offers.append(amount)
        logger.info(f"Memory [{self.session_id}]: {agent} made decision {action} for amount {amount}")

    def add_policy_verdict(self, decision: str, reasons: List[str]):
        verdict = {
            "decision": decision,
            "reasons": reasons,
            "round": self.round_number
        }
        self.policy_verdicts.append(verdict)
        logger.info(f"Memory [{self.session_id}]: SETU Policy Verdict: {decision}")

    def serialize(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "product_id": self.product_id,
            "buyer_goal": self.buyer_goal,
            "merchant_goal": self.merchant_goal,
            "round_number": self.round_number,
            "offers": [str(o) for o in self.offers],
            "counter_offers": [str(c) for c in self.counter_offers],
            "tool_calls": self.tool_calls,
            "observations": self.observations,
            "decisions": self.decisions,
            "policy_verdicts": self.policy_verdicts,
            "final_outcome": self.final_outcome
        }
