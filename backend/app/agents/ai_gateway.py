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


# ==============================================================================
# 2. CIRCUIT BREAKER
# ==============================================================================

class CircuitBreaker:
    """
    In-memory thread-safe circuit breaker for external LLM providers.
    Quickly trips to OPEN state on 429, quota limits, auth errors, billing errors,
    404 model not found, or repeated timeouts, preventing request delays on dead endpoints.
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
                    # Cooldown expired -> test transition to half-open / closed
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

            if is_fast_trip or state["failure_count"] >= 2:
                state["circuit_state"] = "OPEN"
                state["circuit_open_until"] = time.time() + self.cooldown_seconds
                logger.warning(
                    f"CircuitBreaker: Tripped OPEN for provider '{provider_name}' "
                    f"(status={status_code}, category={state['last_category']}, error={state['last_error']}). "
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
                    "last_category": s.get("last_category"),
                    "last_error": s["last_error"],
                    "total_calls": s["total_calls"],
                    "failed_calls": s["failed_calls"]
                }
            return res


# Global CircuitBreaker instance
circuit_breaker = CircuitBreaker(cooldown_seconds=getattr(settings, "CIRCUIT_BREAKER_COOLDOWN_SECONDS", 60.0))


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
            round_num = 1

            if context:
                prod_details = context.current_product or {}
                prod_id = prod_details.get("id", 1)
                prod_name = prod_details.get("name", "Product")
                cat_price = context.catalog_price
                budget = context.buyer_max_budget
                round_num = context.current_round
            elif "samsung" in prompt_lower:
                prod_id = 41
                prod_name = "Samsung Galaxy A15"
                cat_price = Decimal("12999.00")
                budget = Decimal("14000.00")
            elif "earbud" in prompt_lower:
                prod_id = 1
                prod_name = "Wireless Noise-Canceling Earbuds"
                cat_price = Decimal("1599.00")
                budget = Decimal("2000.00")

            is_round_1 = (round_num == 1) or ("round 1" in prompt_lower) or ("opening offer" in prompt_lower)
            
            # Opening offer calculation (85% of catalog or within budget)
            if is_round_1:
                unit_p = min(budget, (cat_price * Decimal("0.85")).quantize(Decimal("0.01")))
                action = "OFFER"
                rationale = f"Deterministic initial buyer offer targeting ~15% discount within budget ceiling of INR {budget:.2f}."
                msg = f"Hi, I would like to offer INR {unit_p:.2f} for {prod_name}."
            else:
                # Evaluation of merchant counter-offer
                last_merchant_price = None
                if context and context.current_proposal:
                    last_merchant_price = Decimal(str(context.current_proposal.get("total_amount", 0)))

                if last_merchant_price and last_merchant_price <= budget:
                    action = "ACCEPT"
                    unit_p = last_merchant_price
                    rationale = f"Merchant counter-offer of INR {unit_p:.2f} is within buyer budget of INR {budget:.2f}. Accepted."
                    msg = f"Deal agreed at INR {unit_p:.2f} for {prod_name}."
                else:
                    action = "COUNTER"
                    unit_p = min(budget, (cat_price * Decimal("0.90")).quantize(Decimal("0.01")))
                    rationale = f"Countering with revised offer of INR {unit_p:.2f} within budget limit."
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

            if context:
                prod_details = context.current_product or {}
                prod_id = prod_details.get("id", 1)
                prod_name = prod_details.get("name", "Product")
                cat_price = context.catalog_price
                floor_price = context.merchant_min_price
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
                last_buyer_offer = Decimal(str(context.current_proposal.get("total_amount", 0)))

            if last_buyer_offer and last_buyer_offer >= floor_price:
                action = "ACCEPT"
                unit_p = last_buyer_offer
                rationale = f"Buyer offer of INR {unit_p:.2f} meets or exceeds merchant price floor of INR {floor_price:.2f}. Accepted."
                msg = f"We accept your offer of INR {unit_p:.2f} for {prod_name}."
            else:
                action = "COUNTER"
                # Offer middle ground between catalog and floor
                unit_p = max(floor_price, (cat_price * Decimal("0.95")).quantize(Decimal("0.01")))
                rationale = f"Buyer offer was below floor. Counter-offering INR {unit_p:.2f} preserving minimum margin requirements."
                msg = f"Our best counter-offer is INR {unit_p:.2f} for {prod_name}."

            return schema(
                action=action,
                product_id=prod_id,
                quantity=1,
                unit_price=unit_p,
                total_amount=unit_p,
                rationale=rationale,
                message=msg,
                margin_check=f"Margin check: PASSED (Preserved floor INR {floor_price:.2f})",
                cross_sell_product_id=None,
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
        depth = 0

        for p_name in chain:
            if not self.circuit_breaker.is_available(p_name):
                logger.info(f"AIGateway: Skipping rate-limited / unavailable provider '{p_name}' (Circuit OPEN).")
                continue

            provider = self.get_provider(p_name)
            if not getattr(provider, "is_available", True):
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
                    meta.fallback_used = (depth > 0 or p_name == "mock")
                    meta.fallback_depth = depth
                    meta.fallback_reason = "; ".join(errors_encountered) if errors_encountered else None

                    self.circuit_breaker.record_success(p_name)

                    if p_name != "mock":
                        self._session_metrics["real_llm_calls"] += 1
                        self._session_metrics["calls_per_provider"][p_name] = self._session_metrics["calls_per_provider"].get(p_name, 0) + 1
                    else:
                        self._session_metrics["deterministic_fallback_calls"] += 1
                        self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1

                    return obj, meta

                except Exception as e:
                    err_msg = str(e)
                    logger.warning(f"AIGateway: Provider '{p_name}' turn generation attempt {attempt+1} failed: {err_msg[:120]}")
                    if attempt == max_retries:
                        errors_encountered.append(f"{p_name}: {err_msg[:80]}")
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
        meta.fallback_reason = "All real LLM providers exhausted or unavailable: " + "; ".join(errors_encountered)

        self._session_metrics["deterministic_fallback_calls"] += 1
        self._session_metrics["calls_per_provider"]["mock"] = self._session_metrics["calls_per_provider"].get("mock", 0) + 1
        return obj, meta

    def _clamp_decision(self, decision: BaseModel, context: NegotiationContext) -> BaseModel:
        """
        Applies authoritative SETU policy clamping to agent output.
        Guarantees that LLM outputs never violate absolute budget or price floor boundaries.
        """
        # Ensure basket_items is populated
        if not getattr(decision, "basket_items", None):
            prod_id = getattr(decision, "product_id", context.current_product.get("id", 1))
            prod_name = context.current_product.get("name", "Product")
            cat_p = context.catalog_price
            unit_p = getattr(decision, "unit_price", cat_p)
            decision.basket_items = [
                BasketItemSchema(
                    product_id=prod_id,
                    name=prod_name,
                    quantity=getattr(decision, "quantity", 1),
                    original_price=cat_p,
                    negotiated_price=unit_p,
                    is_primary=True
                )
            ]

        # Buyer clamping
        if context.agent_role.upper().startswith("BUYER"):
            if getattr(decision, "total_amount", Decimal("0")) > context.buyer_max_budget:
                decision.total_amount = context.buyer_max_budget
                decision.unit_price = context.buyer_max_budget
                if decision.basket_items and len(decision.basket_items) == 1:
                    decision.basket_items[0].negotiated_price = context.buyer_max_budget

        # Merchant clamping
        elif context.agent_role.upper().startswith("MERCHANT"):
            if getattr(decision, "action", "") in ("COUNTER", "ACCEPT", "BUNDLE"):
                if getattr(decision, "total_amount", Decimal("0")) < context.merchant_min_price:
                    decision.total_amount = context.merchant_min_price
                    decision.unit_price = context.merchant_min_price
                    if decision.basket_items and len(decision.basket_items) == 1:
                        decision.basket_items[0].negotiated_price = context.merchant_min_price

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
                "You MUST output ONLY a structured JSON matching the requested schema."
            )
        else:
            return (
                "You are an autonomous Merchant AI Agent representing the store in SETU.\n"
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

        if context.current_proposal:
            amt = context.current_proposal.get("total_amount", context.catalog_price)
            lines.append(f"Latest Active Proposal Under Review: INR {amt}")

        if context.previous_offers:
            lines.append("Offer History in this session:")
            for off in context.previous_offers[-3:]:
                lines.append(f"  - Round {off.get('round', 1)} [{off.get('actor', '').upper()}]: INR {off.get('amount', 0)} ({off.get('action', '')})")

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

def get_ai_gateway() -> AIGateway:
    """Returns the central AIGateway singleton instance."""
    return ai_gateway

