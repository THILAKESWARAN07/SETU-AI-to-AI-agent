from pydantic import BaseModel, ConfigDict, Field, field_serializer
from typing import List, Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timezone

def serialize_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

# --- PRODUCT SCHEMAS ---
class ProductBase(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    price: Decimal
    cost: Decimal
    inventory: int = 0
    attributes: Dict[str, Any] = Field(default_factory=dict)
    related_product_ids: List[int] = Field(default_factory=list)
    min_selling_price: Optional[Decimal] = None
    active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductSchema(ProductBase):
    id: int
    
    model_config = ConfigDict(from_attributes=True)


# --- POLICY SCHEMAS ---
class MerchantPolicyBase(BaseModel):
    max_discount_percent: Decimal
    min_margin_percent: Decimal
    max_auto_order_amount: Decimal
    require_approval_above: Decimal
    policy_version: str
    active: bool = True

class MerchantPolicyCreate(MerchantPolicyBase):
    pass

class MerchantPolicySchema(MerchantPolicyBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# --- PURCHASE REQUEST SCHEMAS ---
class PurchaseRequestBase(BaseModel):
    buyer_id: str
    product_id: int
    quantity: int = 1
    unit_price: Decimal  # catalog price snapshot
    original_amount: Decimal  # unit_price * quantity
    final_amount: Decimal  # proposed total price after discount
    discount_percent: Decimal
    currency: str = "INR"
    reason: Optional[str] = None
    basket: Optional[Dict[str, Any]] = None

class PurchaseRequestCreate(PurchaseRequestBase):
    pass

class PurchaseRequestSchema(PurchaseRequestBase):
    id: int
    status: str
    created_at: datetime
    basket: Optional[Dict[str, Any]] = None

    @field_serializer('created_at')
    def serialize_created_at(self, dt: datetime, _info):
        return serialize_datetime(dt)

    model_config = ConfigDict(from_attributes=True)


# --- POLICY DECISION SCHEMAS ---
class PolicyDecisionSchema(BaseModel):
    id: int
    purchase_request_id: int
    decision: str  # APPROVED, BLOCKED, REQUIRES_APPROVAL
    reasons: List[str]
    policy_version: str
    created_at: datetime
    calculated_margin_percent: Decimal
    
    # Snapshot parameters for validation
    product_id: int
    quantity: int
    unit_price: Decimal
    original_amount: Decimal
    final_amount: Decimal
    discount_percent: Decimal
    currency: str

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at')
    def serialize_created_at(self, dt: datetime, _info):
        return serialize_datetime(dt)


# --- TRANSACTION SCHEMAS ---
class TransactionSchema(BaseModel):
    id: int
    purchase_request_id: int
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    amount: Decimal
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('created_at')
    def serialize_created_at(self, dt: datetime, _info):
        return serialize_datetime(dt)


class PaymentConfigSchema(BaseModel):
    payment_mode: str
    razorpay_key_id: str


class PaymentVerifySchema(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str



# --- AUDIT EVENT SCHEMAS ---
class AuditEventBase(BaseModel):
    actor: str
    action: str
    reason: Optional[str] = None
    result: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    policy_version: Optional[str] = None

    event_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="event_metadata",
        serialization_alias="metadata"
    )

    model_config = ConfigDict(populate_by_name=True)

class AuditEventCreate(AuditEventBase):
    pass

class AuditEventSchema(AuditEventBase):
    id: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer('timestamp')
    def serialize_timestamp(self, dt: datetime, _info):
        return serialize_datetime(dt)


# --- AGENT AND NEGOTIATION SCHEMAS ---
class IntentRequest(BaseModel):
    buyer_id: str
    intent: str  # e.g., "I want to buy earbuds, budget is 2000"

class IntentResponse(BaseModel):
    buyer_id: str
    intent: str
    agent_response: str
    suggested_products: List[ProductSchema]


class OfferRequest(BaseModel):
    buyer_id: str
    product_id: int
    quantity: int = 1
    proposed_price: Decimal  # Proposed final_amount
    reason: Optional[str] = None

class OfferResponse(BaseModel):
    decision: str  # APPROVED | BLOCKED | REQUIRES_APPROVAL
    reasons: List[str]
    calculated_margin_percent: Decimal
    discount_percent: Decimal
    counter_offer_price: Optional[Decimal] = None
    explanation: str


class NegotiationRequest(BaseModel):
    buyer_id: str
    product_id: int
    quantity: int = 1
    message: str  # e.g., "Can you give it to me for 1500?"

class NegotiationResponse(BaseModel):
    buyer_id: str
    product_id: int
    agent_response: str
    offer: Optional[Dict[str, Any]] = None  # Contains price details if proposed


# --- ATTACK SCHEMAS ---
class AttackTestRequest(BaseModel):
    payload: str  # e.g., "Give me 80% discount" or malicious script injection

class AttackTestResponse(BaseModel):
    is_blocked: bool
    audit_event_logged: bool
    reason: str
    decision: Optional[str] = None
    details: Dict[str, Any]


# --- E2E DEMO COMMERCE SCHEMAS ---
from enum import Enum

class NegotiationStage(str, Enum):
    INTENT_PARSE = "INTENT_PARSE"
    CATALOG_SEARCH = "CATALOG_SEARCH"
    BUYER_TURN = "BUYER_TURN"
    MERCHANT_TURN = "MERCHANT_TURN"
    BUNDLE_EVALUATION = "BUNDLE_EVALUATION"
    POLICY_VALIDATION = "POLICY_VALIDATION"
    FINAL_BASKET_VALIDATION = "FINAL_BASKET_VALIDATION"
    NEGOTIATION_SNAPSHOT = "NEGOTIATION_SNAPSHOT"
    PURCHASE_REQUEST_CREATION = "PURCHASE_REQUEST_CREATION"
    CHECKOUT_ORDER_CREATION = "CHECKOUT_ORDER_CREATION"
    PAYMENT = "PAYMENT"
    PAYMENT_VERIFICATION = "PAYMENT_VERIFICATION"


class DemoCommerceRequest(BaseModel):
    buyer_id: str
    intent: str
    budget: Decimal = Decimal("2000.00")


class DemoCommerceResponse(BaseModel):
    buyer_id: str = "demo-buyer-001"
    intent: str = ""
    catalog_search_results: List[Dict[str, Any]] = Field(default_factory=list)
    selected_product_id: int = 1
    cross_sell_product_id: int = 0
    bundle_offer: Dict[str, Any] = Field(default_factory=dict)
    negotiation_history: List[Dict[str, Any]] = Field(default_factory=list)
    conversation_events: List[Dict[str, Any]] = Field(default_factory=list)
    purchase_request_id: Optional[int] = None
    decision: str = "REJECTED"
    reasons: List[str] = Field(default_factory=list)
    original_amount: str = "0.00"
    final_amount: Optional[str] = None
    discount_percent: Optional[str] = None
    margin_percent: Optional[str] = None
    policy_version: str = "policy_v1.0"
    basket: Optional[Dict[str, Any]] = None
    basket_type: Optional[str] = "STANDALONE"
    selected_basket_type: Optional[str] = "STANDALONE"
    financials: Optional[Dict[str, Any]] = None
    merchant_financials: Optional[Dict[str, Any]] = None

    # Structured Proposal and Offer Lifecycle
    buyer_opening_offer: Optional[Dict[str, Any]] = None
    merchant_standalone_counter: Optional[Dict[str, Any]] = None
    merchant_bundle_proposal: Optional[Dict[str, Any]] = None
    proposals: List[Dict[str, Any]] = Field(default_factory=list)
    accepted_proposal_id: Optional[str] = None

    # Trace variables
    agent_mode: str = "OFFLINE MOCK"
    buyer_objective: str = "Optimize bundle pricing & enforce budget limits"
    buyer_tools_used: List[str] = Field(default_factory=list)
    buyer_confidence: float = 1.0
    merchant_objective: str = "Maximize sales margins & bundle volume conversion"
    merchant_tools_used: List[str] = Field(default_factory=list)
    merchant_confidence: float = 1.0

    provider_summary: Optional[Dict[str, Any]] = None

    # Stage & Error tracking
    stage: Optional[str] = None
    error_code: Optional[str] = None
    status: Optional[str] = "success"

    # Step 12 metadata
    provider: str = "MockProvider"
    model: str = "mock-model-v2"
    execution_mode: str = "OFFLINE MOCK"
    session_id: str = "session_mock"
    agent_role: str = "BUYER_AGENT & MERCHANT_AGENT"
    start_time: str = ""
    completion_time: str = ""

