import datetime
from sqlalchemy import Column, Integer, String, Boolean, Numeric, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False)
    description = Column(String)
    price = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    cost = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    inventory = Column(Integer, default=0, nullable=False)
    attributes = Column(JSON, default=dict)
    related_product_ids = Column(JSON, default=list)
    active = Column(Boolean, default=True, nullable=False)

    purchase_requests = relationship("PurchaseRequest", back_populates="product")


class MerchantPolicy(Base):
    __tablename__ = "merchant_policies"

    id = Column(Integer, primary_key=True, index=True)
    max_discount_percent = Column(Numeric(5, 2, asdecimal=True), nullable=False)
    min_margin_percent = Column(Numeric(5, 2, asdecimal=True), nullable=False)
    max_auto_order_amount = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    require_approval_above = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    policy_version = Column(String, nullable=False, index=True)
    active = Column(Boolean, default=True, nullable=False)


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"

    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(String, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    
    # Financial snapshot fields
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2, asdecimal=True), nullable=False)  # Catalog price snapshot at request time
    original_amount = Column(Numeric(10, 2, asdecimal=True), nullable=False)  # unit_price * quantity
    final_amount = Column(Numeric(10, 2, asdecimal=True), nullable=False)  # Proposed final total selling price
    discount_percent = Column(Numeric(5, 2, asdecimal=True), nullable=False)
    currency = Column(String, default="INR", nullable=False)
    
    reason = Column(String)
    status = Column(String, default="PENDING", nullable=False)  # PENDING, APPROVED, BLOCKED, REQUIRES_APPROVAL, PAID
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    product = relationship("Product", back_populates="purchase_requests")
    policy_decisions = relationship("PolicyDecision", back_populates="purchase_request", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="purchase_request", cascade="all, delete-orphan")


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    purchase_request_id = Column(Integer, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False)
    decision = Column(String, nullable=False)  # APPROVED, BLOCKED, REQUIRES_APPROVAL (Canonical statuses)
    reasons = Column(JSON, default=list)
    policy_version = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    calculated_margin_percent = Column(Numeric(5, 2, asdecimal=True), nullable=False)
    
    # Snapshot parameters for verification during payment gateway creation
    product_id = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    original_amount = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    final_amount = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    discount_percent = Column(Numeric(5, 2, asdecimal=True), nullable=False)
    currency = Column(String, nullable=False)

    purchase_request = relationship("PurchaseRequest", back_populates="policy_decisions")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Strict 1-to-1 unique constraint to prevent multiple Razorpay orders for one PurchaseRequest
    purchase_request_id = Column(
        Integer,
        ForeignKey("purchase_requests.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True
    )
    razorpay_order_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    razorpay_signature = Column(String, nullable=True, unique=True, index=True)
    amount = Column(Numeric(10, 2, asdecimal=True), nullable=False)
    status = Column(String, default="PENDING", nullable=False)  # PENDING, SUCCESS, FAILED
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    purchase_request = relationship("PurchaseRequest", back_populates="transactions")


class ProcessedWebhookEvent(Base):
    """
    Database table to track processed webhook event IDs, preventing duplicate processing
    at the database layer.
    """
    __tablename__ = "processed_webhook_events"

    id = Column(String, primary_key=True, nullable=False)
    processed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)
    actor = Column(String, nullable=False, index=True)  # LLM, BUYER_AGENT, MERCHANT_AGENT, HUMAN, WEBHOOK, SYSTEM, LLM_ATTACK_TEST
    action = Column(String, nullable=False, index=True)
    reason = Column(String)
    result = Column(String, nullable=False)  # SUCCESS, FAIL, BLOCKED, REQUIRES_APPROVAL, ERROR
    entity_type = Column(String)
    entity_id = Column(Integer, nullable=True)
    policy_version = Column(String)
    event_metadata = Column("metadata", JSON, default=dict)
