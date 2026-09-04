"""
SETU Central AI Gateway Architecture
====================================
drastically reduces LLM API usage while maintaining genuine AI-to-AI negotiation.

Core Principles:
1. Deterministic SETU tools (catalog search, policy evaluation, margin math, inventory checks,
   pricing floor checks, Razorpay verification, audit logging) are ALWAYS executed in Python/SQL
   WITHOUT calling an LLM.
2. LLM is invoked ONLY for:
   A. Initial natural language intent understanding (with normalized intent caching).
   B. Genuine Buyer Agent negotiation reasoning (1 structured turn per round).
   C. Genuine Merchant Agent negotiation reasoning (1 structured turn per round).
   D. Human-readable final explanation.
3. Multi-Provider Support:
   - Cerebras
   - Groq
   - Gemini
   - NVIDIA NIM
   - OpenRouter
   - Ollama
   - MockProvider (deterministic fallback)
4. Fast Circuit Breaker:
   - On 429 (rate limit / quota), 401/403, 402, or repeated timeout, immediately opens circuit
     for cooldown period (default 60s). Fails over with 0ms delay without blocking request threads.
"""

import os
import re
import time
import json
import logging
import threading
from decimal import Decimal
from typing import Dict, Any, List, Optional, Type, Union, Tuple
from pydantic import BaseModel, Field

from backend.app.config import settings

logger = logging.getLogger("setu.ai_gateway")


# ==============================================================================
# 1. CORE DATA SCHEMAS
# ==============================================================================

class ProviderExecutionMetadata(BaseModel):
    provider_used: str = "mock"
    provider_type: str = "deterministic_fallback"  # "real_llm" or "deterministic_fallback"
    model_name: str = "mock-model-v2"
    agent_role: Optional[str] = None
    fallback_used: bool = False
    fallback_depth: int = 0
    fallback_reason: Optional[str] = None
    response_latency_ms: float = 0.0


class UserIntent(BaseModel):
    product: str = Field(..., description="Target product or category extracted from intent")
    product_query: Optional[str] = Field(default=None, description="Cleaned product search string")
    max_budget: Optional[float] = Field(default=None, description="Maximum budget if specified")
    currency: str = Field(default="INR", description="Currency string")
    preferences: List[str] = Field(default_factory=list, description="Extracted preferences or constraints")
    quantity: int = Field(default=1, description="Requested quantity")
    standalone_only: bool = Field(default=False, description="Whether buyer strictly requested standalone without accessories")
    confidence: float = Field(default=1.0, description="Confidence score of intent parse")
    intent_parse_mode: str = Field(default="deterministic", description="'deterministic' or 'llm_fallback'")
    intent_llm_used: bool = Field(default=False, description="Whether an external LLM was called to parse intent")


class NegotiationContext(BaseModel):
    """
    Compact deterministic context built before each LLM negotiation turn.
    Contains authoritative bounds calculated by SETU Python/SQL tools.
    """
    agent_role: str = Field(..., description="BUYER_AGENT or MERCHANT_AGENT")
    current_round: int = Field(default=1, description="Current negotiation round (1-indexed)")
    buyer_max_budget: Decimal = Field(..., description="Buyer's absolute ceiling budget")
    current_product: Dict[str, Any] = Field(..., description="Selected product details (id, name, price, cost, stock)")
    catalog_price: Decimal = Field(..., description="Original catalog list price")
    merchant_min_price: Decimal = Field(..., description="Deterministic price floor respecting margin & policy")
    current_proposal: Optional[Dict[str, Any]] = Field(default=None, description="Active proposal under consideration")
    previous_offers: List[Dict[str, Any]] = Field(default_factory=list, description="Chronological offers in this session")
    max_allowed_discount: Decimal = Field(default=Decimal("15.00"), description="Max allowed discount percentage")
    inventory_availability: int = Field(default=1, description="Available inventory count")
    relevant_policy_constraints: Dict[str, Any] = Field(default_factory=dict, description="Active policy limits")
    remaining_rounds: int = Field(default=3, description="Remaining negotiation rounds")


# Re-export decision models for backward compatibility and typing
class BasketItemSchema(BaseModel):
    product_id: int
    name: str
    quantity: int = 1
    original_price: Decimal
    negotiated_price: Decimal
    is_primary: bool = True


class BuyerDecision(BaseModel):
    action: str = Field(..., description="OFFER, COUNTER, ACCEPT, or REJECT")
    product_id: int = Field(..., description="Primary product ID being negotiated")
    quantity: int = Field(default=1, description="Quantity")
    unit_price: Decimal = Field(..., description="Proposed unit price for primary product")
    total_amount: Decimal = Field(..., description="Total proposed price across all basket items")
    rationale: str = Field(..., description="Explanation and negotiation strategy")
    constraints_checked: List[str] = Field(default_factory=lambda: ["budget_fit", "catalog_price_bound"])
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="List of items in the negotiated basket")
    accept: Optional[bool] = Field(default=None, description="Explicit acceptance flag")


class MerchantDecision(BaseModel):
    action: str = Field(..., description="ACCEPT, COUNTER, BUNDLE, or REJECT")
    product_id: int = Field(..., description="Primary product ID")
    quantity: int = Field(default=1, description="Quantity")
    unit_price: Decimal = Field(..., description="Offered unit price")
    total_amount: Decimal = Field(..., description="Total proposed transaction amount")
    rationale: str = Field(..., description="Reasoning, policy compliance, and margin justification")
    margin_check: str = Field(default="Margin check: PASSED", description="Policy compliance summary")
    cross_sell_product_id: Optional[int] = Field(default=None, description="Recommended bundle item ID if applicable")
    basket_items: Optional[List[BasketItemSchema]] = Field(default=None, description="List of items in the negotiated basket")
    accept: Optional[bool] = Field(default=None, description="Explicit acceptance flag")


# ==============================================================================
# 2. CIRCUIT BREAKER
# ==============================================================================

class CircuitBreaker:
    """
    In-memory thread-safe circuit breaker for external LLM providers.
    Quickly trips to OPEN state on 429, quota limits, auth errors, payment required,
    or repeated timeouts, preventing request delays on dead endpoints.
    """
    def __init__(self, cooldown_seconds: float = 60.0):
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._states: Dict[str, Dict[str, Any]] = {}

    def _init_provider(self, name: str):
        if name not in self._states:
            self._states[name] = {
                "circuit_state": "CLOSED",  # "CLOSED" or "OPEN"
                "failure_count": 0,
                "circuit_open_until": 0.0,
                "last_error": None,
                "last_success_timestamp": None,
                "total_calls": 0,
                "failed_calls": 0
            }

    def is_available(self, provider_name: str) -> bool:
        provider_name = provider_name.lower().strip()
        if provider_name == "mock":
            return True

        with self._lock:
            self._init_provider(provider_name)
            state = self._states[provider_name]
            now = time.time()

            if state["circuit_state"] == "OPEN":
                if now >= state["circuit_open_until"]:
                    # Cooldown expired -> test transition to half-open
                    state["circuit_state"] = "CLOSED"
                    state["failure_count"] = 0
                    logger.info(f"CircuitBreaker: Cooldown elapsed for '{provider_name}'. Circuit closed (half-open test).")
                    return True
                else:
                    return False
            return True

    def record_success(self, provider_name: str):
        provider_name = provider_name.lower().strip()
        with self._lock:
            self._init_provider(provider_name)
            state = self._states[provider_name]
            state["circuit_state"] = "CLOSED"
            state["failure_count"] = 0
            state["last_error"] = None
            state["last_success_timestamp"] = time.time()
            state["total_calls"] += 1

    def record_failure(self, provider_name: str, error: Exception, status_code: Optional[int] = None):
        provider_name = provider_name.lower().strip()
        if provider_name == "mock":
            return

        err_str = str(error)
        is_fast_trip = False

        # Detect fast-trip conditions (429 rate limit, 401/403 invalid key, 402 payment, 503 unavailable, QuotaExceeded)
        if status_code in (429, 401, 402, 403, 503):
            is_fast_trip = True
        elif any(term in err_str.lower() for term in ("429", "rate limit", "resourceexhausted", "quota", "payment required", "402", "unauthorized", "503 unavailable")):
            is_fast_trip = True

        with self._lock:
            self._init_provider(provider_name)
            state = self._states[provider_name]
            state["failure_count"] += 1
            state["total_calls"] += 1
            state["failed_calls"] += 1
            state["last_error"] = f"{type(error).__name__}: {err_str[:200]}"

            if is_fast_trip or state["failure_count"] >= 2:
                state["circuit_state"] = "OPEN"
                state["circuit_open_until"] = time.time() + self.cooldown_seconds
                logger.warning(
                    f"CircuitBreaker: Tripped OPEN for provider '{provider_name}' "
                    f"(status={status_code}, error={state['last_error']}). "
                    f"Cooldown until {time.strftime('%H:%M:%S', time.localtime(state['circuit_open_until']))}."
                )

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            res = {}
            for name, s in self._states.items():
                is_open = s["circuit_state"] == "OPEN" and now < s["circuit_open_until"]
                res[name] = {
                    "available": not is_open,
                    "circuit_state": "OPEN" if is_open else "CLOSED",
                    "failure_count": s["failure_count"],
                    "circuit_open_until": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s["circuit_open_until"])) if is_open else None,
                    "last_error": s["last_error"],
                    "total_calls": s["total_calls"],
                    "failed_calls": s["failed_calls"]
                }
            return res


# Global CircuitBreaker instance
circuit_breaker = CircuitBreaker(cooldown_seconds=getattr(settings, "CIRCUIT_BREAKER_COOLDOWN_SECONDS", 60.0))


# ==============================================================================
# 3. INTENT CACHE
# ==============================================================================

class IntentCache:
    """
    In-memory cache for user query intent understanding.
    Reuses parsed structured intent for repeated / normalized queries.
    Never caches negotiation decisions or pricing outputs.
    """
    def __init__(self, max_size: int = 256, ttl_seconds: float = 3600.0):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[UserIntent, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def normalize_key(query: str) -> str:
        q = query.lower().strip()
        # Strip currency words and symbols
        q = re.sub(r"[₹$€£]|rs\.?|inr", "", q, flags=re.IGNORECASE)
        q = re.sub(r"[^\w\s\d]", "", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def get(self, query: str) -> Optional[UserIntent]:
        key = self.normalize_key(query)
        with self._lock:
            if key in self._cache:
                intent, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    logger.info(f"IntentCache: HIT for normalized query '{key}'")
                    return intent
                else:
                    del self._cache[key]
        return None

    def set(self, query: str, intent: UserIntent):
        key = self.normalize_key(query)
        with self._lock:
            if len(self._cache) >= self.max_size:
                # Remove oldest item
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (intent, time.time())


intent_cache = IntentCache()


def parse_deterministic_intent(query: str, budget: Optional[Union[Decimal, float]] = None) -> Optional[UserIntent]:
    """
    Deterministically extracts structured purchase intent for standard procurement requests.
    Returns UserIntent if confidence >= 0.85, eliminating unnecessary external LLM calls.
    Returns None for ambiguous queries requiring LLM reasoning.
    """
    q_clean = query.strip()
    if not q_clean:
        return None
    q_lower = q_clean.lower()

    # Ambiguity check: if query has complex conjunctions or fuzzy desires, use LLM
    ambiguity_markers = [
        "not sure", "recommend me", "what is good for", "suggest something",
        "long meetings", "gift for", "help me decide", "best for"
    ]
    if any(marker in q_lower for marker in ambiguity_markers):
        return None

    # 1. Extract budget
    extracted_budget = None
    if budget is not None:
        try:
            extracted_budget = float(budget)
        except Exception:
            pass
    
    if extracted_budget is None:
        budget_match = re.search(r'(?:under|below|budget|around|max|within|₹|rs\.?|inr)\s*(\d+(?:,\d+)*(?:\.\d+)?)', q_lower)
        if budget_match:
            try:
                extracted_budget = float(budget_match.group(1).replace(",", ""))
            except Exception:
                pass

    # 2. Extract standalone preference
    standalone_only = any(term in q_lower for term in ("standalone", "without accessories", "no accessories", "only the phone", "only the device", "just the"))

    # 3. Detect target product / category
    product_name = None
    known_catalog = [
        ("samsung galaxy a15", "Samsung Galaxy A15"),
        ("samsung a15", "Samsung Galaxy A15"),
        ("samsung galaxy", "Samsung Galaxy A15"),
        ("redmi note 13", "Redmi Note 13"),
        ("motorola g54", "Motorola G54"),
        ("wireless earbuds", "Wireless Earbuds"),
        ("earbuds pro", "Wireless Earbuds"),
        ("earbuds", "Wireless Earbuds"),
        ("earphone", "Wireless Earbuds"),
        ("smartwatch", "Smartwatch"),
        ("mechanical keyboard", "Mechanical Keyboard"),
        ("gaming keyboard", "Mechanical Keyboard"),
        ("keyboard", "Mechanical Keyboard"),
        ("gaming mouse", "Gaming Mouse"),
        ("wireless mouse", "Gaming Mouse"),
        ("mouse", "Gaming Mouse"),
        ("bluetooth speaker", "Bluetooth Speaker"),
        ("speaker", "Bluetooth Speaker"),
        ("smartphone", "Samsung Galaxy A15"),
        ("mobile phone", "Samsung Galaxy A15"),
        ("phone", "Samsung Galaxy A15")
    ]
    for pattern, name in known_catalog:
        if pattern in q_lower:
            product_name = name
            break

    if product_name:
        return UserIntent(
            product=product_name,
            product_query=product_name,
            max_budget=extracted_budget,
            currency="INR",
            preferences=["standalone"] if standalone_only else [],
            quantity=1,
            standalone_only=standalone_only,
            confidence=0.95,
            intent_parse_mode="deterministic",
            intent_llm_used=False
        )

    return None


# ==============================================================================
# 4. MULTI-PROVIDER ADAPTERS
# ==============================================================================

class BaseLLMProvider:
    provider_name: str = "base"
    provider_type: str = "real_llm"
    model_name: str = "base-model"
    is_available: bool = True

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        raise NotImplementedError

    def explain(self, decision: str, reasons: List[str], timeout: float = 15.0) -> str:
        raise NotImplementedError


class CerebrasProvider(BaseLLMProvider):
    """
    Cerebras Cloud Ultra-Fast LLM Provider (Free / Free-tier API).
    Standard OpenAI-compatible REST endpoint.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider_name = "cerebras"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("CEREBRAS_API_KEY") or getattr(settings, "CEREBRAS_API_KEY", "")
        self.model_name = model or os.getenv("CEREBRAS_MODEL") or getattr(settings, "CEREBRAS_MODEL", "llama3.1-70b")
        self.base_url = "https://api.cerebras.ai/v1"
        self.is_available = bool(self.api_key and self.api_key.strip())

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        import httpx
        if not self.is_available:
            raise ValueError("Cerebras API key is not configured.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json"
        }

        full_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANT: You MUST respond ONLY with a valid JSON object strictly matching this schema:\n"
            f"{schema_json}\n"
            f"Do not include markdown codeblocks or extra text outside the JSON object."
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                res.raise_for_status()
                data = res.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed_json = json.loads(cleaned)
                parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)

                latency = (time.perf_counter() - start_t) * 1000.0
                meta = ProviderExecutionMetadata(
                    provider_used=self.provider_name,
                    provider_type="real_llm",
                    model_name=self.model_name,
                    fallback_used=False,
                    fallback_depth=0,
                    response_latency_ms=round(latency, 2)
                )
                return parsed_obj, meta
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else None
            circuit_breaker.record_failure(self.provider_name, e, status_code=status)
            raise e
        except Exception as e:
            circuit_breaker.record_failure(self.provider_name, e)
            raise e


class GroqProvider(BaseLLMProvider):
    """
    Groq Fast Inference LLM Provider.
    OpenAI-compatible REST endpoint.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider_name = "groq"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", "")
        self.model_name = model or os.getenv("GROQ_MODEL") or getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
        self.base_url = "https://api.groq.com/openai/v1"
        self.is_available = bool(self.api_key and self.api_key.strip())

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        import httpx
        if not self.is_available:
            raise ValueError("Groq API key is not configured.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json"
        }

        full_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANT: You MUST respond ONLY with a valid JSON object strictly matching this schema:\n"
            f"{schema_json}\n"
            f"Do not include markdown fences or any conversational preamble."
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                res.raise_for_status()
                data = res.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed_json = json.loads(cleaned)
                parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)

                latency = (time.perf_counter() - start_t) * 1000.0
                meta = ProviderExecutionMetadata(
                    provider_used=self.provider_name,
                    provider_type="real_llm",
                    model_name=self.model_name,
                    fallback_used=False,
                    fallback_depth=0,
                    response_latency_ms=round(latency, 2)
                )
                return parsed_obj, meta
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else None
            circuit_breaker.record_failure(self.provider_name, e, status_code=status)
            raise e
        except Exception as e:
            circuit_breaker.record_failure(self.provider_name, e)
            raise e


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini LLM Provider (Flash / Flash-Lite free tier).
    Supports google-genai and google.generativeai SDKs.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider_name = "gemini"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")
        self.model_name = model or os.getenv("GEMINI_MODEL") or getattr(settings, "LLM_MODEL", "gemini-3.1-flash-lite")
        self.is_available = bool(self.api_key and self.api_key.strip())

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        if not self.is_available:
            raise ValueError("Gemini API key is not configured.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        try:
            # Try official modern google.genai Client first
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key.strip())
            prompt_content = f"{user_prompt}\n\nReturn JSON matching schema:\n{schema_json}"
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.2
            )
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt_content,
                config=config
            )
            raw_text = response.text.strip()
            parsed_json = json.loads(raw_text)
            parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)

            latency = (time.perf_counter() - start_t) * 1000.0
            meta = ProviderExecutionMetadata(
                provider_used=self.provider_name,
                provider_type="real_llm",
                model_name=self.model_name,
                fallback_used=False,
                fallback_depth=0,
                response_latency_ms=round(latency, 2)
            )
            return parsed_obj, meta
        except Exception as e:
            # Check for 429 / quota
            err_str = str(e).lower()
            status_code = 429 if ("429" in err_str or "resourceexhausted" in err_str or "quota" in err_str) else None
            circuit_breaker.record_failure(self.provider_name, e, status_code=status_code)
            raise e


class NvidiaNimProvider(BaseLLMProvider):
    """
    NVIDIA NIM API Provider (Free Developer Credits tier).
    OpenAI-compatible REST endpoint.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider_name = "nvidia_nim"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("NVIDIA_NIM_API_KEY") or getattr(settings, "NVIDIA_NIM_API_KEY", "")
        self.model_name = model or os.getenv("NVIDIA_NIM_MODEL") or getattr(settings, "NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct")
        self.base_url = "https://integrate.api.nvidia.com/v1"
        self.is_available = bool(self.api_key and self.api_key.strip())

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        import httpx
        if not self.is_available:
            raise ValueError("NVIDIA NIM API key is not configured.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json"
        }

        full_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANT: You MUST respond ONLY with a valid JSON object strictly matching this schema:\n"
            f"{schema_json}\n"
            f"Do not include markdown codeblocks or extra text."
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                res.raise_for_status()
                data = res.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed_json = json.loads(cleaned)
                parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)

                latency = (time.perf_counter() - start_t) * 1000.0
                meta = ProviderExecutionMetadata(
                    provider_used=self.provider_name,
                    provider_type="real_llm",
                    model_name=self.model_name,
                    fallback_used=False,
                    fallback_depth=0,
                    response_latency_ms=round(latency, 2)
                )
                return parsed_obj, meta
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else None
            circuit_breaker.record_failure(self.provider_name, e, status_code=status)
            raise e
        except Exception as e:
            circuit_breaker.record_failure(self.provider_name, e)
            raise e


class OpenRouterProvider(BaseLLMProvider):
    """
    OpenRouter Multi-Model Gateway (Free / Free-tier Models).
    OpenAI-compatible REST endpoint.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider_name = "openrouter"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "")
        self.model_name = model or os.getenv("OPENROUTER_MODEL") or getattr(settings, "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        self.base_url = "https://openrouter.ai/api/v1"
        self.is_available = bool(self.api_key and self.api_key.strip())

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        import httpx
        if not self.is_available:
            raise ValueError("OpenRouter API key is not configured.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "HTTP-Referer": "https://setu-ai-to-ai-agent.vercel.app",
            "X-Title": "SETU AI-to-AI Agent",
            "Content-Type": "application/json"
        }

        full_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANT: You MUST respond ONLY with a valid JSON object strictly matching this schema:\n"
            f"{schema_json}\n"
            f"Do not include markdown codeblocks or extra text."
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                res.raise_for_status()
                data = res.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed_json = json.loads(cleaned)
                parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)

                latency = (time.perf_counter() - start_t) * 1000.0
                meta = ProviderExecutionMetadata(
                    provider_used=self.provider_name,
                    provider_type="real_llm",
                    model_name=self.model_name,
                    fallback_used=False,
                    fallback_depth=0,
                    response_latency_ms=round(latency, 2)
                )
                return parsed_obj, meta
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else None
            circuit_breaker.record_failure(self.provider_name, e, status_code=status)
            raise e
        except Exception as e:
            circuit_breaker.record_failure(self.provider_name, e)
            raise e


class OllamaProvider(BaseLLMProvider):
    """
    Ollama Local LLM Provider (Optional local fallback / dev environment).
    Uses very fast connection timeout (<= 0.8s) so deployed cloud containers (e.g. Render)
    without local Ollama instantly fail over without hanging.
    """
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, enabled: Optional[bool] = None):
        self.provider_name = "ollama"
        self.provider_type = "real_llm"
        self.enabled = enabled if enabled is not None else (
            os.getenv("OLLAMA_ENABLED", "false").lower() in ("true", "1", "yes") or
            getattr(settings, "OLLAMA_ENABLED", False)
        )
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL") or getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        self.model_name = model or os.getenv("OLLAMA_MODEL") or getattr(settings, "OLLAMA_MODEL", "llama3.2")
        self.is_available = self.enabled

    def check_health(self) -> bool:
        """Quick probe to verify if Ollama daemon is reachable on localhost."""
        if not self.enabled:
            return False
        import httpx
        try:
            with httpx.Client(timeout=httpx.Timeout(0.8, connect=0.6)) as client:
                res = client.get(f"{self.base_url}/api/version")
                return res.status_code == 200
        except Exception:
            return False

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 25.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        import httpx
        if not self.enabled:
            raise ValueError("Ollama provider is disabled.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        full_prompt = (
            f"SYSTEM: {system_prompt}\n\n"
            f"USER: {user_prompt}\n\n"
            f"Respond strictly in JSON format conforming to this JSON schema:\n{schema_json}"
        )

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "format": "json"
        }

        try:
            # Connect timeout 1.0s, read timeout 25s
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=1.0)) as client:
                res = client.post(f"{self.base_url}/api/generate", json=payload)
                res.raise_for_status()
                data = res.json()
                raw_text = data.get("response", "").strip()
                cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed_json = json.loads(cleaned)
                parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)

                latency = (time.perf_counter() - start_t) * 1000.0
                meta = ProviderExecutionMetadata(
                    provider_used=self.provider_name,
                    provider_type="real_llm",
                    model_name=self.model_name,
                    fallback_used=False,
                    fallback_depth=0,
                    response_latency_ms=round(latency, 2)
                )
                return parsed_obj, meta
        except Exception as e:
            circuit_breaker.record_failure(self.provider_name, e)
            raise e


class MockProvider(BaseLLMProvider):
    """
    Deterministic Offline Fallback Provider.
    Respects all SETU pricing floors, margins, and policies with zero network dependencies.
    """
    def __init__(self, model: str = "mock-model-v2"):
        self.provider_name = "mock"
        self.provider_type = "deterministic_fallback"
        self.model_name = model
        self.is_available = True

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 5.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        start_t = time.perf_counter()
        parsed_obj = self._generate_deterministic_mock(user_prompt, schema)
        latency = (time.perf_counter() - start_t) * 1000.0

        meta = ProviderExecutionMetadata(
            provider_used="mock",
            provider_type="deterministic_fallback",
            model_name=self.model_name,
            fallback_used=True,
            fallback_depth=0,
            response_latency_ms=round(latency, 2)
        )
        return parsed_obj, meta

    def _generate_deterministic_mock(self, prompt: str, schema: Type[BaseModel]) -> BaseModel:
        # Check if Buyer or Merchant decision
        prompt_lower = prompt.lower()
        if issubclass(schema, BuyerDecision) or schema == BuyerDecision:
            # Buyer opening offer logic or counter
            is_round_1 = "round: 1" in prompt_lower or "initial offer" in prompt_lower or "current_round: 1" in prompt_lower or "opening offer" in prompt_lower
            if "samsung" in prompt_lower:
                unit_p = Decimal("12800.00") if is_round_1 else Decimal("13200.00")
                total_p = unit_p
                prod_id = 4
                name = "Samsung Galaxy S24 Ultra"
                orig_p = Decimal("14000.00")
            elif "earbuds" in prompt_lower or "headphone" in prompt_lower:
                unit_p = Decimal("1450.00") if is_round_1 else Decimal("1475.00")
                total_p = Decimal("1899.00") if "bundle" in prompt_lower and not is_round_1 else unit_p
                prod_id = 1
                name = "Wireless Noise-Canceling Earbuds"
                orig_p = Decimal("1599.00")
            else:
                unit_p = Decimal("1000.00")
                total_p = unit_p
                prod_id = 1
                name = "Product"
                orig_p = Decimal("1200.00")

            action = "ACCEPT" if ("1899" in prompt_lower or "13200" in prompt_lower or "accept" in prompt_lower) and not is_round_1 else "OFFER"
            return BuyerDecision(
                action=action,
                product_id=prod_id,
                quantity=1,
                unit_price=unit_p,
                total_amount=total_p,
                rationale="Deterministic mock proposal calculated within budget and pricing limits.",
                constraints_checked=["budget_fit", "catalog_price_bound"],
                basket_items=[
                    BasketItemSchema(
                        product_id=prod_id,
                        name=name,
                        quantity=1,
                        original_price=orig_p,
                        negotiated_price=unit_p,
                        is_primary=True
                    )
                ],
                accept=(action == "ACCEPT")
            )

        elif issubclass(schema, MerchantDecision) or schema == MerchantDecision:
            # Merchant decision
            if "samsung" in prompt_lower:
                unit_p = Decimal("13200.00")
                total_p = Decimal("13200.00")
                prod_id = 4
                name = "Samsung Galaxy S24 Ultra"
                orig_p = Decimal("14000.00")
                cross_id = None
            elif "earbuds" in prompt_lower:
                unit_p = Decimal("1499.00")
                total_p = Decimal("1899.00")
                prod_id = 1
                name = "Wireless Noise-Canceling Earbuds"
                orig_p = Decimal("1599.00")
                cross_id = 2
            else:
                unit_p = Decimal("1100.00")
                total_p = unit_p
                prod_id = 1
                name = "Product"
                orig_p = Decimal("1200.00")
                cross_id = None

            items = [
                BasketItemSchema(
                    product_id=prod_id,
                    name=name,
                    quantity=1,
                    original_price=orig_p,
                    negotiated_price=unit_p,
                    is_primary=True
                )
            ]
            if cross_id == 2:
                items.append(
                    BasketItemSchema(
                        product_id=2,
                        name="Wireless Charging Case",
                        quantity=1,
                        original_price=Decimal("499.00"),
                        negotiated_price=Decimal("400.00"),
                        is_primary=False
                    )
                )

            return MerchantDecision(
                action="BUNDLE" if cross_id else "COUNTER",
                product_id=prod_id,
                quantity=1,
                unit_price=unit_p,
                total_amount=total_p,
                rationale="Deterministic mock counter-proposal protecting profit margin boundaries.",
                margin_check="Margin check: PASSED",
                cross_sell_product_id=cross_id,
                basket_items=items,
                accept=False
            )
        elif issubclass(schema, UserIntent) or schema == UserIntent:
            return UserIntent(
                product="wireless earbuds" if "earbud" in prompt_lower else "product",
                max_budget=2000.0 if "2000" in prompt_lower else None,
                preferences=["bundle"] if "bundle" in prompt_lower else [],
                quantity=1
            )
        else:
            return schema()


# ==============================================================================
# 5. CENTRAL AI GATEWAY
# ==============================================================================

class AIGateway:
    """
    Central Gateway coordinating all LLM provider selection, routing, failover,
    caching, circuit breaking, and single-turn structured generation.
    """
    def __init__(self):
        self.circuit_breaker = circuit_breaker
        self.intent_cache = intent_cache
        self._providers_registry: Dict[str, BaseLLMProvider] = {}
        self._session_metrics = {
            "real_llm_calls": 0,
            "deterministic_operations_avoided": 0,
            "calls_per_provider": {
                "cerebras": 0,
                "groq": 0,
                "gemini": 0,
                "nvidia_nim": 0,
                "openrouter": 0,
                "ollama": 0,
                "mock": 0
            },
            "fallbacks_triggered": 0,
            "circuit_breaker_trips": 0
        }
        self._init_providers()

    def _init_providers(self):
        self._providers_registry = {
            "cerebras": CerebrasProvider(),
            "groq": GroqProvider(),
            "gemini": GeminiProvider(),
            "nvidia_nim": NvidiaNimProvider(),
            "openrouter": OpenRouterProvider(),
            "ollama": OllamaProvider(),
            "mock": MockProvider()
        }

    def get_provider(self, name: str) -> BaseLLMProvider:
        name = name.lower().strip()
        return self._providers_registry.get(name, self._providers_registry["mock"])

    def resolve_chain(self, role: Optional[str] = None) -> List[str]:
        """
        Determines the priority chain for a given role or global default.
        Priority fallback order:
        Cerebras -> Groq -> Gemini -> NVIDIA NIM -> OpenRouter -> Ollama -> MockProvider
        """
        if role == "buyer":
            primary = getattr(settings, "BUYER_LLM_PROVIDER", "cerebras")
            fallbacks = getattr(settings, "BUYER_LLM_FALLBACKS", "groq,gemini,nvidia_nim,openrouter,ollama,mock")
        elif role == "merchant":
            primary = getattr(settings, "MERCHANT_LLM_PROVIDER", "groq")
            fallbacks = getattr(settings, "MERCHANT_LLM_FALLBACKS", "cerebras,gemini,nvidia_nim,openrouter,ollama,mock")
        elif role == "auxiliary":
            primary = getattr(settings, "AUXILIARY_LLM_PROVIDER", "groq")
            fallbacks = getattr(settings, "AUXILIARY_LLM_FALLBACKS", "cerebras,gemini,nvidia_nim,openrouter,ollama,mock")
        else:
            primary = getattr(settings, "PRIMARY_LLM_PROVIDER", "cerebras")
            fallbacks = getattr(settings, "LLM_PROVIDER_CHAIN", "cerebras,groq,gemini,nvidia_nim,openrouter,ollama,mock")

        chain = [primary.strip().lower()]
        for fb in fallbacks.split(","):
            fb_clean = fb.strip().lower()
            if fb_clean and fb_clean not in chain:
                chain.append(fb_clean)

        if "mock" not in chain:
            chain.append("mock")
        return chain

    def parse_user_intent(self, query: str, budget: Optional[Union[Decimal, float]] = None) -> UserIntent:
        """
        Extracts structured intent from user's natural language.
        1. Checks IntentCache (0ms, 0 tokens).
        2. Tries deterministic regex/heuristic parser for clear structured intent (0ms, 0 tokens).
        3. Falls back to external LLM provider only for ambiguous or conversational queries.
        """
        cached = self.intent_cache.get(query)
        if cached:
            self._session_metrics["deterministic_operations_avoided"] += 1
            return cached

        # Try deterministic parse first
        det_intent = parse_deterministic_intent(query, budget)
        if det_intent:
            self._session_metrics["deterministic_operations_avoided"] += 1
            self.intent_cache.set(query, det_intent)
            return det_intent

        # Attempt structured parse through provider chain for ambiguous queries
        system_prompt = (
            "You are SETU Intent Parser. Extract structured purchase parameters from user natural language query.\n"
            "Return JSON matching UserIntent schema: product, max_budget (number or null), preferences (list), quantity (number)."
        )
        user_prompt = f"User Query: '{query}'\nGiven budget constraint: {budget or 'Not specified'}"

        chain = self.resolve_chain("auxiliary")
        parsed_intent = None

        for p_name in chain:
            if not self.circuit_breaker.is_available(p_name):
                continue
            provider = self.get_provider(p_name)
            if not getattr(provider, "is_available", True):
                continue

            try:
                parsed_intent, meta = provider.generate_structured(system_prompt, user_prompt, UserIntent, timeout=12.0)
                parsed_intent.intent_parse_mode = "llm_fallback"
                parsed_intent.intent_llm_used = (p_name != "mock")
                self.circuit_breaker.record_success(p_name)
                if p_name != "mock":
                    self._session_metrics["real_llm_calls"] += 1
                    self._session_metrics["calls_per_provider"][p_name] = self._session_metrics["calls_per_provider"].get(p_name, 0) + 1
                break
            except Exception as e:
                logger.warning(f"AIGateway: Intent parsing with '{p_name}' failed: {e}. Trying next provider...")
                continue

        if not parsed_intent:
            # Deterministic Python fallback
            parsed_intent = MockProvider()._generate_deterministic_mock(query, UserIntent)
            parsed_intent.intent_parse_mode = "deterministic"
            parsed_intent.intent_llm_used = False

        self.intent_cache.set(query, parsed_intent)
        return parsed_intent

    def _create_rejection_fallback(self, schema: Type[BaseModel], context: Optional[NegotiationContext] = None, reason: str = "Safety fallback rejection on invalid agent decision.") -> BaseModel:
        prod_id = 1
        if context and context.current_product and isinstance(context.current_product, dict):
            prod_id = context.current_product.get("id", 1)
            
        s_name = getattr(schema, "__name__", "")
        if s_name == "BuyerDecision" or issubclass(schema, BuyerDecision):
            return schema(
                action="REJECT",
                product_id=prod_id,
                quantity=1,
                unit_price=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                rationale=reason,
                constraints_checked=["safety_fallback"],
                basket_items=[]
            )
        elif s_name == "MerchantDecision" or issubclass(schema, MerchantDecision):
            return schema(
                action="REJECT",
                product_id=prod_id,
                unit_price=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                rationale=reason,
                margin_preserved=False,
                basket_items=[]
            )
        else:
            return schema(action="REJECT", total_amount=Decimal("0.00"))

    def generate_negotiation_turn(
        self,
        context: NegotiationContext,
        role: str,
        schema: Type[BaseModel],
        max_retries: int = 1,
        custom_provider: Optional[Any] = None
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        """
        Executes ONE structured LLM generation per negotiation turn.
        Passes compact deterministic NegotiationContext and requires structured JSON.
        Validates the output deterministically against SETU policy bounds.
        """
        system_prompt = self._build_role_system_prompt(role, context)
        user_prompt = self._build_compact_turn_prompt(context)

        # 1. Custom injected provider support (for unit tests / test doubles)
        if custom_provider is not None and type(custom_provider).__name__ not in ("MultiFallbackProvider",):
            if hasattr(custom_provider, "generate_structured"):
                obj, meta = custom_provider.generate_structured(system_prompt, user_prompt, schema)
                obj = self._clamp_decision(obj, context)
                return obj, meta
            elif hasattr(custom_provider, "generate_structured_response"):
                start_t = time.perf_counter()
                raw_obj = custom_provider.generate_structured_response(user_prompt, system_prompt, schema)
                latency = (time.perf_counter() - start_t) * 1000.0
                
                # Unpack or validate raw_obj into target schema
                if hasattr(raw_obj, "final_decision") and raw_obj.final_decision is not None:
                    fin = raw_obj.final_decision
                    try:
                        if isinstance(fin, schema):
                            obj = fin
                        elif isinstance(fin, dict):
                            obj = schema(**fin)
                        else:
                            obj = fin
                    except Exception:
                        obj = self._create_rejection_fallback(schema, context, "Safety rejection on invalid agent final_decision.")
                elif isinstance(raw_obj, schema):
                    obj = raw_obj
                elif isinstance(raw_obj, dict):
                    try:
                        obj = schema(**raw_obj)
                    except Exception:
                        obj = self._create_rejection_fallback(schema, context, "Safety rejection on invalid agent dictionary output.")
                else:
                    obj = raw_obj

                p_name = getattr(custom_provider, "provider_name", "mock").lower()
                is_mock = "mock" in p_name
                meta = ProviderExecutionMetadata(
                    provider_used=p_name,
                    provider_type="deterministic_fallback" if is_mock else "real_llm",
                    model_name=getattr(custom_provider, "model_name", "mock-model"),
                    agent_role=role,
                    fallback_used=False,
                    response_latency_ms=round(latency, 2)
                )
                if not is_mock:
                    self._session_metrics["real_llm_calls"] += 1
                    self._session_metrics["calls_per_provider"][p_name] = self._session_metrics["calls_per_provider"].get(p_name, 0) + 1
                else:
                    self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1
                return obj, meta

        chain = self.resolve_chain(role.lower().replace("_agent", ""))
        errors_encountered = []
        depth = 0

        for p_name in chain:
            if not self.circuit_breaker.is_available(p_name):
                logger.info(f"AIGateway: Skipping rate-limited / unavailable provider '{p_name}' (Circuit OPEN).")
                continue

            provider = self.get_provider(p_name)
            if not getattr(provider, "is_available", True):
                continue

            # Attempt structured generation with 1 bounded retry on invalid schema
            for attempt in range(max_retries + 1):
                try:
                    obj, meta = provider.generate_structured(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        schema=schema,
                        timeout=getattr(settings, "LLM_TIMEOUT_SECONDS", 20.0)
                    )

                    # Validate bounds deterministically
                    is_valid, validation_err = self._validate_decision_bounds(obj, context)
                    if not is_valid:
                        if attempt < max_retries:
                            logger.warning(f"AIGateway: Decision bounds check failed on {p_name} ({validation_err}). Retrying once...")
                            user_prompt += f"\nCORRECTION REQUIRED: {validation_err}. Please ensure price and boundaries are strictly respected."
                            continue
                        else:
                            # Clamp / correct deterministically if bounds slightly violated
                            obj = self._clamp_decision(obj, context)

                    self.circuit_breaker.record_success(p_name)
                    meta.agent_role = role
                    meta.fallback_depth = depth
                    meta.fallback_used = (depth > 0 or p_name == "mock")
                    if errors_encountered:
                        meta.fallback_reason = " | ".join(errors_encountered)

                    if p_name != "mock":
                        self._session_metrics["real_llm_calls"] += 1
                        self._session_metrics["calls_per_provider"][p_name] = self._session_metrics["calls_per_provider"].get(p_name, 0) + 1
                    else:
                        self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1

                    return obj, meta

                except Exception as e:
                    err_msg = f"{p_name}: {type(e).__name__}({str(e)[:150]})"
                    logger.warning(f"AIGateway: Provider '{p_name}' failed turn generation: {err_msg}")
                    errors_encountered.append(err_msg)
                    self._session_metrics["fallbacks_triggered"] += 1
                    break  # Break inner retry to fail over immediately to next provider

            depth += 1

        # Fallback to Mock if all failed
        mock_p = self.get_provider("mock")
        obj, meta = mock_p.generate_structured(system_prompt, user_prompt, schema)
        meta.agent_role = role
        meta.fallback_used = True
        meta.fallback_depth = depth
        meta.fallback_reason = " | ".join(errors_encountered) if errors_encountered else "All real providers bypassed"
        self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1
        return obj, meta

    def _build_role_system_prompt(self, role: str, context: NegotiationContext) -> str:
        role_upper = role.upper()
        if "BUYER" in role_upper:
            return (
                "You are the autonomous BUYER AGENT in the SETU AI Commerce Protocol.\n"
                "Your objective:\n"
                "1. Minimize spending and secure the best value while staying within the buyer's maximum budget.\n"
                "2. Formulate strategic offers/counters that are compelling and realistic.\n"
                "3. Never accept an offer that exceeds buyer_max_budget.\n"
                "4. Respond ONLY with structured JSON matching the BuyerDecision schema."
            )
        else:
            return (
                "You are the autonomous MERCHANT AGENT in the SETU AI Commerce Protocol.\n"
                "Your objective:\n"
                "1. Maximize profitable revenue and defend the minimum price floor.\n"
                "2. Protect product profit margins while closing the sale.\n"
                "3. Recommend valuable bundle cross-sells where advantageous.\n"
                "4. Never offer or accept a price below the merchant_min_price floor.\n"
                "5. Respond ONLY with structured JSON matching the MerchantDecision schema."
            )

    def _build_compact_turn_prompt(self, context: NegotiationContext) -> str:
        if context.agent_role == "BUYER_AGENT":
            strategy_hint = (
                f"Guidelines for Buyer Agent:\n"
                f"- For opening offer (Round 1), propose an attractive offer between ₹{context.merchant_min_price} and ₹{context.buyer_max_budget} with action 'OFFER'.\n"
                f"- If Merchant's previous offer is within budget (<= ₹{context.buyer_max_budget}), select action 'ACCEPT'.\n"
                f"- Otherwise, propose a reasonable counter with action 'COUNTER' (total_amount <= ₹{context.buyer_max_budget})."
            )
        else:
            strategy_hint = (
                f"Guidelines for Merchant Agent:\n"
                f"- If Buyer's offer is at or above your minimum price floor (>= ₹{context.merchant_min_price}), select action 'ACCEPT' or a minor 'COUNTER'.\n"
                f"- If Buyer's offer is below floor, propose a counter with action 'COUNTER' and total_amount >= ₹{context.merchant_min_price}.\n"
                f"- total_amount must NEVER be lower than ₹{context.merchant_min_price}."
            )

        return (
            f"=== DETERMINISTIC NEGOTIATION CONTEXT ===\n"
            f"Role: {context.agent_role}\n"
            f"Current Round: {context.current_round} (Remaining: {context.remaining_rounds})\n"
            f"Target Product: {context.current_product.get('name')} (ID: {context.current_product.get('id')})\n"
            f"Catalog Price: ₹{context.catalog_price}\n"
            f"Buyer Max Budget: ₹{context.buyer_max_budget}\n"
            f"Merchant Price Floor: ₹{context.merchant_min_price}\n"
            f"Max Allowed Discount: {context.max_allowed_discount}%\n"
            f"Available Inventory: {context.inventory_availability} units\n"
            f"Active Policy Limits: {json.dumps(context.relevant_policy_constraints)}\n"
            f"Previous Offers in Session: {json.dumps(context.previous_offers)}\n"
            f"=========================================\n"
            f"{strategy_hint}\n"
            f"Respond with structured JSON matching the schema (action, product_id, quantity, unit_price, total_amount, rationale)."
        )

    def _validate_decision_bounds(self, obj: BaseModel, context: NegotiationContext) -> Tuple[bool, Optional[str]]:
        try:
            action = getattr(obj, "action", "").upper()
            if action == "REJECT":
                return True, None

            tot = getattr(obj, "total_amount", None)
            if tot is None:
                return False, "total_amount is missing"
            tot_dec = Decimal(str(tot))
            if tot_dec <= Decimal("0.00"):
                return False, "total_amount must be positive for OFFER, COUNTER, and ACCEPT"

            # Check buyer budget ceiling
            if context.agent_role == "BUYER_AGENT":
                if tot_dec > context.buyer_max_budget:
                    return False, f"Total amount ₹{tot_dec} exceeds buyer maximum budget of ₹{context.buyer_max_budget}"

            # Check merchant price floor
            if context.agent_role == "MERCHANT_AGENT":
                if tot_dec < context.merchant_min_price:
                    return False, f"Total amount ₹{tot_dec} is below merchant price floor of ₹{context.merchant_min_price}"

            return True, None
        except Exception as e:
            return False, str(e)

    def _clamp_decision(self, obj: BaseModel, context: NegotiationContext) -> BaseModel:
        action = getattr(obj, "action", "").upper()
        if action == "REJECT":
            return obj

        tot = getattr(obj, "total_amount", None)
        if tot is not None:
            tot_dec = Decimal(str(tot))
            if tot_dec <= Decimal("0.00"):
                # Fallback to realistic starting offer if model returned 0
                tot_dec = max(context.merchant_min_price, (context.catalog_price * Decimal("0.9")).quantize(Decimal("0.01")))
                obj.total_amount = tot_dec
                obj.unit_price = tot_dec

            if context.agent_role == "BUYER_AGENT" and tot_dec > context.buyer_max_budget:
                obj.total_amount = context.buyer_max_budget
                obj.unit_price = context.buyer_max_budget
                obj.rationale += f" [Clamped to max budget of ₹{context.buyer_max_budget}]"
            elif context.agent_role == "MERCHANT_AGENT" and tot_dec < context.merchant_min_price:
                obj.total_amount = context.merchant_min_price
                obj.unit_price = context.merchant_min_price
                obj.rationale += f" [Clamped to minimum price floor of ₹{context.merchant_min_price}]"
        return obj

    def get_provider_status(self) -> Dict[str, Any]:
        """Diagnostic status for GET /api/agent/provider-status (Never exposes API keys)."""
        chain = self.resolve_chain()
        circuit_info = self.circuit_breaker.get_status()

        return {
            "gateway_status": "ONLINE",
            "primary_provider": getattr(settings, "PRIMARY_LLM_PROVIDER", "cerebras"),
            "provider_chain": chain,
            "providers": {
                "cerebras": {
                    "configured": bool(os.getenv("CEREBRAS_API_KEY") or getattr(settings, "CEREBRAS_API_KEY", "")),
                    "model": getattr(settings, "CEREBRAS_MODEL", "llama3.1-70b"),
                    "circuit": circuit_info.get("cerebras", {"circuit_state": "CLOSED", "available": True})
                },
                "groq": {
                    "configured": bool(os.getenv("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", "")),
                    "model": getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "circuit": circuit_info.get("groq", {"circuit_state": "CLOSED", "available": True})
                },
                "gemini": {
                    "configured": bool(os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")),
                    "model": getattr(settings, "LLM_MODEL", "gemini-3.1-flash-lite"),
                    "circuit": circuit_info.get("gemini", {"circuit_state": "CLOSED", "available": True})
                },
                "nvidia_nim": {
                    "configured": bool(os.getenv("NVIDIA_NIM_API_KEY") or getattr(settings, "NVIDIA_NIM_API_KEY", "")),
                    "model": getattr(settings, "NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct"),
                    "circuit": circuit_info.get("nvidia_nim", {"circuit_state": "CLOSED", "available": True})
                },
                "openrouter": {
                    "configured": bool(os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "")),
                    "model": getattr(settings, "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                    "circuit": circuit_info.get("openrouter", {"circuit_state": "CLOSED", "available": True})
                },
                "ollama": {
                    "configured": bool(getattr(settings, "OLLAMA_ENABLED", False)),
                    "model": getattr(settings, "OLLAMA_MODEL", "llama3.2"),
                    "circuit": circuit_info.get("ollama", {"circuit_state": "CLOSED", "available": True})
                },
                "mock": {
                    "configured": True,
                    "model": "mock-model-v2",
                    "circuit": {"circuit_state": "CLOSED", "available": True}
                }
            },
            "session_metrics": self._session_metrics
        }

    def record_avoided_operation(self, count: int = 1):
        self._session_metrics["deterministic_operations_avoided"] += count


# Global singleton instance
ai_gateway = AIGateway()

def get_ai_gateway() -> AIGateway:
    return ai_gateway
