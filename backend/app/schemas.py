from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any, Optional
from decimal import Decimal
from datetime import datetime

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

class PurchaseRequestCreate(PurchaseRequestBase):
    pass

class PurchaseRequestSchema(PurchaseRequestBase):
    id: int
    status: str
    created_at: datetime

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


# --- TRANSACTION SCHEMAS ---
class TransactionSchema(BaseModel):
    id: int
    purchase_request_id: int
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    amount: Decimal
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- AUDIT EVENT SCHEMAS ---
class AuditEventBase(BaseModel):
    actor: str
    action: str
    reason: Optional[str] = None
    result: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    policy_version: Optional[str] = None
    event_metadata: Dict[str, Any] = Field(default_factory=dict, validation_alias="metadata", serialization_alias="metadata")

    model_config = ConfigDict(populate_by_name=True)

class AuditEventCreate(AuditEventBase):
    pass

class AuditEventSchema(AuditEventBase):
    id: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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
