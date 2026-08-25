import pytest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from decimal import Decimal

from backend.app import payments as payments_module
from backend.app.models import PurchaseRequest, Transaction

def test_concurrent_payment_creation_is_serialized(client, db, monkeypatch):
    """
    Concurrency integration test: launches two simultaneous payment creation requests
    for the same PurchaseRequest.
    Mock Razorpay and assert:
    - exactly ONE Razorpay create_order call is made.
    - exactly ONE Transaction record is created.
    - one request succeeds (HTTP 200) and the other cleanly reports that the transaction already exists (HTTP 400).
    - no duplicate Razorpay order is created.
    """
    # 1. Create an approved purchase request and policy decision
    req_data = {
        "buyer_id": "buyer_agent_alpha",
        "product_id": 1,
        "quantity": 1,
        "unit_price": "1599.00",
        "original_amount": "1599.00",
        "final_amount": "1599.00",
        "discount_percent": "0.00",
        "currency": "INR",
        "reason": "Concurrency test direct purchase"
    }
    
    # Submitting purchase request
    purchase_res = client.post("/api/purchase/request", json=req_data).json()
    pr_id = purchase_res["purchase_request_id"]
    
    # Verify status is APPROVED
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == pr_id).first()
    assert pr.status == "APPROVED"
    
    # 2. Mock the payment gateway adapter to track create_order invocations
    mock_adapter = MagicMock()
    mock_adapter.create_order.return_value = {
        "id": f"order_mock_concurrency_{pr_id}",
        "amount": 159900,
        "currency": "INR",
        "status": "created"
    }
    
    # Replace get_payment_adapter to return our mock_adapter
    monkeypatch.setattr(payments_module, "get_payment_adapter", lambda: mock_adapter)
    
    # 3. Launch concurrent requests using ThreadPoolExecutor
    def send_payment_request():
        # TestClient is thread-safe for making concurrent calls against app
        return client.post(f"/api/payment/create?purchase_request_id={pr_id}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(send_payment_request) for _ in range(2)]
        results = [f.result() for f in futures]
        
    # 4. Assert response statuses
    # One request must succeed (200), and the other must cleanly fail (400) because the transaction already exists.
    status_codes = [r.status_code for r in results]
    assert 200 in status_codes
    assert 400 in status_codes
    
    # Locate the error response
    fail_res = next(r for r in results if r.status_code == 400).json()
    assert "already exists" in fail_res["detail"]
    
    # 5. Verify database and mock constraints
    # Check that create_order was called EXACTLY once
    assert mock_adapter.create_order.call_count == 1
    
    # Check that exactly one transaction record exists in the DB
    tx_count = db.query(Transaction).filter(Transaction.purchase_request_id == pr_id).count()
    assert tx_count == 1
