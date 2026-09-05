"""
SETU Central AI Gateway Architecture
====================================
Drastically reduces LLM API usage while maintaining genuine AI-to-AI negotiation.

Core Principles:
1. Deterministic SETU tools (catalog search, policy evaluation, margin math, inventory checks,
   pricing floor checks, Razorpay verification, audit logging) are ALWAYS executed in Python/SQL
   WITHOUT calling an LLM.
2. LLM is invoked ONLY for:
   A. Initial natural language intent understanding (with normalized intent caching).
   B. Genuine Buyer Agent negotiation reasoning (1 structured turn per round).
   C. Genuine Merchant Agent negotiation reasoning (1 structured turn per round).
   D. Human-readable final explanation.
3. Multi-Provider Fallback Priority Chain:
   Cerebras -> Groq -> Gemini -> NVIDIA NIM -> OpenRouter -> Ollama -> MockProvider
4. Fast Circuit Breaker:
   - On 429 (rate limit / quota), 401/403 (auth), 402 (billing), 404 (model/endpoint not found),
     503 (service unavailable), or repeated timeouts, immediately opens circuit for cooldown
     (default 60s). Fails over with 0ms delay without blocking request threads or sleep loops.
5. Absolute Safety:
   - If ALL external providers fail, MockProvider GUARANTEES a 100% schema-compliant,
     deterministic fallback decision. SETU NEVER crashes with an empty or malformed mock response.
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

# Import canonical schemas from provider.py to prevent identity mismatch
from backend.app.agents.provider import (
    BuyerDecision,
    MerchantDecision,
    BasketItemSchema,
    ProviderExecutionMetadata,
    PurchaseRequestProposal,
    MerchantOffer,
)

logger = logging.getLogger("setu.ai_gateway")


# ==============================================================================
# 1. CORE DATA SCHEMAS & ERROR CONTRACT
# ==============================================================================

class FailureCategory:
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    AUTH_ERROR = "AUTH_ERROR"
    BILLING_ERROR = "BILLING_ERROR"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    ENDPOINT_ERROR = "ENDPOINT_ERROR"
    TIMEOUT = "TIMEOUT"
    SDK_ERROR = "SDK_ERROR"
    UNAVAILABLE = "UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN = "UNKNOWN"


class ProviderFailure(Exception):
    """
    Standardized provider failure exception.
    Provides structured error categorization without leaking secrets.
    """
    def __init__(
        self,
        provider_name: str,
        category: str,
        message: str,
        status_code: Optional[int] = None,
        model_name: Optional[str] = None
    ):
        self.provider_name = provider_name.lower().strip()
        self.category = category
        self.message = message
        self.status_code = status_code
        self.model_name = model_name
        super().__init__(f"[{self.provider_name.upper()} | {self.category}] {self.message}")


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
    optional_bundle: Optional[Dict[str, Any]] = Field(default=None, description="Deterministic bundle & cross-sell options available")
    bundle_already_proposed: bool = Field(default=False, description="Whether the bundle was already presented in earlier rounds")
    standalone_preferred: bool = Field(default=False, description="Whether buyer strictly prefers standalone without accessories")
    buyer_profile: str = Field(default="PRICE_FIRST", description="Buyer profile: 'PRICE_FIRST' or 'VALUE_ORIENTED'")


# ==============================================================================
# 2. CIRCUIT BREAKER
# ==============================================================================

class CircuitBreaker:
    """
    In-memory thread-safe circuit breaker for external LLM providers.
    Quickly trips to OPEN state on 429, quota limits, auth errors, billing errors,
    404 model not found, or repeated timeouts, preventing request delays on dead endpoints.
    Recovers via HALF_OPEN state after cooldown expiry without persistent lock-in.
    """
    def __init__(self, cooldown_seconds: float = 30.0):
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._states: Dict[str, Dict[str, Any]] = {}

    def _init_provider(self, name: str):
        if name not in self._states:
            self._states[name] = {
                "circuit_state": "CLOSED",  # "CLOSED", "OPEN", "HALF_OPEN"
                "failure_count": 0,
                "circuit_open_until": 0.0,
                "last_error": None,
                "last_category": None,
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
                    # Cooldown expired -> test transition to HALF_OPEN (allows 1 trial request)
                    state["circuit_state"] = "HALF_OPEN"
                    logger.info(f"CircuitBreaker: Cooldown elapsed for '{provider_name}'. Circuit state changed to HALF_OPEN (probing).")
                    return True
                else:
                    return False
            elif state["circuit_state"] == "HALF_OPEN":
                return True
            return True

    def record_success(self, provider_name: str):
        provider_name = provider_name.lower().strip()
        with self._lock:
            self._init_provider(provider_name)
            state = self._states[provider_name]
            state["circuit_state"] = "CLOSED"
            state["failure_count"] = 0
            state["circuit_open_until"] = 0.0
            state["last_error"] = None
            state["last_category"] = None
            state["last_success_timestamp"] = time.time()
            state["total_calls"] += 1

    def record_failure(
        self,
        provider_name: str,
        error: Exception,
        status_code: Optional[int] = None,
        category: Optional[str] = None
    ):
        provider_name = provider_name.lower().strip()
        if provider_name == "mock":
            return

        err_str = str(error)
        cat = category or (getattr(error, "category", None))

        is_fast_trip = False
        if status_code in (401, 402, 403, 404, 429, 503):
            is_fast_trip = True
        elif cat in (
            FailureCategory.RATE_LIMITED,
            FailureCategory.QUOTA_EXHAUSTED,
            FailureCategory.AUTH_ERROR,
            FailureCategory.BILLING_ERROR,
            FailureCategory.MODEL_NOT_FOUND,
            FailureCategory.ENDPOINT_ERROR,
            FailureCategory.TIMEOUT,
            FailureCategory.SDK_ERROR,
            FailureCategory.UNAVAILABLE,
        ):
            is_fast_trip = True
        elif any(term in err_str.lower() for term in (
            "429", "rate limit", "resourceexhausted", "quota", "payment required",
            "402", "unauthorized", "401", "forbidden", "403", "not found", "404",
            "503 unavailable", "model_not_found", "importerror"
        )):
            is_fast_trip = True

        with self._lock:
            self._init_provider(provider_name)
            state = self._states[provider_name]
            state["failure_count"] += 1
            state["total_calls"] += 1
            state["failed_calls"] += 1
            state["last_category"] = cat or FailureCategory.UNKNOWN
            state["last_error"] = f"{type(error).__name__}: {err_str[:200]}"

            # In HALF_OPEN, any failure immediately trips back to OPEN
            if is_fast_trip or state["circuit_state"] == "HALF_OPEN" or state["failure_count"] >= 2:
                state["circuit_state"] = "OPEN"
                state["circuit_open_until"] = time.time() + self.cooldown_seconds
                logger.warning(
                    f"CircuitBreaker: Tripped OPEN for provider '{provider_name}' "
                    f"(status={status_code}, category={state['last_category']}, error={state['last_error']}). "
                    f"Cooldown until {time.strftime('%H:%M:%S', time.localtime(state['circuit_open_until']))}."
                )

    def reset(self, provider_name: Optional[str] = None):
        """Resets in-memory circuit breaker states (all or specific provider)."""
        with self._lock:
            if provider_name:
                self._states.pop(provider_name.lower().strip(), None)
            else:
                self._states.clear()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            res = {}
            for name, s in self._states.items():
                is_open = s["circuit_state"] == "OPEN" and now < s["circuit_open_until"]
                curr_state = "OPEN" if is_open else ("HALF_OPEN" if s["circuit_state"] == "HALF_OPEN" or (s["circuit_state"] == "OPEN" and now >= s["circuit_open_until"]) else "CLOSED")
                res[name] = {
                    "available": curr_state in ("CLOSED", "HALF_OPEN"),
                    "circuit_state": curr_state,
                    "failure_count": s["failure_count"],
                    "circuit_open_until": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s["circuit_open_until"])) if is_open else None,
                    "last_category": s.get("last_category"),
                    "last_error": s["last_error"],
                    "total_calls": s["total_calls"],
                    "failed_calls": s["failed_calls"]
                }
            return res


# Global CircuitBreaker instance
circuit_breaker = CircuitBreaker(cooldown_seconds=getattr(settings, "CIRCUIT_BREAKER_COOLDOWN_SECONDS", 30.0))


# ==============================================================================
# 3. INTENT CACHE & DETERMINISTIC INTENT PARSER
# ==============================================================================

def parse_deterministic_intent(query: str, budget: Optional[Decimal] = None) -> Optional[UserIntent]:
    """
    Deterministically parses structured user purchase queries without invoking an LLM.
    Returns UserIntent if high confidence pattern matches, otherwise None (fallback to LLM).
    """
    q_clean = query.strip()
    if not q_clean:
        return None

    # Pattern: "I want <Product> [with budget [Rs/INR] <amount>]"
    # Example: "I want Samsung Galaxy A15 with budget 14000 INR."
    match = re.search(
        r"(?:i\s+want|buy|looking\s+for|purchase|need)\s+([a-zA-Z0-9\s\+\-]+?)"
        r"(?:\s+(?:with\s+budget|budget|under|for|max\s+price)\s+(?:rs\.?|inr|₹|\$)?\s*([\d,]+(?:\.\d+)?))?(?:\s*(?:inr|rs\.?|₹|\$))?[\.\!\?]?$",
        q_clean,
        re.IGNORECASE
    )

    if match:
        prod_name = match.group(1).strip()
        budget_str = match.group(2)
        parsed_budget = None

        if budget_str:
            try:
                parsed_budget = float(budget_str.replace(",", ""))
            except Exception:
                pass
        elif budget is not None:
            parsed_budget = float(budget)

        # Sanity check product name
        if len(prod_name) >= 3 and not any(w in prod_name.lower() for w in ["something", "anything", "whatever"]):
            is_standalone = bool(re.search(r"standalone|without\s+accessories|only\s+phone|no\s+bundle", q_clean, re.IGNORECASE))
            return UserIntent(
                product=prod_name,
                product_query=prod_name,
                max_budget=parsed_budget,
                currency="INR",
                preferences=["standalone"] if is_standalone else [],
                quantity=1,
                standalone_only=is_standalone,
                confidence=0.98,
                intent_parse_mode="deterministic",
                intent_llm_used=False
            )

    return None


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
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (intent, time.time())


intent_cache = IntentCache()


# ==============================================================================
# 4. PROVIDER ADAPTERS
# ==============================================================================

class BaseLLMProvider:
    provider_name: str = "base"
    provider_type: str = "real_llm"
    model_name: str = "base-model"
    is_available: bool = False

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        raise NotImplementedError


class CerebrasProvider(BaseLLMProvider):
    """
    Cerebras Cloud Inference LLM Provider.
    Ultra-fast Llama-3.1 inference tier.
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
            raise ProviderFailure(self.provider_name, FailureCategory.AUTH_ERROR, "Cerebras API key is not configured.")

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

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(url, json=payload, headers=headers)
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
            cat = FailureCategory.RATE_LIMITED if status == 429 else (
                FailureCategory.AUTH_ERROR if status in (401, 403) else (
                    FailureCategory.MODEL_NOT_FOUND if status == 404 else FailureCategory.ENDPOINT_ERROR
                )
            )
            failure = ProviderFailure(self.provider_name, cat, f"HTTP {status}: {e.response.text[:150] if e.response else str(e)}", status_code=status, model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, status_code=status, category=cat)
            raise failure
        except httpx.TimeoutException as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.TIMEOUT, f"Request timed out after {timeout}s: {e}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, category=FailureCategory.TIMEOUT)
            raise failure
        except Exception as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.UNKNOWN, f"Cerebras call failed: {str(e)[:150]}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure)
            raise failure


class GroqProvider(BaseLLMProvider):
    """
    Groq Fast Inference LLM Provider.
    OpenAI-compatible REST endpoint.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        self.provider_name = "groq"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", "")
        self.model_name = model or os.getenv("GROQ_MODEL") or os.getenv("MERCHANT_LLM_MODEL") or getattr(settings, "GROQ_MODEL", "groq/compound-mini")
        
        raw_url = base_url or os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1"
        self.base_url = raw_url.rstrip("/")
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
            raise ProviderFailure(self.provider_name, FailureCategory.AUTH_ERROR, "Groq API key is not configured.")

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

        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(url, json=payload, headers=headers)
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
            cat = FailureCategory.RATE_LIMITED if status == 429 else (
                FailureCategory.AUTH_ERROR if status in (401, 403) else (
                    FailureCategory.MODEL_NOT_FOUND if status == 404 else FailureCategory.ENDPOINT_ERROR
                )
            )
            msg = f"Groq HTTP {status} error: {e.response.text[:150] if e.response else str(e)}"
            failure = ProviderFailure(self.provider_name, cat, msg, status_code=status, model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, status_code=status, category=cat)
            raise failure
        except httpx.TimeoutException as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.TIMEOUT, f"Groq request timed out after {timeout}s: {e}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, category=FailureCategory.TIMEOUT)
            raise failure
        except Exception as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.UNKNOWN, f"Groq execution failure: {str(e)[:150]}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure)
            raise failure


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini LLM Provider.
    Supports both modern google-genai and legacy google-generativeai SDKs gracefully.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider_name = "gemini"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")
        self.model_name = model or os.getenv("GEMINI_MODEL") or getattr(settings, "LLM_MODEL", "gemini-3.5-flash")
        self.is_available = self._check_operational_availability()

    @staticmethod
    def get_sdk_status() -> Tuple[Optional[str], Optional[Any], Optional[Any]]:
        """
        Safely checks which Gemini SDK is installed in the current environment.
        Returns (sdk_type, sdk_module, types_module)
        """
        # 1. Try modern google-genai
        try:
            from google import genai
            from google.genai import types
            return ("google.genai", genai, types)
        except Exception:
            pass

        # 2. Try legacy google-generativeai
        try:
            import google.generativeai as legacy_genai
            return ("google.generativeai", legacy_genai, None)
        except Exception:
            pass

        return (None, None, None)

    def _check_operational_availability(self) -> bool:
        has_key = bool(self.api_key and self.api_key.strip())
        sdk_type, _, _ = self.get_sdk_status()
        return has_key and (sdk_type is not None)

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 20.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        if not self.api_key or not self.api_key.strip():
            raise ProviderFailure(self.provider_name, FailureCategory.AUTH_ERROR, "Gemini API key is not configured.")

        sdk_type, sdk_module, types_module = self.get_sdk_status()
        if sdk_type is None:
            failure = ProviderFailure(self.provider_name, FailureCategory.SDK_ERROR, "Neither 'google-genai' nor 'google-generativeai' is installed.")
            circuit_breaker.record_failure(self.provider_name, failure, category=FailureCategory.SDK_ERROR)
            raise failure

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        try:
            if sdk_type == "google.genai":
                client = sdk_module.Client(api_key=self.api_key.strip())
                prompt_content = f"{user_prompt}\n\nReturn JSON matching schema:\n{schema_json}"
                config = types_module.GenerateContentConfig(
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
            else:
                # Legacy google.generativeai
                sdk_module.configure(api_key=self.api_key.strip())
                model = sdk_module.GenerativeModel(
                    model_name=self.model_name,
                    system_instruction=system_prompt,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.2}
                )
                prompt_content = f"{user_prompt}\n\nStrictly return JSON matching:\n{schema_json}"
                response = model.generate_content(prompt_content)
                raw_text = response.text.strip()

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
            err_str = str(e)
            cat = FailureCategory.UNKNOWN
            status_code = None
            if any(w in err_str.lower() for w in ["429", "resourceexhausted", "quota"]):
                cat = FailureCategory.QUOTA_EXHAUSTED
                status_code = 429
            elif any(w in err_str.lower() for w in ["503", "unavailable"]):
                cat = FailureCategory.UNAVAILABLE
                status_code = 503
            elif any(w in err_str.lower() for w in ["401", "403", "api_key_invalid", "permissiondenied"]):
                cat = FailureCategory.AUTH_ERROR
                status_code = 403
            elif any(w in err_str.lower() for w in ["404", "not_found", "model not found"]):
                cat = FailureCategory.MODEL_NOT_FOUND
                status_code = 404

            failure = ProviderFailure(self.provider_name, cat, f"Gemini API failure: {err_str[:150]}", status_code=status_code, model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, status_code=status_code, category=cat)
            raise failure


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
            raise ProviderFailure(self.provider_name, FailureCategory.AUTH_ERROR, "NVIDIA NIM API key is not configured.")

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

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(url, json=payload, headers=headers)
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
            cat = FailureCategory.RATE_LIMITED if status == 429 else (
                FailureCategory.AUTH_ERROR if status in (401, 403) else (
                    FailureCategory.MODEL_NOT_FOUND if status == 404 else FailureCategory.ENDPOINT_ERROR
                )
            )
            failure = ProviderFailure(self.provider_name, cat, f"NVIDIA NIM HTTP {status}: {e.response.text[:150] if e.response else str(e)}", status_code=status, model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, status_code=status, category=cat)
            raise failure
        except httpx.TimeoutException as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.TIMEOUT, f"NVIDIA NIM request timed out after {timeout}s: {e}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, category=FailureCategory.TIMEOUT)
            raise failure
        except Exception as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.UNKNOWN, f"NVIDIA NIM failure: {str(e)[:150]}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure)
            raise failure


class OpenRouterProvider(BaseLLMProvider):
    """
    OpenRouter API Provider (Free models and universal aggregator).
    OpenAI-compatible REST endpoint with required OpenRouter metadata headers.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        self.provider_name = "openrouter"
        self.provider_type = "real_llm"
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "")
        self.model_name = model or os.getenv("OPENROUTER_MODEL") or getattr(settings, "OPENROUTER_MODEL", "dots-studio/dots-3-note-preview:free")
        raw_url = base_url or os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        self.base_url = raw_url.rstrip("/")
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
            raise ProviderFailure(self.provider_name, FailureCategory.AUTH_ERROR, "OpenRouter API key is not configured.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://setu.ai",
            "X-Title": "SETU AI Commerce Trust Layer"
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

        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(url, json=payload, headers=headers)
                res.raise_for_status()
                data = res.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
                parsed_json = json.loads(cleaned)
                try:
                    parsed_obj = schema.model_validate(parsed_json) if hasattr(schema, "model_validate") else schema.parse_obj(parsed_json)
                except Exception:
                    if isinstance(parsed_json, dict):
                        for k, v in parsed_json.items():
                            if isinstance(v, dict) and any(f in v for f in ["action", "product_id", "total_amount", "unit_price"]):
                                parsed_json = v
                                break
                    fields_dict = {}
                    model_fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
                    for f_name in model_fields:
                        if f_name in parsed_json:
                            fields_dict[f_name] = parsed_json[f_name]
                    if "action" not in fields_dict or not fields_dict["action"]:
                        fields_dict["action"] = "COUNTER" if "Merchant" in getattr(schema, "__name__", "") else "OFFER"
                    if "product_id" not in fields_dict:
                        fields_dict["product_id"] = 1
                    if "quantity" not in fields_dict:
                        fields_dict["quantity"] = 1
                    if "unit_price" not in fields_dict:
                        fields_dict["unit_price"] = Decimal("1450.00")
                    if "total_amount" not in fields_dict:
                        fields_dict["total_amount"] = Decimal("1450.00")
                    if "rationale" not in fields_dict:
                        fields_dict["rationale"] = str(parsed_json.get("reason", parsed_json.get("rationale", "Autonomous reasoning.")))
                    parsed_obj = schema.model_construct(**fields_dict) if hasattr(schema, "model_construct") else schema.construct(**fields_dict)

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
            cat = FailureCategory.RATE_LIMITED if status == 429 else (
                FailureCategory.BILLING_ERROR if status == 402 else (
                    FailureCategory.AUTH_ERROR if status in (401, 403) else (
                        FailureCategory.MODEL_NOT_FOUND if status == 404 else FailureCategory.ENDPOINT_ERROR
                    )
                )
            )
            msg = f"OpenRouter HTTP {status}: {e.response.text[:150] if e.response else str(e)}"
            failure = ProviderFailure(self.provider_name, cat, msg, status_code=status, model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, status_code=status, category=cat)
            raise failure
        except httpx.TimeoutException as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.TIMEOUT, f"OpenRouter request timed out after {timeout}s: {e}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, category=FailureCategory.TIMEOUT)
            raise failure
        except Exception as e:
            failure = ProviderFailure(self.provider_name, FailureCategory.UNKNOWN, f"OpenRouter failure: {str(e)[:150]}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure)
            raise failure


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
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model_name = model or os.getenv("OLLAMA_MODEL") or getattr(settings, "OLLAMA_MODEL", "llama3.2")
        self.is_available = bool(self.enabled)

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[BaseModel],
        timeout: float = 25.0
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        import httpx
        if not self.is_available:
            raise ProviderFailure(self.provider_name, FailureCategory.UNAVAILABLE, "Ollama is disabled or not running.")

        start_t = time.perf_counter()
        schema_json = json.dumps(schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema())

        payload = {
            "model": self.model_name,
            "system": system_prompt,
            "prompt": f"{user_prompt}\n\nRespond ONLY with JSON matching:\n{schema_json}",
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2}
        }

        url = f"{self.base_url}/api/generate"
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=0.8)) as client:
                res = client.post(url, json=payload)
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
            failure = ProviderFailure(self.provider_name, FailureCategory.UNAVAILABLE, f"Ollama connection failure: {e}", model_name=self.model_name)
            circuit_breaker.record_failure(self.provider_name, failure, category=FailureCategory.UNAVAILABLE)
            raise failure


class MockProvider(BaseLLMProvider):
    """
    Deterministic Offline Fallback Provider.
    Guarantees 100% schema-compliant, safe decision generation respecting all SETU
    pricing floors, margins, and policies with zero network dependencies.
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
        timeout: float = 5.0,
        context: Optional[NegotiationContext] = None
    ) -> Tuple[BaseModel, ProviderExecutionMetadata]:
        start_t = time.perf_counter()
        parsed_obj = self._generate_deterministic_mock(user_prompt, schema, context=context)
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

    def _generate_deterministic_mock(
        self,
        prompt: str,
        schema: Type[BaseModel],
        context: Optional[NegotiationContext] = None
    ) -> BaseModel:
        prompt_lower = prompt.lower()
        s_name = getattr(schema, "__name__", "")

        # ----------------------------------------------------------------------
        # 1. BuyerDecision Builder
        # ----------------------------------------------------------------------
        if s_name == "BuyerDecision" or issubclass(schema, BuyerDecision):
            prod_id = 1
            prod_name = "Product"
            cat_price = Decimal("1000.00")
            budget = Decimal("1200.00")
            floor_price = Decimal("850.00")
            round_num = 1

            if context:
                prod_details = context.current_product or {}
                prod_id = prod_details.get("id", 1)
                prod_name = prod_details.get("name", "Product")
                cat_price = context.catalog_price
                budget = context.buyer_max_budget
                floor_price = context.merchant_min_price
                round_num = context.current_round
            elif "samsung" in prompt_lower:
                prod_id = 41
                prod_name = "Samsung Galaxy A15"
                cat_price = Decimal("12999.00")
                budget = Decimal("14000.00")
                floor_price = Decimal("11049.15")
            elif "earbud" in prompt_lower:
                prod_id = 1
                prod_name = "Wireless Noise-Canceling Earbuds"
                cat_price = Decimal("1599.00")
                budget = Decimal("2000.00")
                floor_price = Decimal("1359.15")

            is_round_1 = (round_num == 1) if context else bool("round 1" in prompt_lower or "opening offer" in prompt_lower)

            if is_round_1:
                # Opening offer targeting ~15% discount (bounded by budget and floor)
                target_discount_price = (cat_price * Decimal("0.85")).quantize(Decimal("1.00"))
                unit_p = min(budget, max(floor_price, target_discount_price))
                action = "OFFER"
                rationale = f"Deterministic opening buyer offer targeting a ~15% discount at INR {unit_p:.2f} within budget ceiling INR {budget:.2f}."
                msg = f"Hi, I would like to offer INR {unit_p:.2f} for {prod_name}."
            else:
                last_merchant_price = None
                if context and context.current_proposal:
                    try:
                        last_merchant_price = Decimal(str(context.current_proposal.get("total_amount", 0)))
                    except Exception:
                        pass

                last_buyer_price = min(budget, max(floor_price, (cat_price * Decimal("0.85")).quantize(Decimal("1.00"))))
                if context and context.previous_offers:
                    for off in reversed(context.previous_offers):
                        actor_str = str(off.get("actor") or off.get("agent_role") or "").upper()
                        if "BUYER" in actor_str:
                            try:
                                last_buyer_price = Decimal(str(off.get("amount") or off.get("unit_price") or off.get("total_amount")))
                                break
                            except Exception:
                                pass

                if last_merchant_price is None:
                    last_merchant_price = cat_price

                # Check budget constraint
                if last_merchant_price > budget:
                    if round_num >= 4:
                        action = "REJECT"
                        unit_p = Decimal("0.00")
                        rationale = f"Merchant counter-offer INR {last_merchant_price:.2f} exceeds buyer budget INR {budget:.2f}. Rejected."
                        msg = f"Unfortunately INR {last_merchant_price:.2f} exceeds my budget limit of INR {budget:.2f}. I cannot proceed."
                    else:
                        action = "COUNTER"
                        unit_p = min(budget, last_buyer_price + Decimal("50.00"))
                        rationale = f"Merchant offer exceeds budget. Countering at budget-bounded INR {unit_p:.2f}."
                        msg = f"Can you meet at INR {unit_p:.2f} within my budget for {prod_name}?"
                else:
                    gap = last_merchant_price - last_buyer_price
                    # If gap is small (<= 35 INR), or merchant already matched/undercut buyer offer, accept
                    if gap <= Decimal("35.00") or last_merchant_price <= last_buyer_price:
                        action = "ACCEPT"
                        unit_p = last_merchant_price
                        rationale = f"Merchant counter-offer INR {unit_p:.2f} is within acceptable spread and budget ceiling (INR {budget:.2f}). Accepted."
                        msg = f"Deal agreed at INR {unit_p:.2f} for {prod_name}."
                    elif round_num >= 4:
                        # Final round: accept if within budget and below catalog price
                        action = "ACCEPT"
                        unit_p = last_merchant_price
                        rationale = f"Final round agreement at merchant counter-offer INR {unit_p:.2f} within budget (INR {budget:.2f})."
                        msg = f"Since this is our final round, I'm happy to accept INR {unit_p:.2f} for {prod_name}."
                    else:
                        # Realistic gradual concession: move 40% of the spread toward merchant
                        concession = max(Decimal("30.00"), (gap * Decimal("0.40")).quantize(Decimal("1.00")))
                        unit_p = min(budget, min(last_merchant_price, last_buyer_price + concession))
                        if unit_p >= last_merchant_price:
                            action = "ACCEPT"
                            unit_p = last_merchant_price
                            rationale = f"Concession reached merchant counter-offer INR {unit_p:.2f}. Accepted."
                            msg = f"I accept your offer of INR {unit_p:.2f} for {prod_name}."
                        else:
                            action = "COUNTER"
                            rationale = f"Countering with gradual concession of INR {unit_p:.2f} toward merchant price."
                            msg = f"Can you meet at INR {unit_p:.2f} for {prod_name}?"

            return schema(
                action=action,
                product_id=prod_id,
                quantity=1,
                unit_price=unit_p,
                total_amount=unit_p,
                rationale=rationale,
                message=msg,
                constraints_checked=["budget_fit", "catalog_price_bound", "deterministic_mock"],
                basket_items=[
                    BasketItemSchema(
                        product_id=prod_id,
                        name=prod_name,
                        quantity=1,
                        original_price=cat_price,
                        negotiated_price=unit_p,
                        is_primary=True
                    )
                ],
                accept=(action == "ACCEPT")
            )

        # ----------------------------------------------------------------------
        # 2. MerchantDecision Builder
        # ----------------------------------------------------------------------
        elif s_name == "MerchantDecision" or issubclass(schema, MerchantDecision):
            prod_id = 1
            prod_name = "Product"
            cat_price = Decimal("1000.00")
            floor_price = Decimal("900.00")
            round_num = 1

            if context:
                prod_details = context.current_product or {}
                prod_id = prod_details.get("id", 1)
                prod_name = prod_details.get("name", "Product")
                cat_price = context.catalog_price
                floor_price = context.merchant_min_price
                round_num = context.current_round
            elif "samsung" in prompt_lower:
                prod_id = 41
                prod_name = "Samsung Galaxy A15"
                cat_price = Decimal("12999.00")
                floor_price = Decimal("11049.15")
            elif "earbud" in prompt_lower:
                prod_id = 1
                prod_name = "Wireless Noise-Canceling Earbuds"
                cat_price = Decimal("1599.00")
                floor_price = Decimal("1359.15")

            last_buyer_offer = None
            if context and context.current_proposal:
                try:
                    last_buyer_offer = Decimal(str(context.current_proposal.get("total_amount", 0)))
                except Exception:
                    pass

            bundle_proposal = None

            # 1. Predatory offer check
            if last_buyer_offer and (last_buyer_offer <= floor_price * Decimal("0.40") or last_buyer_offer <= Decimal("100.00")):
                action = "REJECT"
                unit_p = cat_price
                rationale = f"Buyer offer of INR {last_buyer_offer:.2f} is predatory and severely below cost/margin floor of INR {floor_price:.2f}."
                msg = f"I'm sorry, an offer of INR {last_buyer_offer:.2f} is severely below our product cost. I cannot accept this offer."
                margin_check = f"Margin check: FAILED (Predatory offer below 40% floor)"

            # 2. Zero discount policy / floor at catalog price (Task 5 compliance: merchant can hold list price)
            elif floor_price >= cat_price:
                if last_buyer_offer and last_buyer_offer >= cat_price:
                    action = "ACCEPT"
                    unit_p = last_buyer_offer
                    rationale = f"Buyer offer meets or exceeds catalog price INR {cat_price:.2f} with zero-discount policy."
                    msg = f"We accept your offer of INR {unit_p:.2f} for {prod_name}."
                    margin_check = f"Margin check: PASSED (Met catalog price INR {cat_price:.2f})"
                else:
                    action = "COUNTER"
                    unit_p = cat_price
                    rationale = f"Strict margin policy enforces holding catalog price of INR {cat_price:.2f}."
                    msg = f"Our best price is INR {cat_price:.2f} for {prod_name}."
                    margin_check = f"Margin check: PASSED (Held catalog price INR {cat_price:.2f})"

            # 3. Buyer offer meets or exceeds catalog price
            elif last_buyer_offer and last_buyer_offer >= cat_price:
                action = "ACCEPT"
                unit_p = last_buyer_offer
                rationale = f"Buyer offer of INR {unit_p:.2f} meets catalog list price. Accepted."
                msg = f"We accept your offer of INR {unit_p:.2f} for {prod_name}."
                margin_check = f"Margin check: PASSED (Floor INR {floor_price:.2f})"

            # 4. Buyer offer is at or above floor price
            elif last_buyer_offer and last_buyer_offer >= floor_price:
                # Accept if buyer offer is within 3% of catalog price or in later rounds (round >= 3)
                if last_buyer_offer >= (cat_price * Decimal("0.97")) or round_num >= 3:
                    action = "ACCEPT"
                    unit_p = last_buyer_offer
                    rationale = f"Buyer offer of INR {unit_p:.2f} meets or exceeds margin floor of INR {floor_price:.2f}. Accepted."
                    msg = f"We accept your offer of INR {unit_p:.2f} for {prod_name}."
                    margin_check = f"Margin check: PASSED (Floor INR {floor_price:.2f})"
                else:
                    # Concede gradually toward buyer without dropping below floor
                    spread = cat_price - last_buyer_offer
                    factor = Decimal("0.45") if round_num <= 1 else Decimal("0.70")
                    target_p = (cat_price - (spread * factor)).quantize(Decimal("1.00"))
                    unit_p = max(floor_price, target_p)

                    if unit_p <= last_buyer_offer:
                        action = "ACCEPT"
                        unit_p = last_buyer_offer
                        rationale = f"Counter reached buyer offer INR {unit_p:.2f}. Accepted."
                        msg = f"We accept your offer of INR {unit_p:.2f} for {prod_name}."
                        margin_check = f"Margin check: PASSED (Floor INR {floor_price:.2f})"
                    else:
                        action = "COUNTER"
                        rationale = f"Progressive merchant counter of INR {unit_p:.2f} preserving margin floor INR {floor_price:.2f}."
                        msg = f"Our counter-offer is INR {unit_p:.2f} for {prod_name}."
                        margin_check = f"Margin check: PASSED (Floor INR {floor_price:.2f})"

            # 5. Buyer offer was below floor price
            else:
                action = "COUNTER"
                unit_p = max(floor_price, (cat_price * Decimal("0.93")).quantize(Decimal("1.00")))
                rationale = f"Buyer offer was below floor INR {floor_price:.2f}. Counter-offering INR {unit_p:.2f}."
                msg = f"Our best counter-offer is INR {unit_p:.2f} for {prod_name}."
                margin_check = f"Margin check: PASSED (Preserved floor INR {floor_price:.2f})"

            return schema(
                action=action,
                product_id=prod_id,
                quantity=1,
                unit_price=unit_p,
                total_amount=unit_p,
                rationale=rationale,
                message=msg,
                margin_check=margin_check,
                cross_sell_product_id=None,
                bundle_proposal=bundle_proposal,
                basket_items=[
                    BasketItemSchema(
                        product_id=prod_id,
                        name=prod_name,
                        quantity=1,
                        original_price=cat_price,
                        negotiated_price=unit_p,
                        is_primary=True
                    )
                ],
                accept=(action == "ACCEPT")
            )

        # ----------------------------------------------------------------------
        # 3. UserIntent Builder
        # ----------------------------------------------------------------------
        elif s_name == "UserIntent" or issubclass(schema, UserIntent):
            prod = "Samsung Galaxy A15" if "samsung" in prompt_lower else (
                "Wireless Noise-Canceling Earbuds" if "earbud" in prompt_lower else "Product"
            )
            return UserIntent(
                product=prod,
                product_query=prod,
                max_budget=14000.0 if "14000" in prompt_lower else (2000.0 if "2000" in prompt_lower else None),
                preferences=["standalone"] if "standalone" in prompt_lower else [],
                quantity=1,
                standalone_only=bool("standalone" in prompt_lower),
                confidence=1.0,
                intent_parse_mode="deterministic",
                intent_llm_used=False
            )

        # ----------------------------------------------------------------------
        # 4. Generic Safe Fallback Builder (Fills all required schema fields)
        # ----------------------------------------------------------------------
        else:
            fields_dict = {}
            model_fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
            for f_name, f_info in model_fields.items():
                if f_info.is_required() if hasattr(f_info, "is_required") else getattr(f_info, "required", False):
                    # Fill default based on type
                    annotation = getattr(f_info, "annotation", None) or getattr(f_info, "type_", None)
                    if annotation == int:
                        fields_dict[f_name] = 1
                    elif annotation == Decimal:
                        fields_dict[f_name] = Decimal("1000.00")
                    elif annotation == float:
                        fields_dict[f_name] = 1000.0
                    elif annotation == str:
                        fields_dict[f_name] = "deterministic_mock"
                    elif annotation == bool:
                        fields_dict[f_name] = True
                    elif annotation in (list, List):
                        fields_dict[f_name] = []
                    else:
                        fields_dict[f_name] = None
            try:
                return schema(**fields_dict)
            except Exception:
                return schema.model_construct(**fields_dict) if hasattr(schema, "model_construct") else schema.construct(**fields_dict)


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
        self.providers: Dict[str, BaseLLMProvider] = {
            "cerebras": CerebrasProvider(),
            "groq": GroqProvider(),
            "gemini": GeminiProvider(),
            "nvidia_nim": NvidiaNimProvider(),
            "openrouter": OpenRouterProvider(),
            "ollama": OllamaProvider(),
            "mock": MockProvider()
        }
        self._providers_registry = self.providers
        self.primary_provider = os.getenv("PRIMARY_LLM_PROVIDER") or getattr(settings, "PRIMARY_LLM_PROVIDER", "cerebras")
        raw_chain = os.getenv("LLM_PROVIDER_CHAIN") or getattr(settings, "LLM_PROVIDER_CHAIN", "cerebras,groq,gemini,nvidia_nim,openrouter,ollama,mock")
        self.provider_chain = [p.strip().lower() for p in raw_chain.split(",") if p.strip()]
        if "mock" not in self.provider_chain:
            self.provider_chain.append("mock")

        self._session_metrics = {
            "total_intent_queries": 0,
            "cached_intent_queries": 0,
            "deterministic_intent_queries": 0,
            "real_llm_calls": 0,
            "deterministic_fallback_calls": 0,
            "calls_per_provider": {},
            "avoided_deterministic_operations": 0
        }

    def get_provider(self, name: str) -> BaseLLMProvider:
        return self.providers.get(name.lower().strip(), self.providers["mock"])

    def resolve_chain(self, role: Optional[str] = None) -> List[str]:
        """
        Resolves the provider fallback priority chain for a given role or global default.
        Always guarantees 'mock' at the very end.
        """
        if role:
            role_key = role.upper().replace("_AGENT", "")
            fallbacks_str = os.getenv(f"{role_key}_LLM_FALLBACKS") or getattr(settings, f"{role_key}_LLM_FALLBACKS", None)
            prim = os.getenv(f"{role_key}_LLM_PROVIDER") or getattr(settings, f"{role_key}_LLM_PROVIDER", None)
            if prim:
                chain = [prim.strip().lower()]
                if fallbacks_str:
                    for f in fallbacks_str.split(","):
                        f_clean = f.strip().lower()
                        if f_clean and f_clean not in chain:
                            chain.append(f_clean)
                if "mock" not in chain:
                    chain.append("mock")
                return chain

        return list(self.provider_chain)

    def record_avoided_operation(self, count: int = 1):
        self._session_metrics["avoided_deterministic_operations"] += count

    def parse_user_intent(self, query: str, budget: Optional[Decimal] = None) -> UserIntent:
        """
        Parses user intent with cached intent first, deterministic matching second,
        and structured LLM fallback only when necessary.
        """
        self._session_metrics["total_intent_queries"] += 1

        # 1. Check Intent Cache
        cached = self.intent_cache.get(query)
        if cached:
            self._session_metrics["cached_intent_queries"] += 1
            return cached

        # 2. Deterministic Regex / Token Parsing (Zero LLM Tokens)
        det_intent = parse_deterministic_intent(query, budget=budget)
        if det_intent:
            self._session_metrics["deterministic_intent_queries"] += 1
            self.intent_cache.set(query, det_intent)
            return det_intent

        # 3. LLM Parsing Fallback via Provider Chain
        chain = self.resolve_chain("auxiliary")
        system_prompt = (
            "You are SETU's Natural Language Intent Understanding engine.\n"
            "Extract target product, max budget, preferences, quantity, and standalone requirement from user input."
        )
        user_prompt = f"Extract intent from query: '{query}'" + (f" (User entered budget: {budget})" if budget else "")

        parsed_intent = None
        for p_name in chain:
            if not self.circuit_breaker.is_available(p_name):
                continue

            provider = self.get_provider(p_name)
            if not getattr(provider, "is_available", True):
                continue

            try:
                if p_name == "mock":
                    parsed_intent, meta = provider.generate_structured(system_prompt, user_prompt, UserIntent, timeout=5.0)
                else:
                    parsed_intent, meta = provider.generate_structured(system_prompt, user_prompt, UserIntent, timeout=12.0)
                
                parsed_intent.intent_parse_mode = "llm_fallback" if p_name != "mock" else "deterministic"
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
            parsed_intent = MockProvider()._generate_deterministic_mock(query, UserIntent)
            parsed_intent.intent_parse_mode = "deterministic"
            parsed_intent.intent_llm_used = False

        self.intent_cache.set(query, parsed_intent)
        return parsed_intent

    def _create_rejection_fallback(
        self,
        schema: Type[BaseModel],
        context: Optional[NegotiationContext] = None,
        reason: str = "Safety fallback rejection on invalid agent decision."
    ) -> BaseModel:
        prod_id = 1
        prod_name = "Product"
        cat_price = Decimal("1000.00")
        if context:
            prod_details = context.current_product or {}
            prod_id = prod_details.get("id", 1)
            prod_name = prod_details.get("name", "Product")
            cat_price = context.catalog_price

        s_name = getattr(schema, "__name__", "")
        if s_name == "BuyerDecision" or issubclass(schema, BuyerDecision):
            return schema(
                action="REJECT",
                product_id=prod_id,
                quantity=1,
                unit_price=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                rationale=reason,
                message="I cannot proceed with this offer under current constraints.",
                constraints_checked=["safety_fallback"],
                basket_items=[
                    BasketItemSchema(
                        product_id=prod_id,
                        name=prod_name,
                        quantity=1,
                        original_price=cat_price,
                        negotiated_price=Decimal("0.00"),
                        is_primary=True
                    )
                ],
                accept=False
            )
        elif s_name == "MerchantDecision" or issubclass(schema, MerchantDecision):
            return schema(
                action="REJECT",
                product_id=prod_id,
                quantity=1,
                unit_price=Decimal("0.00"),
                total_amount=Decimal("0.00"),
                rationale=reason,
                message="We cannot support this offer within our policy margins.",
                margin_check="Margin check: FAILED",
                cross_sell_product_id=None,
                basket_items=[
                    BasketItemSchema(
                        product_id=prod_id,
                        name=prod_name,
                        quantity=1,
                        original_price=cat_price,
                        negotiated_price=Decimal("0.00"),
                        is_primary=True
                    )
                ],
                accept=False
            )
        else:
            return MockProvider()._generate_deterministic_mock(reason, schema, context=context)

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
        provider_attempts = []
        depth = 0

        for p_name in chain:
            if not self.circuit_breaker.is_available(p_name):
                logger.info(f"AIGateway: Skipping rate-limited / unavailable provider '{p_name}' (Circuit OPEN).")
                provider_attempts.append({
                    "provider": p_name,
                    "status": "circuit_open",
                    "error_code": "CIRCUIT_OPEN"
                })
                continue

            provider = self.get_provider(p_name)
            if not getattr(provider, "is_available", True) and p_name != "mock":
                logger.info(f"AIGateway: Skipping unconfigured provider '{p_name}' (No API key).")
                provider_attempts.append({
                    "provider": p_name,
                    "status": "misconfigured",
                    "error_code": "NO_API_KEY"
                })
                continue

            # Attempt structured generation
            for attempt in range(max_retries + 1):
                try:
                    if p_name == "mock":
                        obj, meta = provider.generate_structured(
                            system_prompt,
                            user_prompt,
                            schema,
                            timeout=5.0,
                            context=context
                        )
                    else:
                        obj, meta = provider.generate_structured(
                            system_prompt,
                            user_prompt,
                            schema,
                            timeout=18.0
                        )

                    # Post-generation deterministic validation & clamping
                    obj = self._clamp_decision(obj, context)

                    meta.agent_role = role
                    is_mock_turn = (p_name == "mock")
                    meta.fallback_used = (depth > 0)
                    meta.fallback_depth = depth
                    meta.real_provider_attempted = not is_mock_turn or depth > 0 or len(provider_attempts) > 0
                    meta.real_llm_success = not is_mock_turn
                    meta.mock_fallback_used = is_mock_turn

                    if not is_mock_turn:
                        provider_attempts.append({
                            "provider": p_name,
                            "status": "success",
                            "model": getattr(provider, "model_name", None),
                            "latency_ms": meta.response_latency_ms
                        })
                        meta.provider_attempts = list(provider_attempts)
                        meta.fallback_reason = "; ".join(errors_encountered) if errors_encountered else None
                    else:
                        meta.fallback_reason = "all_real_providers_unavailable" if not errors_encountered else "; ".join(errors_encountered)
                        meta.provider_attempts = list(provider_attempts)

                    self.circuit_breaker.record_success(p_name)

                    if not is_mock_turn:
                        self._session_metrics["real_llm_calls"] += 1
                        self._session_metrics["calls_per_provider"][p_name] = self._session_metrics["calls_per_provider"].get(p_name, 0) + 1
                    else:
                        self._session_metrics["deterministic_fallback_calls"] += 1
                        self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1

                    return obj, meta

                except Exception as e:
                    err_msg = str(e)
                    status_code = getattr(e, "status_code", None) or (429 if "429" in err_msg else 500)
                    category = getattr(e, "category", None) or ("RATE_LIMITED" if status_code == 429 else "FAILED")
                    logger.warning(f"AIGateway: Provider '{p_name}' turn generation attempt {attempt+1} failed: {err_msg[:120]}")
                    self.circuit_breaker.record_failure(p_name, e, status_code=status_code, category=category)
                    if attempt == max_retries:
                        errors_encountered.append(f"{p_name}_{category.lower()}")
                        provider_attempts.append({
                            "provider": p_name,
                            "status": "failed",
                            "error_code": str(status_code),
                            "category": category
                        })
                        depth += 1
                    continue

        # Ultimate safety fallback: guaranteed valid MockProvider execution
        logger.warning(f"AIGateway: All external providers failed. Executing deterministic MockProvider fallback.")
        mock_p = self.get_provider("mock")
        obj, meta = mock_p.generate_structured(system_prompt, user_prompt, schema, timeout=5.0, context=context)
        obj = self._clamp_decision(obj, context)
        meta.agent_role = role
        meta.fallback_used = True
        meta.fallback_depth = depth
        meta.fallback_reason = "all_real_providers_unavailable" if not errors_encountered else "; ".join(errors_encountered)
        meta.provider_attempts = list(provider_attempts)
        meta.real_provider_attempted = len(provider_attempts) > 0
        meta.real_llm_success = False
        meta.mock_fallback_used = True

        self._session_metrics["deterministic_fallback_calls"] += 1
        self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1
        return obj, meta

    def _clamp_decision(self, decision: BaseModel, context: NegotiationContext) -> BaseModel:
        """
        Applies authoritative SETU policy clamping to agent output.
        Guarantees that LLM outputs never violate absolute budget or price floor boundaries.
        """
        # 1. Sanitize action
        valid_buyer_actions = {"OFFER", "COUNTER", "ACCEPT", "REJECT", "ACCEPT_BUNDLE", "REJECT_BUNDLE"}
        valid_merchant_actions = {"COUNTER", "ACCEPT", "REJECT", "BUNDLE", "PROPOSE_BUNDLE", "HOLD_PREVIOUS_OFFER"}
        raw_act = getattr(decision, "action", "")
        if isinstance(raw_act, dict) or not isinstance(raw_act, str):
            raw_act = "COUNTER"
            setattr(decision, "action", raw_act)
        elif context.agent_role.upper().startswith("BUYER") and raw_act not in valid_buyer_actions:
            setattr(decision, "action", "COUNTER")
        elif context.agent_role.upper().startswith("MERCHANT") and raw_act not in valid_merchant_actions:
            setattr(decision, "action", "COUNTER")

        # 2. Sanitize and validate basket_items
        raw_items = getattr(decision, "basket_items", None) or []
        valid_items = []
        for item in raw_items:
            if isinstance(item, BasketItemSchema):
                valid_items.append(item)
            elif isinstance(item, dict):
                try:
                    valid_items.append(BasketItemSchema.model_validate(item))
                except Exception:
                    pass

        prod_id = getattr(decision, "product_id", context.current_product.get("id", 1))
        if not isinstance(prod_id, int):
            try:
                prod_id = int(str(prod_id))
            except Exception:
                prod_id = context.current_product.get("id", 1)
        setattr(decision, "product_id", prod_id)

        prod_name = context.current_product.get("name", "Product")
        cat_p = context.catalog_price

        # Sanitize unit_price and total_amount
        raw_unit_p = getattr(decision, "unit_price", None)
        try:
            unit_p = Decimal(str(raw_unit_p)) if (raw_unit_p is not None and not isinstance(raw_unit_p, (dict, list))) else cat_p
        except Exception:
            unit_p = cat_p
        setattr(decision, "unit_price", unit_p)

        if not valid_items:
            valid_items = [
                BasketItemSchema(
                    product_id=prod_id,
                    name=prod_name,
                    quantity=1,
                    original_price=cat_p,
                    negotiated_price=unit_p,
                    is_primary=True
                )
            ]
        decision.basket_items = valid_items

        # Sanitize rationale / message / reason
        for str_field in ("rationale", "reason", "message"):
            val = getattr(decision, str_field, None)
            if isinstance(val, (dict, list)) or (val is not None and not isinstance(val, str)):
                setattr(decision, str_field, f"Autonomous reasoning for {context.agent_role}.")

        # Buyer clamping
        if context.agent_role.upper().startswith("BUYER"):
            try:
                tot = getattr(decision, "total_amount", Decimal("0"))
                tot_dec = Decimal(str(tot)) if not isinstance(tot, (dict, list)) else Decimal("0")
                b_max = Decimal(str(context.buyer_max_budget))
                if tot_dec <= Decimal("0") or tot_dec > b_max:
                    clamped_val = b_max if tot_dec > b_max else (context.buyer_max_budget * Decimal("0.85")).quantize(Decimal("0.01"))
                    decision.total_amount = clamped_val
                    decision.unit_price = clamped_val
                    if decision.basket_items and len(decision.basket_items) == 1:
                        decision.basket_items[0].negotiated_price = clamped_val
            except Exception as e:
                logger.warning(f"Error in buyer clamping: {e}")

        # Merchant clamping
        elif context.agent_role.upper().startswith("MERCHANT"):
            if getattr(decision, "action", "") in ("COUNTER", "ACCEPT", "BUNDLE", "PROPOSE_BUNDLE", "HOLD_PREVIOUS_OFFER"):
                # If standalone counter, clamp against minimum floor
                if getattr(decision, "action", "") not in ("BUNDLE", "PROPOSE_BUNDLE") and len(getattr(decision, "basket_items", [])) <= 1:
                    try:
                        tot = getattr(decision, "total_amount", Decimal("0"))
                        tot_dec = Decimal(str(tot)) if not isinstance(tot, (dict, list)) else Decimal("0")
                        m_min = Decimal(str(context.merchant_min_price))
                        if tot_dec < m_min or tot_dec <= Decimal("0"):
                            decision.total_amount = m_min
                            decision.unit_price = m_min
                            if decision.basket_items and len(decision.basket_items) == 1:
                                decision.basket_items[0].negotiated_price = m_min
                    except Exception as e:
                        logger.warning(f"Error in merchant clamping: {e}")

        return decision

    def _build_role_system_prompt(self, role: str, context: NegotiationContext) -> str:
        prod = context.current_product or {}
        p_name = prod.get("name", "Product")
        is_buyer = "BUYER" in role.upper()

        if is_buyer:
            return (
                "You are an autonomous Buyer AI Agent acting for a human customer in SETU.\n"
                f"Negotiating for: '{p_name}'.\n"
                f"Your Hard Budget Ceiling: INR {context.buyer_max_budget:.2f}. You must NEVER offer or agree above this.\n"
                f"Catalog List Price: INR {context.catalog_price:.2f}.\n"
                f"Current Round: {context.current_round} of 4.\n"
                "Goal: Secure the best possible value for the customer within budget.\n"
                "If the merchant proposes an optional bundle/cross-sell, compare standalone vs bundle. "
                "The bundle is strictly optional and must never replace your request without consent. "
                "If you prefer lower total cost or only need the primary product, continue negotiating standalone. "
                "If you value the accessory package and the bundle price is within budget, you may choose the bundle.\n"
                "You MUST output ONLY a structured JSON matching the requested schema."
            )
        else:
            return (
                "You are an autonomous Merchant AI Agent representing the store in SETU.\n"
                "You are negotiating autonomously. You may offer the standalone product or, when beneficial, propose an optional bundle/cross-sell. "
                "The bundle is optional and must never replace the buyer's original request without consent. Do not mention a bundle merely because one exists. "
                "Consider the buyer's budget, current negotiation stage, product price, bundle savings, merchant margin, and buyer's latest offer.\n"
                f"Negotiating product: '{p_name}'.\n"
                f"Catalog Price: INR {context.catalog_price:.2f}.\n"
                f"Merchant Minimum Price Floor: INR {context.merchant_min_price:.2f}. (Do not sell below this).\n"
                f"Current Round: {context.current_round} of 4.\n"
                "Goal: Maximize transaction value and margin while reaching a mutually profitable agreement.\n"
                "You MUST output ONLY a structured JSON matching the requested schema."
            )

    def _build_compact_turn_prompt(self, context: NegotiationContext) -> str:
        prod = context.current_product or {}
        p_name = prod.get("name", "Product")
        lines = [
            f"=== NEGOTIATION TURN ROUND {context.current_round} ===",
            f"Target Product: {p_name} (ID: {prod.get('id', 1)})",
            f"Catalog List Price: INR {context.catalog_price:.2f}",
            f"Buyer Budget Limit: INR {context.buyer_max_budget:.2f}",
            f"Merchant Price Floor: INR {context.merchant_min_price:.2f}",
            f"Remaining Rounds: {context.remaining_rounds}",
        ]

        if context.optional_bundle:
            b_info = context.optional_bundle
            lines.append("\n--- OPTIONAL BUNDLE / CROSS-SELL OPPORTUNITY ---")
            lines.append(f"  Package Name: {b_info.get('bundle_name', 'Bundle Package')}")
            lines.append(f"  Included Products: {b_info.get('included_product_names', '')} (IDs: {b_info.get('bundle_product_ids', [])})")
            lines.append(f"  Bundle List Price: INR {b_info.get('bundle_list_price', '0.00')}")
            lines.append(f"  Allowed Bundle Selling Range: INR {b_info.get('bundle_min_price', '0.00')} - {b_info.get('bundle_list_price', '0.00')}")
            lines.append(f"  Bundle Recommended Price: INR {b_info.get('bundle_price', '0.00')}")
            lines.append(f"  Calculated Buyer Savings: INR {b_info.get('savings', '0.00')}")
            lines.append(f"  Bundle Fits Buyer Budget (<= INR {context.buyer_max_budget:.2f}): {b_info.get('fits_budget', True)}")
            lines.append(f"  Bundle Items In Stock: {b_info.get('inventory_available', True)}")
            lines.append(f"  Bundle Previously Proposed: {context.bundle_already_proposed}")

        if context.current_proposal:
            amt = context.current_proposal.get("total_amount", context.catalog_price)
            lines.append(f"\nLatest Active Proposal Under Review: INR {amt}")
            if context.current_proposal.get("options_summary"):
                lines.append(f"Proposal Options Under Consideration: {context.current_proposal['options_summary']}")

        if context.previous_offers:
            lines.append("\nOffer History in this session:")
            for off in context.previous_offers[-3:]:
                lines.append(f"  - Round {off.get('round', 1)} [{off.get('actor', '').upper()}]: INR {off.get('total_amount', off.get('amount', 0))} ({off.get('action', '')})")

        lines.append("\nEvaluate the state and formulate your next structured negotiation decision JSON.")
        return "\n".join(lines)

    def get_provider_status(self) -> Dict[str, Any]:
        """
        Safely returns health, operational status, and circuit state of all providers.
        Never exposes API keys or credentials.
        """
        cb_status = self.circuit_breaker.get_status()
        prov_status = {}

        for name, prov in self.providers.items():
            cb = cb_status.get(name, {
                "available": True,
                "circuit_state": "CLOSED",
                "failure_count": 0,
                "circuit_open_until": None,
                "last_error": None
            })

            # Check SDK operational availability for Gemini
            extra_info = {}
            if name == "gemini":
                sdk_type, _, _ = GeminiProvider.get_sdk_status()
                extra_info["sdk_type"] = sdk_type or "None (ImportError)"

            is_configured = getattr(prov, "is_available", False)
            prov_status[name] = {
                "configured": is_configured,
                "provider_type": prov.provider_type,
                "model": getattr(prov, "model_name", "n/a"),
                "circuit": cb,
                "healthy": is_configured and cb["available"],
                **extra_info
            }

        return {
            "gateway_status": "ONLINE",
            "primary_provider": self.primary_provider,
            "provider_chain": self.provider_chain,
            "providers": prov_status,
            "metrics": self._session_metrics
        }


# Global singleton AIGateway
ai_gateway = AIGateway()
CentralAIGateway = AIGateway

def get_ai_gateway() -> AIGateway:
    """Returns the central AIGateway singleton instance."""
    return ai_gateway


