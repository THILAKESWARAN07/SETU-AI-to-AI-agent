import hmac
import hashlib
import json
from decimal import Decimal
from fastapi.testclient import TestClient
from backend.app.config import settings
from backend.app.models import Transaction, PurchaseRequest, AuditEvent, ProcessedWebhookEvent

def generate_webhook_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()


def test_webhook_happy_path(client: TestClient, db):
    # 1. Create approved request with snapshots
    req_data = {
        "buyer_id": "buyer_agent_alpha",
        "product_id": 1,
        "quantity": 1,
        "unit_price": "1599.00",
        "original_amount": "1599.00",
        "final_amount": "1599.00",
        "discount_percent": "0.00",
        "currency": "INR",
        "reason": "Direct purchase"
    }
    purchase_res = client.post("/api/purchase/request", json=req_data).json()
    pr_id = purchase_res["purchase_request_id"]

    # 2. Generate Razorpay order
    payment_res = client.post(f"/api/payment/create?purchase_request_id={pr_id}").json()
    razorpay_order_id = payment_res["razorpay_order_id"]

    # 3. Simulate Webhook order.paid event
    webhook_payload = {
        "entity": "event",
        "event": "order.paid",
        "id": "evt_success_1001",
        "payload": {
            "order": {
                "entity": {
                    "id": razorpay_order_id,
                    "amount": 159900,
                    "status": "paid"
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_live_payment_abc",
                    "order_id": razorpay_order_id,
                    "amount": 159900,
                    "status": "captured"
                }
            }
        }
    }
    
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    sig = generate_webhook_signature(payload_bytes, settings.RAZORPAY_WEBHOOK_SECRET)
    headers = {"X-Razorpay-Signature": sig}

    # 4. Trigger Webhook
    webhook_res = client.post("/api/webhooks/razorpay", data=payload_bytes, headers=headers)
    assert webhook_res.status_code == 200
    assert webhook_res.json()["status"] == "success"

    # Verify state updates
    tx = db.query(Transaction).filter(Transaction.razorpay_order_id == razorpay_order_id).first()
    assert tx.status == "SUCCESS"
    assert tx.razorpay_payment_id == "pay_live_payment_abc"

    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == pr_id).first()
    assert pr.status == "PAID"

    # Verify event added to ProcessedWebhookEvent table
    processed = db.query(ProcessedWebhookEvent).filter(ProcessedWebhookEvent.id == "evt_success_1001").first()
    assert processed is not None


def test_webhook_invalid_signature(client: TestClient, db):
    webhook_payload = {"entity": "event", "event": "order.paid", "id": "evt_sig_fail"}
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    
    headers = {"X-Razorpay-Signature": "invalid_signature_string"}
    response = client.post("/api/webhooks/razorpay", data=payload_bytes, headers=headers)
    
    assert response.status_code == 400
    assert "Invalid signature" in response.json()["detail"]

    # Verify database hasn't logged event as processed
    processed = db.query(ProcessedWebhookEvent).filter(ProcessedWebhookEvent.id == "evt_sig_fail").first()
    assert processed is None


def test_webhook_duplicate_protection(client: TestClient, db):
    # Setup approved purchase request and transaction
    tx = Transaction(
        purchase_request_id=1,
        razorpay_order_id="order_duplicate_test_99",
        amount=Decimal("1599.00"),
        status="PENDING"
    )
    db.add(tx)
    db.commit()

    webhook_payload = {
        "entity": "event",
        "event": "order.paid",
        "id": "evt_duplicate_id_2002",
        "payload": {
            "order": {
                "entity": {
                    "id": "order_duplicate_test_99",
                    "amount": 159900
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_captured_once",
                    "order_id": "order_duplicate_test_99"
                }
            }
        }
    }
    
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    sig = generate_webhook_signature(payload_bytes, settings.RAZORPAY_WEBHOOK_SECRET)
    headers = {"X-Razorpay-Signature": sig}

    # First webhook post - SUCCESS processing
    res1 = client.post("/api/webhooks/razorpay", data=payload_bytes, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "success"

    # Second webhook post (same event ID) - Ignored due to duplicate check
    res2 = client.post("/api/webhooks/razorpay", data=payload_bytes, headers=headers)
    assert res2.status_code == 200
    assert "Duplicate event ID ignored" in res2.json()["message"]

    # Check that transaction payment ID remains the first captured ID
    db.refresh(tx)
    assert tx.status == "SUCCESS"
    assert tx.razorpay_payment_id == "pay_captured_once"

    # Verify duplicate event logged in Audit
    audit_evt = db.query(AuditEvent).filter(
        AuditEvent.actor == "WEBHOOK",
        AuditEvent.result == "SUCCESS",
        AuditEvent.reason.like("%Idempotency Guard%")
    ).first()
    assert audit_evt is not None


def test_webhook_unknown_transaction(client: TestClient, db):
    webhook_payload = {
        "entity": "event",
        "event": "order.paid",
        "id": "evt_unknown_99",
        "payload": {
            "order": {
                "entity": {
                    "id": "order_does_not_exist_in_database",
                    "amount": 159900
                }
            }
        }
    }
    
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    sig = generate_webhook_signature(payload_bytes, settings.RAZORPAY_WEBHOOK_SECRET)
    headers = {"X-Razorpay-Signature": sig}

    response = client.post("/api/webhooks/razorpay", data=payload_bytes, headers=headers)
    assert response.status_code == 400
    assert "Transaction not found" in response.json()["detail"]
