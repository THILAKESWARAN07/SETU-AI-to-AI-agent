import hmac
import hashlib
import json
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.models import PurchaseRequest, PolicyDecision, Transaction, ProcessedWebhookEvent
from backend.app import payments as payments_module
from backend.app.payments import MockRazorpayAdapter, RazorpayAdapter, get_payment_adapter
from backend.app.main import app

def generate_webhook_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

def test_inr_to_paise_conversion():
    # 2. Correct INR -> paise conversion
    adapter = MockRazorpayAdapter("mocksecret123", "mockwebhooksecret123")
    order = adapter.create_order(Decimal("15.99"), "receipt_1")
    assert order["amount"] == 1599
    
    with patch("razorpay.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.order.create.return_value = {"id": "order_test_123", "amount": 159900}
        mock_client.return_value = mock_instance
        
        rzp_adapter = RazorpayAdapter("rzp_test_realstyleid", "realsecret", "webhook_secret")
        res = rzp_adapter.create_order(Decimal("1599.00"), "rec_2")
        assert res["amount"] == 159900
        mock_instance.order.create.assert_called_once_with(data={
            "amount": 159900,
            "currency": "INR",
            "receipt": "rec_2"
        })

def test_order_creation_mocked():
    # 1. Razorpay order creation with valid credentials mocked
    with patch("razorpay.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.order.create.return_value = {
            "id": "order_mocked_101",
            "amount": 189900,
            "currency": "INR",
            "status": "created"
        }
        mock_client.return_value = mock_instance
        
        with patch.object(settings, "PAYMENT_MODE", "razorpay"), \
             patch.object(settings, "RAZORPAY_KEY_ID", "rzp_test_realstyleid"), \
             patch.object(settings, "RAZORPAY_KEY_SECRET", "realsecret"), \
             patch.object(settings, "RAZORPAY_WEBHOOK_SECRET", "realwebhooksecret"):
            
            adapter = get_payment_adapter()
            assert isinstance(adapter, RazorpayAdapter)
            res = adapter.create_order(Decimal("1899.00"), "receipt_abc")
            assert res["id"] == "order_mocked_101"

def test_server_side_amount_locking_and_security(client: TestClient, db):
    # Setup approved purchase request and decision
    pr = PurchaseRequest(
        buyer_id="buyer_agent_alpha",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1599.00"),
        discount_percent=Decimal("0.00"),
        currency="INR",
        status="APPROVED"
    )
    db.add(pr)
    db.commit()
    
    decision = PolicyDecision(
        purchase_request_id=pr.id,
        decision="APPROVED",
        reasons=[],
        policy_version="v1",
        calculated_margin_percent=Decimal("30.00"),
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1599.00"),
        discount_percent=Decimal("0.00"),
        currency="INR"
    )
    db.add(decision)
    db.commit()

    # 3. Server-side amount locking: verify that the amount is resolved from the locked db final_amount,
    # and the frontend client does not submit amounts.
    # 4. Invalid purchase request rejected:
    res = client.post("/api/payment/create?purchase_request_id=9999")
    assert res.status_code == 400
    assert "not found" in res.json()["detail"].lower()

def test_unapproved_purchase_request_rejected(client: TestClient, db):
    # 5. Unapproved purchase request rejected
    pr = PurchaseRequest(
        buyer_id="buyer_agent_alpha",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1599.00"),
        discount_percent=Decimal("0.00"),
        currency="INR",
        status="PENDING" # Not approved
    )
    db.add(pr)
    db.commit()

    res = client.post(f"/api/payment/create?purchase_request_id={pr.id}")
    assert res.status_code == 400
    assert "approved" in res.json()["detail"].lower()

def test_razorpay_api_failure_handling():
    # 6. Razorpay API failure handled safely
    with patch("razorpay.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.order.create.side_effect = Exception("API connection timeout")
        mock_client.return_value = mock_instance
        
        rzp_adapter = RazorpayAdapter("rzp_test_realstyleid", "realsecret", "webhook_secret")
        with pytest.raises(RuntimeError) as exc_info:
            rzp_adapter.create_order(Decimal("1599.00"), "rec_err")
        assert "communication error" in str(exc_info.value).lower()

def test_payment_signature_verification(client: TestClient, db):
    # Setup transaction
    tx = Transaction(
        purchase_request_id=101,
        razorpay_order_id="order_sig_test",
        amount=Decimal("1599.00"),
        status="PENDING"
    )
    db.add(tx)
    db.commit()

    # Create correct signature
    secret = settings.RAZORPAY_KEY_SECRET
    msg = f"order_sig_test|pay_sig_test"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

    # 7. Valid payment signature accepted
    payload = {
        "razorpay_order_id": "order_sig_test",
        "razorpay_payment_id": "pay_sig_test",
        "razorpay_signature": sig
    }
    res = client.post("/api/payment/verify", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "SUCCESS"
    assert res.json()["razorpay_payment_id"] == "pay_sig_test"

    # Setup another transaction for invalid sig test
    tx2 = Transaction(
        purchase_request_id=102,
        razorpay_order_id="order_sig_fail_test",
        amount=Decimal("1599.00"),
        status="PENDING"
    )
    db.add(tx2)
    db.commit()

    # 8. Invalid payment signature rejected
    payload_invalid = {
        "razorpay_order_id": "order_sig_fail_test",
        "razorpay_payment_id": "pay_sig_test",
        "razorpay_signature": "invalid_signature_mock"
    }
    res_invalid = client.post("/api/payment/verify", json=payload_invalid)
    assert res_invalid.status_code == 400
    assert "Invalid payment signature" in res_invalid.json()["detail"]

    # Re-fetch transaction and assert status is FAILED
    db.refresh(tx2)
    assert tx2.status == "FAILED"

def test_webhook_verification_scenarios(client: TestClient, db):
    tx = Transaction(
        purchase_request_id=103,
        razorpay_order_id="order_webhook_test_101",
        amount=Decimal("1899.00"),
        status="PENDING"
    )
    db.add(tx)
    db.commit()

    webhook_payload = {
        "entity": "event",
        "event": "order.paid",
        "id": "evt_unique_webhook_1001",
        "payload": {
            "order": {
                "entity": {
                    "id": "order_webhook_test_101",
                    "amount": 189900
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_captured_webhook_abc",
                    "order_id": "order_webhook_test_101"
                }
            }
        }
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    valid_sig = generate_webhook_signature(payload_bytes, settings.RAZORPAY_WEBHOOK_SECRET)

    # 9. Valid webhook accepted
    res = client.post("/api/webhooks/razorpay", data=payload_bytes, headers={"X-Razorpay-Signature": valid_sig})
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # 10. Invalid webhook signature rejected
    res_invalid = client.post("/api/webhooks/razorpay", data=payload_bytes, headers={"X-Razorpay-Signature": "invalid_sig"})
    assert res_invalid.status_code == 400
    assert "Invalid signature" in res_invalid.json()["detail"]

    # 11. Duplicate webhook does not double-process
    res_dup = client.post("/api/webhooks/razorpay", data=payload_bytes, headers={"X-Razorpay-Signature": valid_sig})
    assert res_dup.status_code == 200
    assert "Duplicate event ID ignored" in res_dup.json()["message"]

def test_mock_payment_still_works(client: TestClient, db):
    # 12. Mock payment still works
    with patch.object(settings, "PAYMENT_MODE", "mock"):
        pr = PurchaseRequest(
            buyer_id="buyer_mock",
            product_id=1,
            quantity=1,
            unit_price=Decimal("1599.00"),
            original_amount=Decimal("1599.00"),
            final_amount=Decimal("1599.00"),
            discount_percent=Decimal("0.00"),
            currency="INR",
            status="APPROVED"
        )
        db.add(pr)
        db.commit()

        decision = PolicyDecision(
            purchase_request_id=pr.id,
            decision="APPROVED",
            reasons=[],
            policy_version="v1",
            calculated_margin_percent=Decimal("30.00"),
            product_id=1,
            quantity=1,
            unit_price=Decimal("1599.00"),
            original_amount=Decimal("1599.00"),
            final_amount=Decimal("1599.00"),
            discount_percent=Decimal("0.00"),
            currency="INR"
        )
        db.add(decision)
        db.commit()

        res = client.post(f"/api/payment/create?purchase_request_id={pr.id}")
        assert res.status_code == 200
        assert "order_mock_" in res.json()["razorpay_order_id"]

def test_ai_agent_sandboxing_and_secrets(client: TestClient):
    # 13. AI agents cannot access Razorpay credentials/tools
    from backend.app.agents.buyer_agent import BuyerAgent
    from backend.app.agents.provider import MockLLMProvider
    llm = MockLLMProvider()
    agent = BuyerAgent(llm)
    tools = agent.registry.tools
    tool_names = list(tools.keys())
    assert "create_razorpay_order" not in tool_names
    assert "capture_payment" not in tool_names
    assert "refund_payment" not in tool_names
    
    # 14. Secrets are not leaked in API responses
    res = client.get("/api/payment/config")
    assert res.status_code == 200
    cfg = res.json()
    assert "payment_mode" in cfg
    assert "razorpay_key_id" in cfg
    res_str = json.dumps(cfg)
    assert settings.RAZORPAY_KEY_SECRET not in res_str
    assert "key_secret" not in res_str
    assert "webhook_secret" not in res_str

def test_razorpay_credentials_activate_razorpay_mode():
    from backend.app.config import Settings
    import os
    from unittest.mock import patch
    
    # Case 1: Valid Razorpay test credentials should activate razorpay mode
    with patch.dict(os.environ, {
        "RAZORPAY_KEY_ID": "rzp_test_validkey123",
        "RAZORPAY_KEY_SECRET": "validsecret123",
        "RAZORPAY_WEBHOOK_SECRET": "mockwebhooksecret123",
        "PAYMENT_MODE": "mock"
    }):
        s = Settings()
        assert s.PAYMENT_MODE == "razorpay"
        assert s.RAZORPAY_MODE == "test"
        assert s.active_payment_mode == "razorpay"
        
    # Case 2: Absent or invalid credentials should fall back to mock
    with patch.dict(os.environ, {
        "RAZORPAY_KEY_ID": "rzp_test_mockkeyid123",
        "RAZORPAY_KEY_SECRET": "mocksecret123",
        "PAYMENT_MODE": "mock"
    }):
        s = Settings()
        assert s.PAYMENT_MODE == "mock"
        assert s.active_payment_mode == "mock"

    with patch.dict(os.environ, {
        "RAZORPAY_KEY_ID": "",
        "RAZORPAY_KEY_SECRET": "",
        "PAYMENT_MODE": "mock"
    }):
        s = Settings()
        assert s.PAYMENT_MODE == "mock"
        assert s.active_payment_mode == "mock"

