import hmac
import hashlib
import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, Optional
import httpx
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import PurchaseRequest, PolicyDecision, Transaction
from backend.app.audit import AuditEngine

logger = logging.getLogger("setu.payments")

class PaymentGatewayAdapter(ABC):
    @abstractmethod
    def create_order(self, amount: Decimal, receipt_id: str) -> Dict[str, Any]:
        """
        Creates a payment gateway order.
        Amount is in INR (Decimal).
        """
        pass

    @abstractmethod
    def verify_payment_signature(
        self, order_id: str, payment_id: str, signature: str
    ) -> bool:
        """
        Verifies the payment callback signature.
        """
        pass

    @abstractmethod
    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> bool:
        """
        Verifies the webhook signature.
        """
        pass


class MockRazorpayAdapter(PaymentGatewayAdapter):
    """
    Mock adapter that simulates Razorpay API responses without making HTTP calls.
    Allows fully deterministic offline testing.
    """
    def __init__(self, key_secret: str, webhook_secret: str):
        # Kept private to adapter instance
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret

    def create_order(self, amount: Decimal, receipt_id: str) -> Dict[str, Any]:
        amount_paise = int(amount * Decimal("100"))
        order_id = f"order_mock_{receipt_id}_{amount_paise}"
        logger.info(f"[MOCK PAY] Simulating Order creation: {order_id} for amount {amount}")
        return {
            "id": order_id,
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": "INR",
            "receipt": receipt_id,
            "status": "created",
            "created_at": 1600000000
        }

    def verify_payment_signature(
        self, order_id: str, payment_id: str, signature: str
    ) -> bool:
        msg = f"{order_id}|{payment_id}"
        expected = hmac.new(
            self._key_secret.encode(),
            msg.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> bool:
        expected = hmac.new(
            self._webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


class RazorpayAdapter(PaymentGatewayAdapter):
    """
    Production-ready adapter communicating with Razorpay API endpoints.
    """
    def __init__(self, key_id: str, key_secret: str, webhook_secret: str):
        # Kept private to adapter instance, never exposed in prompts or attributes
        self._key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self.base_url = "https://api.razorpay.com/v1"

    def create_order(self, amount: Decimal, receipt_id: str) -> Dict[str, Any]:
        amount_paise = int(amount * Decimal("100"))
        
        # Test mode fallback helper
        if self._key_id == "rzp_test_mockkeyid123" or "mock" in self._key_id:
            mock = MockRazorpayAdapter(self._key_secret, self._webhook_secret)
            return mock.create_order(amount, receipt_id)
            
        data = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_id
        }
        
        logger.info(f"[RAZORPAY PAY] Requesting order from Razorpay: receipt={receipt_id}")
        
        try:
            import razorpay
            client = razorpay.Client(auth=(self._key_id, self._key_secret))
            # Use SDK to create order
            order = client.order.create(data=data)
            return order
        except Exception as e:
            logger.error(f"Razorpay API call failed during SDK call: {e}")
            raise RuntimeError(f"Razorpay communication error: {e}")

    def verify_payment_signature(
        self, order_id: str, payment_id: str, signature: str
    ) -> bool:
        msg = f"{order_id}|{payment_id}"
        expected = hmac.new(
            self._key_secret.encode(),
            msg.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> bool:
        expected = hmac.new(
            self._webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def get_payment_adapter() -> PaymentGatewayAdapter:
    """
    Dependency injection helper to return the payment adapter configured with server-side secrets.
    """
    if settings.active_payment_mode == "mock":
        return MockRazorpayAdapter(settings.RAZORPAY_KEY_SECRET, settings.RAZORPAY_WEBHOOK_SECRET)
    else:
        return RazorpayAdapter(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
            settings.RAZORPAY_WEBHOOK_SECRET
        )



import threading

# Process-level lock to serialize requests within the same process.
# SQLite ignores row locks (with_for_update). Thus, in local SQLite environments
# and single-worker web servers, this thread lock enforces strict serialization.
# In multi-worker production environments backed by PostgreSQL/MySQL, the database-level
# transaction with row locking (.with_for_update()) handles inter-process serialization.
_payment_lock = threading.Lock()


def process_payment_creation(db: Session, purchase_request_id: int) -> Transaction:
    """
    Core Payment Creator. Verifies that the PurchaseRequest is APPROVED and performs
    comprehensive field matches against the active PolicyDecision before generating Razorpay orders.
    Serializes payment creation to prevent concurrency race conditions.
    """
    # 1. Acquire thread-level lock to serialize concurrent execution within the application process
    with _payment_lock:
        # 2. Fetch Purchase Request and acquire row-level lock in the database (production PostgreSQL)
        pr = db.query(PurchaseRequest).filter(
            PurchaseRequest.id == purchase_request_id
        ).with_for_update().first()

        if not pr:
            AuditEngine.log_event(
                db=db,
                actor="SYSTEM",
                action="CREATE_PAYMENT",
                result="FAIL",
                reason=f"Purchase request ID {purchase_request_id} not found."
            )
            raise ValueError("Purchase request not found")

        # 3. Check if the status is canonical APPROVED
        if pr.status != "APPROVED":
            AuditEngine.log_event(
                db=db,
                actor="SYSTEM",
                action="CREATE_PAYMENT",
                result="BLOCKED",
                reason=f"Security alert: Blocked payment attempt. Purchase Request status is '{pr.status}', expected 'APPROVED'.",
                entity_type="PurchaseRequest",
                entity_id=pr.id,
                metadata={"amount": str(pr.final_amount)}
            )
            raise PermissionError("Purchase request has not been APPROVED by the backend Policy Engine.")

        # 4. Re-check for existing transaction INSIDE the locked block to prevent duplicate Razorpay orders
        existing_tx = db.query(Transaction).filter(Transaction.purchase_request_id == purchase_request_id).first()
        if existing_tx:
            raise ValueError("A payment transaction already exists for this purchase request.")

        # 5. Fetch the latest PolicyDecision associated with this request
        decision = db.query(PolicyDecision).filter(
            PolicyDecision.purchase_request_id == purchase_request_id
        ).order_by(PolicyDecision.created_at.desc()).first()

        if not decision:
            AuditEngine.log_event(
                db=db,
                actor="SYSTEM",
                action="CREATE_PAYMENT",
                result="BLOCKED",
                reason="Security alert: Blocked payment attempt. No matching PolicyDecision found in the database.",
                entity_type="PurchaseRequest",
                entity_id=pr.id
            )
            raise PermissionError("Policy decision not found for this purchase request.")

        # 6. Verify the PolicyDecision status is APPROVED
        if decision.decision != "APPROVED":
            AuditEngine.log_event(
                db=db,
                actor="SYSTEM",
                action="CREATE_PAYMENT",
                result="BLOCKED",
                reason=f"Security alert: Blocked payment attempt. PolicyDecision status is '{decision.decision}', expected 'APPROVED'.",
                entity_type="PurchaseRequest",
                entity_id=pr.id
            )
            raise PermissionError("Policy decision is not APPROVED.")

        # 7. Deep Cross-Verification (Rule 2 & 6)
        # Check that every single snapshot field matches exactly between PurchaseRequest and PolicyDecision
        mismatches = []
        if pr.product_id != decision.product_id:
            mismatches.append(f"product_id: {pr.product_id} vs {decision.product_id}")
        if pr.quantity != decision.quantity:
            mismatches.append(f"quantity: {pr.quantity} vs {decision.quantity}")
        if pr.unit_price != decision.unit_price:
            mismatches.append(f"unit_price: {pr.unit_price} vs {decision.unit_price}")
        if pr.original_amount != decision.original_amount:
            mismatches.append(f"original_amount: {pr.original_amount} vs {decision.original_amount}")
        if pr.final_amount != decision.final_amount:
            mismatches.append(f"final_amount: {pr.final_amount} vs {decision.final_amount}")
        if pr.discount_percent != decision.discount_percent:
            mismatches.append(f"discount_percent: {pr.discount_percent} vs {decision.discount_percent}")
        if pr.currency != decision.currency:
            mismatches.append(f"currency: {pr.currency} vs {decision.currency}")

        if mismatches:
            AuditEngine.log_event(
                db=db,
                actor="SYSTEM",
                action="CREATE_PAYMENT",
                result="BLOCKED",
                reason=f"Security alert: PolicyDecision/PurchaseRequest mismatch. Mismatches: {', '.join(mismatches)}",
                entity_type="PurchaseRequest",
                entity_id=pr.id,
                metadata={"mismatches": mismatches}
            )
            raise PermissionError("Security alert: PurchaseRequest parameters mismatch with the approved PolicyDecision snapshot.")

        # 8. Invoke isolated adapter to request order (secrets are kept safe inside the adapter)
        adapter = get_payment_adapter()
        try:
            order_data = adapter.create_order(pr.final_amount, str(pr.id))
        except Exception as e:
            logger.error(f"Razorpay API call failed during order generation: {e}")
            raise RuntimeError(f"Payment Gateway order creation failed: {e}")

        # 9. Create Transaction
        tx = Transaction(
            purchase_request_id=pr.id,
            razorpay_order_id=order_data["id"],
            amount=pr.final_amount,
            status="PENDING"
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)

        # 10. Log successful generation to audit trail
        AuditEngine.log_event(
            db=db,
            actor="SYSTEM",
            action="CREATE_PAYMENT",
            result="SUCCESS",
            reason=f"Successfully generated payment transaction. Razorpay Order ID: {order_data['id']}",
            entity_type="Transaction",
            entity_id=tx.id,
            metadata={"razorpay_order_id": order_data["id"]}
        )

        return tx

