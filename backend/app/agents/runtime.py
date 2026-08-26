import logging
from typing import Dict, Any, List, Optional, Type
from decimal import Decimal
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from backend.app.agents.provider import LLMProvider, BuyerDecision, MerchantDecision
from backend.app.audit import AuditEngine

logger = logging.getLogger("setu.agents.runtime")

class ToolArgs(BaseModel):
    query: Optional[str] = Field(default=None, description="Search query string")
    category: Optional[str] = Field(default=None, description="Filter category")
    product_id: Optional[int] = Field(default=None, description="Target product ID")
    product_ids: Optional[List[int]] = Field(default=None, description="List of target product IDs")
    proposed_price: Optional[str] = Field(default=None, description="Offered deal amount decimal string")
    budget: Optional[str] = Field(default=None, description="Maximum budget decimal string")
    discount_percent: Optional[str] = Field(default=None, description="Proposed discount percentage")
    quantity: Optional[int] = Field(default=None, description="Quantity of items")

class AgentActionProposal(BaseModel):
    call_tool: Optional[str] = Field(default=None, description="The name of the tool to execute, if any. Must be one of the permitted tools.")
    tool_args: Optional[ToolArgs] = Field(default=None, description="Arguments for the tool call, if executing a tool.")
    final_decision: Optional[Dict[str, Any]] = Field(default=None, description="The final structured decision dictionary matching either BuyerDecision or MerchantDecision schema.")
    reasoning: str = Field(..., description="Explain your chain of thought: what information you are seeking or how you arrived at this final price proposal.")
    confidence: float = Field(default=1.0, description="Your confidence score in this step (0.0 to 1.0).")

def get_action_proposal_schema(decision_class: Type[BaseModel]) -> Type[BaseModel]:
    class AgentActionProposal(BaseModel):
        call_tool: Optional[str] = Field(default=None, description="The name of the tool to execute, if any. Must be one of the permitted tools.")
        tool_args: Optional[ToolArgs] = Field(default=None, description="Arguments for the tool call, if executing a tool.")
        final_decision: Optional[decision_class] = Field(default=None, description="The final structured decision object.")
        reasoning: str = Field(..., description="Explain your chain of thought: what information you are seeking or how you arrived at this final price proposal.")
        confidence: float = Field(default=1.0, description="Your confidence score in this step (0.0 to 1.0).")
    
    AgentActionProposal.__name__ = "AgentActionProposal"
    return AgentActionProposal


def execute_agent_loop(
    db: Session,
    agent: Any,
    provider: LLMProvider,
    memory: Any,
    prompt: str,
    schema_class: Type[BaseModel],
    max_tool_steps: int = 5
) -> BaseModel:
    """
    Executes a genuine OBSERVE -> REASON -> TOOL -> OBSERVE inner loop.
    Enforces retry boundaries, validates tools against registries, and intercepts unsafe calls.
    """
    actor_name = agent.role  # BUYER_AGENT or MERCHANT_AGENT
    allowed_tools = list(agent.registry.tools.keys())
    action_proposal_class = get_action_proposal_schema(schema_class)

    round_tool_calls = []
    round_observations = []
    
    retry_count = 0
    max_retries = 3

    for step_idx in range(1, max_tool_steps + 1):
        # Log thinking state
        AuditEngine.log_event(
            db=db,
            actor=actor_name,
            action=f"{actor_name}_THINKING",
            result="SUCCESS",
            reason=f"Agent inner reasoning step {step_idx} started."
        )

        # Build context from previous steps in this round
        history_lines = []
        for idx, (tc, obs) in enumerate(zip(round_tool_calls, round_observations)):
            history_lines.append(f"Step {idx+1}: Called '{tc['tool_name']}' with args {tc['args']}. Observation: {obs['result']}")
        history_context = "\n".join(history_lines)

        tool_specs = []
        for name in allowed_tools:
            _, schema = agent.registry.tools[name]
            tool_specs.append(f"- Tool: {name}\n  Description: {schema.get('description')}\n  Parameters: {schema.get('parameters')}")
        tool_specs_context = "\n".join(tool_specs)

        step_prompt = (
            f"{prompt}\n\n"
            f"=== Inner Reasoning Step {step_idx} ===\n"
            f"Allowed Tools and Specifications:\n{tool_specs_context}\n\n"
            f"History of tools executed in this round so far:\n{history_context or 'None'}\n\n"
            f"Please return a JSON matching the AgentActionProposal schema.\n"
            f"You can choose to call a tool to gather information by setting 'call_tool' to a name in Allowed Tools.\n"
            f"Make sure to specify valid arguments matching the tool parameters schema in 'tool_args' if calling a tool.\n"
            f"If you have gathered all necessary information to make a final offer, counter-offer, acceptance, or rejection, "
            f"please set 'final_decision' to match the final decision schema format (with action, product_id, quantity, unit_price, total_amount, rationale, and metric checks)."
        )

        try:
            proposal = provider.generate_structured_response(
                step_prompt, 
                agent.system_instruction, 
                action_proposal_class
            )
        except Exception as e:
            import json
            if isinstance(e, (ValidationError, TypeError, json.JSONDecodeError)):
                logger.warning(f"Validation failure in step {step_idx}: {e}")
                retry_count += 1
                if retry_count > max_retries:
                    logger.error("Maximum retry limit exceeded during agent structured generation.")
                    break
                continue
            else:
                raise e

        # Option A: Execute Tool
        if proposal.call_tool:
            tool_name = proposal.call_tool
            if proposal.tool_args:
                if hasattr(proposal.tool_args, "model_dump"):
                    tool_args = {k: v for k, v in proposal.tool_args.model_dump().items() if v is not None}
                else:
                    tool_args = {k: v for k, v in proposal.tool_args.dict().items() if v is not None}
            else:
                tool_args = {}

            # Strict security allowlist enforcement
            if tool_name not in allowed_tools:
                obs_result = f"Error: Tool '{tool_name}' is not allowlisted for this agent runtime."
                memory.add_tool_call(actor_name, tool_name, tool_args)
                memory.add_observation(actor_name, tool_name, obs_result)
                round_tool_calls.append({"tool_name": tool_name, "args": tool_args})
                round_observations.append({"result": obs_result})
                continue

            # Log Tool Call event
            AuditEngine.log_event(
                db=db,
                actor=actor_name,
                action=f"{actor_name}_TOOL_CALL",
                result="SUCCESS",
                reason=f"Executed allowlisted tool: {tool_name}",
                metadata={"tool_name": tool_name, "args": tool_args}
            )

            # Record call to session memory
            memory.add_tool_call(actor_name, tool_name, tool_args)

            try:
                # Execute the tool
                result = agent.registry.execute_tool(tool_name, db, **tool_args)
                obs_result = result
            except Exception as ex:
                obs_result = f"Execution Error: {str(ex)}"

            # Log Tool Result event
            AuditEngine.log_event(
                db=db,
                actor=actor_name,
                action=f"{actor_name}_TOOL_RESULT",
                result="SUCCESS" if "Error" not in str(obs_result) else "FAIL",
                reason=f"Observed result from tool: {tool_name}",
                metadata={"tool_name": tool_name, "result": str(obs_result)}
            )

            # Record observation to session memory
            memory.add_observation(actor_name, tool_name, obs_result)

            round_tool_calls.append({"tool_name": tool_name, "args": tool_args})
            round_observations.append({"result": obs_result})

        # Option B: Conclude thinking with Final Decision
        elif proposal.final_decision:
            decision_dict = proposal.final_decision
            try:
                # Validate the final decision schema
                if isinstance(decision_dict, schema_class):
                    decision_obj = decision_dict
                elif isinstance(decision_dict, dict):
                    decision_obj = schema_class(**decision_dict)
                else:
                    # Fallback parse
                    decision_obj = schema_class.parse_obj(decision_dict)
                
                # Log final proposal selection in memory
                memory.add_decision(
                    actor_name,
                    decision_obj.action,
                    decision_obj.total_amount,
                    decision_obj.rationale,
                    proposal.confidence
                )
                
                # Expose confidence/reasoning metadata to agent class if needed
                agent.last_confidence = proposal.confidence
                agent.last_reasoning = proposal.reasoning
                agent.tools_called_in_session = list(set(agent.tools_called_in_session + [tc["tool_name"] for tc in round_tool_calls]))
                
                return decision_obj
            except ValidationError as ve:
                logger.warning(f"Final decision validation failed: {ve}")
                round_tool_calls.append({"tool_name": "validation_check", "args": {}})
                round_observations.append({"result": f"Validation Error: final_decision fields are malformed or invalid: {ve}. Please correct the parameters."})
                retry_count += 1
                if retry_count > max_retries:
                    break
        else:
            # Fallback if both are empty
            round_tool_calls.append({"tool_name": "no_action", "args": {}})
            round_observations.append({"result": "Error: You must either specify call_tool or final_decision in your step proposal."})

    # Default fallback REJECT if loop terminates without agreeing or validates incorrectly
    logger.warning("Agent reasoning loop timed out or failed validation. Returning default REJECT decision.")
    if schema_class == BuyerDecision:
        return BuyerDecision(
            action="REJECT",
            product_id=agent.registry.execute_tool("search_catalog", db)[0]["id"] if allowed_tools else 1,
            quantity=1,
            unit_price=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            rationale="Agent loop timed out without formulating a valid structured decision proposal.",
            constraints_checked=["timeout_safety"]
        )
    else:
        return MerchantDecision(
            action="REJECT",
            product_id=1,
            quantity=1,
            unit_price=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            rationale="Agent loop timed out without formulating a valid merchant decision.",
            margin_check="Margin check: FAILED due to timeout exception."
        )
