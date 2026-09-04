import os
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from pydantic import BaseModel

from backend.app.agents.provider import (
    LLMProvider,
    GeminiProvider,
    OpenRouterProvider,
    GroqProvider,
    MockProvider,
    MultiFallbackProvider,
    AgentProviderRouter,
    get_provider_for_agent,
    get_provider_for_task,
    ProviderExecutionMetadata,
    BuyerDecision,
    MerchantDecision
)
from backend.app.config import settings


class DummySchema(BaseModel):
    action: str
    amount: str


def test_provider_execution_metadata_fields():
    meta = ProviderExecutionMetadata(
        provider_used="groq",
        provider_type="real_llm",
        model_name="llama-3.3-70b-versatile",
        agent_role="merchant",
        fallback_used=False,
        fallback_depth=0,
        fallback_reason=None,
        response_latency_ms=123.45
    )
    assert meta.provider_used == "groq"
    assert meta.provider_type == "real_llm"
    assert meta.model_name == "llama-3.3-70b-versatile"
    assert meta.agent_role == "merchant"
    assert meta.fallback_used is False
    assert meta.fallback_depth == 0
    assert meta.response_latency_ms == 123.45


def test_mock_provider_execution():
    provider = MockProvider()
    resp = provider.generate_response("Hello", "You are an assistant", [])
    assert "text" in resp
    meta = provider.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "mock"
    assert meta.fallback_used is False


def test_buyer_multi_fallback_chain_success_primary():
    """Buyer chain: Gemini -> OpenRouter -> Groq -> Mock. Test primary (Gemini) success."""
    primary_mock = MagicMock(spec=LLMProvider)
    primary_mock.provider_name = "Gemini"
    primary_mock.model_name = "gemini-3.1-flash-lite"
    primary_mock.generate_response.return_value = {"text": "Gemini response", "tool_calls": []}
    primary_mock.last_execution_metadata = ProviderExecutionMetadata(
        provider_used="gemini",
        provider_type="real_llm",
        model_name="gemini-3.1-flash-lite",
        agent_role="buyer",
        fallback_used=False,
        fallback_depth=0,
        response_latency_ms=50.0
    )

    openrouter_mock = MagicMock(spec=LLMProvider)
    openrouter_mock.provider_name = "OpenRouter"
    groq_mock = MagicMock(spec=LLMProvider)
    groq_mock.provider_name = "Groq"
    mock_p = MockProvider()

    chain = MultiFallbackProvider(providers=[primary_mock, openrouter_mock, groq_mock, mock_p], agent_role="buyer")
    resp = chain.generate_response("Test prompt", "System instruction", [])
    assert resp["text"] == "Gemini response"
    
    meta = chain.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "gemini"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_used is False
    assert meta.fallback_depth == 0
    assert meta.agent_role == "buyer"


def test_buyer_fallback_to_openrouter_on_gemini_429():
    """Buyer chain: Gemini fails with 429 -> OpenRouter succeeds before Groq/Mock."""
    gemini_mock = MagicMock(spec=LLMProvider)
    gemini_mock.provider_name = "Gemini"
    gemini_mock.model_name = "gemini-3.1-flash-lite"
    gemini_mock.generate_response.side_effect = Exception("429 ResourceExhausted rate limit")

    openrouter_mock = MagicMock(spec=LLMProvider)
    openrouter_mock.provider_name = "OpenRouter"
    openrouter_mock.model_name = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_mock.generate_response.return_value = {"text": "OpenRouter response", "tool_calls": []}
    openrouter_mock.last_execution_metadata = ProviderExecutionMetadata(
        provider_used="openrouter",
        provider_type="real_llm",
        model_name="meta-llama/llama-3.3-70b-instruct:free",
        agent_role="buyer",
        fallback_used=False,
        fallback_depth=0,
        response_latency_ms=80.0
    )

    groq_mock = MagicMock(spec=LLMProvider)
    groq_mock.provider_name = "Groq"
    mock_p = MockProvider()

    chain = MultiFallbackProvider(providers=[gemini_mock, openrouter_mock, groq_mock, mock_p], agent_role="buyer")
    resp = chain.generate_response("Test prompt", "System instruction", [])
    assert resp["text"] == "OpenRouter response"

    meta = chain.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "openrouter"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_used is True
    assert meta.fallback_depth == 1
    assert "429" in (meta.fallback_reason or "")
    assert meta.agent_role == "buyer"


def test_merchant_multi_fallback_chain_success_primary():
    """Merchant chain: Groq -> OpenRouter -> Gemini -> Mock. Test primary (Groq) success."""
    groq_mock = MagicMock(spec=LLMProvider)
    groq_mock.provider_name = "Groq"
    groq_mock.model_name = "llama-3.3-70b-versatile"
    groq_mock.generate_response.return_value = {"text": "Groq response", "tool_calls": []}
    groq_mock.last_execution_metadata = ProviderExecutionMetadata(
        provider_used="groq",
        provider_type="real_llm",
        model_name="llama-3.3-70b-versatile",
        agent_role="merchant",
        fallback_used=False,
        fallback_depth=0,
        response_latency_ms=45.0
    )

    openrouter_mock = MagicMock(spec=LLMProvider)
    gemini_mock = MagicMock(spec=LLMProvider)
    mock_p = MockProvider()

    chain = MultiFallbackProvider(providers=[groq_mock, openrouter_mock, gemini_mock, mock_p], agent_role="merchant")
    resp = chain.generate_response("Test prompt", "System instruction", [])
    assert resp["text"] == "Groq response"

    meta = chain.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "groq"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_used is False
    assert meta.fallback_depth == 0
    assert meta.agent_role == "merchant"


def test_merchant_fallback_to_gemini_when_groq_and_openrouter_fail():
    """Merchant chain: Groq fails -> OpenRouter fails -> Gemini succeeds before Mock."""
    groq_mock = MagicMock(spec=LLMProvider)
    groq_mock.provider_name = "Groq"
    groq_mock.generate_response.side_effect = Exception("Groq 429 Rate Limit")

    openrouter_mock = MagicMock(spec=LLMProvider)
    openrouter_mock.provider_name = "OpenRouter"
    openrouter_mock.generate_response.side_effect = Exception("OpenRouter 503 Service Unavailable")

    gemini_mock = MagicMock(spec=LLMProvider)
    gemini_mock.provider_name = "Gemini"
    gemini_mock.model_name = "gemini-3.1-flash-lite"
    gemini_mock.generate_response.return_value = {"text": "Gemini fallback response", "tool_calls": []}
    gemini_mock.last_execution_metadata = ProviderExecutionMetadata(
        provider_used="gemini",
        provider_type="real_llm",
        model_name="gemini-3.1-flash-lite",
        agent_role="merchant",
        fallback_used=False,
        fallback_depth=0,
        response_latency_ms=95.0
    )

    mock_p = MockProvider()

    chain = MultiFallbackProvider(providers=[groq_mock, openrouter_mock, gemini_mock, mock_p], agent_role="merchant")
    resp = chain.generate_response("Test prompt", "System instruction", [])
    assert resp["text"] == "Gemini fallback response"

    meta = chain.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "gemini"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_used is True
    assert meta.fallback_depth == 2
    assert "Groq" in meta.fallback_reason
    assert "OpenRouter" in meta.fallback_reason
    assert meta.agent_role == "merchant"


def test_all_real_providers_fail_engages_deterministic_mock():
    """All 3 real providers fail -> Deterministic MockProvider engaged as final fallback."""
    p1 = MagicMock(spec=LLMProvider)
    p1.provider_name = "Groq"
    p1.generate_response.side_effect = Exception("Groq Error")

    p2 = MagicMock(spec=LLMProvider)
    p2.provider_name = "OpenRouter"
    p2.generate_response.side_effect = Exception("OpenRouter Error")

    p3 = MagicMock(spec=LLMProvider)
    p3.provider_name = "Gemini"
    p3.generate_response.side_effect = Exception("Gemini Error")

    mock_p = MockProvider()

    chain = MultiFallbackProvider(providers=[p1, p2, p3, mock_p], agent_role="merchant")
    resp = chain.generate_response("Search catalog electronics", "System instruction", [])
    assert "text" in resp

    meta = chain.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "mock"
    assert meta.provider_type == "deterministic_fallback"
    assert meta.fallback_used is True
    assert meta.fallback_depth == 3
    assert "Groq Error" in meta.fallback_reason
    assert "OpenRouter Error" in meta.fallback_reason
    assert "Gemini Error" in meta.fallback_reason


def test_agent_provider_isolation():
    """Verify Buyer (Gemini-primary) and Merchant (Groq-primary) get independent provider instances."""
    buyer_p = get_provider_for_agent("buyer")
    merchant_p = get_provider_for_agent("merchant")

    assert buyer_p is not merchant_p
    assert getattr(buyer_p, "agent_role", None) == "buyer"
    assert getattr(merchant_p, "agent_role", None) == "merchant"


def test_provider_status_endpoint():
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    response = client.get("/api/agent/provider-status")
    assert response.status_code == 200
    data = response.json()

    assert "buyer" in data
    assert "merchant" in data
    assert "auxiliary" in data
    assert "keys_configured" in data

    # Verify OpenAI is completely removed from keys_configured
    assert "openai" not in data["keys_configured"]
    assert "gemini" in data["keys_configured"]
    assert "groq" in data["keys_configured"]
    assert "openrouter" in data["keys_configured"]

    # Verify no private API keys are leaked in any field
    data_str = str(data)
    assert "AIzaSy" not in data_str
    assert "sk-" not in data_str
    assert "gsk_" not in data_str
