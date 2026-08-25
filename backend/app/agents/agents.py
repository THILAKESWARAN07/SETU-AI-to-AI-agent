from backend.app.agents.provider import LLMProvider, MockProvider, MockLLMProvider
from backend.app.agents.tools import ToolRegistry, SecurityError
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent

# For backward compatibility, map Agent to BuyerAgent or expose it
Agent = BuyerAgent

def get_buyer_agent(provider=None) -> BuyerAgent:
    """
    Returns an instance of the Buyer Agent configured with the given provider.
    """
    return BuyerAgent(provider)

def get_merchant_agent(provider=None) -> MerchantAgent:
    """
    Returns an instance of the Merchant Agent configured with the given provider.
    """
    return MerchantAgent(provider)
