import json
import logging
from decimal import Decimal
from sqlalchemy.orm import Session

from backend.app.payments import get_payment_adapter, deduct_inventory_for_paid_purchase
from backend.app.models import Transaction, PurchaseRequest, ProcessedWebhookEvent
from backend.app.audit import AuditEngine

logger = logging.getLogger("setu.webhooks")

class WebhookProcessor:
    @staticmethod
    def process_razorpay_webhook(
        db: Session,
        payload_bytes: bytes,
        signature: str
    ) -> dict:
        """
        Processes an incoming Razorpay webhook with database-level idempotency
        and signature validation over raw bytes.
        
        Args:
            db: SQLAlchemy Session
            payload_bytes: The raw request body bytes
            signature: The X-Razorpay-Signature header
            
        Returns:
            Dict containing processing status.
        """
        adapter = get_payment_adapter()
        
        # 1. Verify signature on RAW body bytes
        if not adapter.verify_webhook_signature(payload_bytes, signature):
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="FAIL",
                reason="Invalid webhook signature",
                metadata={"signature_received": signature}
            )
            return {"status": "error", "message": "Invalid signature"}

        # 2. Parse payload
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as e:
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="FAIL",
                reason=f"Payload decoding failed: {str(e)}"
            )
            return {"status": "error", "message": "Invalid JSON payload"}

        event_type = payload.get("event")
        event_id = payload.get("id")
        
        if not event_id:
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="FAIL",
                reason="Missing event ID in webhook payload"
            )
            return {"status": "error", "message": "Missing event id"}

        # 3. Webhook Event ID / Idempotency protection at Database level
        existing_event = db.query(ProcessedWebhookEvent).filter(
            ProcessedWebhookEvent.id == event_id
        ).first()
        
        if existing_event:
            # Event already processed. Return success to Razorpay but do not modify DB state.
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="SUCCESS",
                reason=f"Idempotency Guard: Duplicate webhook event ID '{event_id}' skipped.",
                metadata={"event_id": event_id, "duplicate": True}
            )
            return {"status": "success", "message": "Duplicate event ID ignored."}

        # We handle payment captured or order paid events
        if event_type not in ["order.paid", "payment.captured"]:
            # Record that we successfully processed this event so we don't handle it again
            processed_evt = ProcessedWebhookEvent(id=event_id)
            db.add(processed_evt)
            db.commit()
            
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="SUCCESS",
                reason=f"Ignored unsupported event type: {event_type}",
                metadata={"event_id": event_id, "event_type": event_type}
            )
            return {"status": "ignored", "message": f"Unsupported event {event_type}"}

        # Extract order details
        order_payload = payload.get("payload", {}).get("order", {}).get("entity", {})
        payment_payload = payload.get("payload", {}).get("payment", {}).get("entity", {})
        
        order_id = order_payload.get("id") or payment_payload.get("order_id")
        payment_id = payment_payload.get("id")
        amount_paise = order_payload.get("amount") or payment_payload.get("amount")
        
        if not order_id:
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="FAIL",
                reason="Missing order_id in webhook payload",
                metadata={"event_id": event_id}
            )
            return {"status": "error", "message": "Missing order_id"}

        amount_decimal = Decimal(amount_paise) / Decimal("100") if amount_paise else Decimal("0")

        # 4. Find target transaction
        transaction = db.query(Transaction).filter(Transaction.razorpay_order_id == order_id).first()
        
        if not transaction:
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="FAIL",
                reason=f"No transaction found for Razorpay order ID: {order_id}",
                metadata={"event_id": event_id, "razorpay_order_id": order_id, "payment_id": payment_id}
            )
            return {"status": "error", "message": f"Transaction not found for {order_id}"}

        # 5. Process event and update transaction (and purchase request)
        # Check if transaction is already SUCCESS (double protection check)
        if transaction.status == "SUCCESS":
            # Record this event ID to prevent duplicate handling
            processed_evt = ProcessedWebhookEvent(id=event_id)
            db.add(processed_evt)
            db.commit()
            
            AuditEngine.log_event(
                db=db,
                actor="WEBHOOK",
                action="PROCESS_WEBHOOK",
                result="SUCCESS",
                reason=f"Idempotency Guard: Transaction {transaction.id} already marked successful.",
                entity_type="Transaction",
                entity_id=transaction.id,
                metadata={"event_id": event_id}
            )
            return {"status": "success", "message": "Transaction already processed."}

        logger.info(f"Webhook matched order {order_id}. Updating Transaction ID {transaction.id} to SUCCESS. Razorpay Payment ID: {payment_id}")
        transaction.status = "SUCCESS"
        transaction.razorpay_payment_id = payment_id
        transaction.razorpay_signature = signature
        
        # Mark associated purchase request as PAID and deduct inventory
        purchase_request = db.query(PurchaseRequest).filter(
            PurchaseRequest.id == transaction.purchase_request_id
        ).first()
        if purchase_request:
            try:
                deduct_inventory_for_paid_purchase(db, purchase_request)
            except Exception as e:
                logger.error(f"Inventory deduction failed during webhook processing: {e}")
                AuditEngine.log_event(
                    db=db,
                    actor="WEBHOOK",
                    action="PROCESS_WEBHOOK",
                    result="FAIL",
                    reason=f"Payment received but inventory deduction failed: {str(e)}",
                    entity_type="Transaction",
                    entity_id=transaction.id,
                    metadata={"event_id": event_id, "error": str(e)}
                )
                return {"status": "error", "message": str(e)}

        # Register event ID as processed
        processed_evt = ProcessedWebhookEvent(id=event_id)
        db.add(processed_evt)
        db.commit()

        # Log webhook success
        AuditEngine.log_event(
            db=db,
            actor="WEBHOOK",
            action="PROCESS_WEBHOOK",
            result="SUCCESS",
            reason=f"Webhook processed successfully. Transaction updated to SUCCESS and PurchaseRequest marked as PAID.",
            entity_type="Transaction",
            entity_id=transaction.id,
            metadata={
                "event_id": event_id,
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "amount": str(amount_decimal)
            }
        )

        return {"status": "success", "message": "Webhook processed successfully"}
