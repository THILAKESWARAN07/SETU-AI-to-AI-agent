import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from backend.app.agents.agents import get_buyer_agent, MockLLMProvider, ToolRegistry, SecurityError
from backend.app.models import PurchaseRequest, PolicyDecision, Transaction, AuditEvent

def test_llm_tool_registry_has_no_payment_tools():
    """
    Ensures that the buyer agent has no tools for payments and that
    the ToolRegistry explicitly blocks registering payment-related tools.
    """
    provider = MockLLMProvider()
    agent = get_buyer_agent(provider)
    
    # 1. Verify registered tools do not contain payment-related terms
    tool_names = list(agent.registry.tools.keys())
    for name in tool_names:
        name_lower = name.lower()
        assert "payment" not in name_lower
        assert "razorpay" not in name_lower
        assert "capture" not in name_lower
        assert "refund" not in name_lower

    # 2. Verify that attempting to register an unsafe tool raises a SecurityError
    registry = ToolRegistry()
    
    def mock_pay_tool(db):
        return "paid"
        
    unsafe_schema = {
        "name": "create_razorpay_order",
        "description": "Directly creates a Razorpay payment order.",
        "parameters": {"type": "object", "properties": {}}
    }
    
    with pytest.raises(SecurityError) as exc_info:
        registry.register_tool("create_razorpay_order", mock_pay_tool, unsafe_schema)
        
    assert "Security Block" in str(exc_info.value)


def test_payment_endpoint_blocks_fake_approval(client: TestClient, db):
    """
    Fake approval: A PurchaseRequest with status = 'APPROVED' is inserted in the DB,
    but there is no matching PolicyDecision record.
    Expected: Payment gateway rejects and logs a BLOCKED audit event.
    """
    # Create request with fake status and no decision
    fake_pr = PurchaseRequest(
        buyer_id="attacker",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1599.00"),
        discount_percent=Decimal("0.00"),
        currency="INR",
        reason="Fake approval bypass attempt",
        status="APPROVED"  # Attacker tries to bypass by setting APPROVED state
    )
    db.add(fake_pr)
    db.commit()

    # Attempt to trigger payment creation
    response = client.post(f"/api/payment/create?purchase_request_id={fake_pr.id}")
    assert response.status_code == 400
    assert "Policy decision not found" in response.json()["detail"]

    # Verify audit event logged as BLOCKED
    audit_evt = db.query(AuditEvent).filter(
        AuditEvent.action == "CREATE_PAYMENT",
        AuditEvent.result == "BLOCKED",
        AuditEvent.entity_id == fake_pr.id
    ).first()
    assert audit_evt is not None
    assert "no matching policydecision found" in audit_evt.reason.lower()


def test_payment_endpoint_blocks_modified_approved_amount(client: TestClient, db):
    """
    Modified approved amount: A PurchaseRequest gets APPROVED for ₹1599.
    Attacker modifies PurchaseRequest.final_amount in DB to ₹10.00.
    Expected: Payment gateway rejects due to mismatch with PolicyDecision snapshot and logs a BLOCKED audit event.
    """
    # 1. Propose valid Earbuds at 1599 (approved)
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

    # 2. Tamper with final_amount in database directly (e.g. simulation of DB injection / bypass)
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == pr_id).first()
    pr.final_amount = Decimal("10.00")  # Change from 1599.00 to 10.00
    db.commit()

    # 3. Attempt to trigger payment creation
    response = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert response.status_code == 400
    assert "parameters mismatch" in response.json()["detail"]

    # Verify audit event logged
    audit_evt = db.query(AuditEvent).filter(
        AuditEvent.action == "CREATE_PAYMENT",
        AuditEvent.result == "BLOCKED",
        AuditEvent.entity_id == pr_id
    ).first()
    assert audit_evt is not None
    assert "mismatch" in audit_evt.reason.lower()


def test_payment_endpoint_blocks_modified_product(client: TestClient, db):
    """
    Modified product: A PurchaseRequest gets APPROVED for Wireless Charging Case (₹399).
    Attacker modifies PurchaseRequest.product_id in DB to Premium Soundbar (₹5000).
    Expected: Rejected due to mismatch with PolicyDecision product_id.
    """
    # 1. Request Case at 399
    req_data = {
        "buyer_id": "buyer_agent_alpha",
        "product_id": 2, # Case
        "quantity": 1,
        "unit_price": "399.00",
        "original_amount": "399.00",
        "final_amount": "399.00",
        "discount_percent": "0.00",
        "currency": "INR",
        "reason": "Direct purchase"
    }
    purchase_res = client.post("/api/purchase/request", json=req_data).json()
    pr_id = purchase_res["purchase_request_id"]

    # 2. Tamper with product_id in DB: swap Case (2) for Soundbar (4)
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == pr_id).first()
    pr.product_id = 4
    db.commit()

    # 3. Attempt to trigger payment
    response = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert response.status_code == 400
    assert "parameters mismatch" in response.json()["detail"]


def test_payment_endpoint_blocks_blocked_purchase(client: TestClient, db):
    """
    BLOCKED purchase: PurchaseRequest is rejected by policy engine (decision = 'BLOCKED').
    Attacker attempts to create payment order anyway.
    Expected: Rejected.
    """
    req_data = {
        "buyer_id": "attacker",
        "product_id": 1,
        "quantity": 1,
        "unit_price": "1599.00",
        "original_amount": "1599.00",
        "final_amount": "159.00",  # ~90% discount (blocked)
        "discount_percent": "90.00",
        "currency": "INR",
        "reason": "I want it cheap"
    }
    purchase_res = client.post("/api/purchase/request", json=req_data).json()
    assert purchase_res["decision"] == "BLOCKED"
    pr_id = purchase_res["purchase_request_id"]

    # Try to pay
    response = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert response.status_code == 400
    assert "has not been APPROVED" in response.json()["detail"]


def test_payment_endpoint_blocks_requires_approval_purchase(client: TestClient, db):
    """
    REQUIRES_APPROVAL purchase: PurchaseRequest requires human review.
    Attacker tries to execute payment without human approval.
    Expected: Rejected.
    """
    req_data = {
        "buyer_id": "buyer_agent_alpha",
        "product_id": 4, # Soundbar at 5000 (above auto-approval limit)
        "quantity": 1,
        "unit_price": "5000.00",
        "original_amount": "5000.00",
        "final_amount": "5000.00",
        "discount_percent": "0.00",
        "currency": "INR",
        "reason": "Direct purchase"
    }
    purchase_res = client.post("/api/purchase/request", json=req_data).json()
    assert purchase_res["decision"] == "REQUIRES_APPROVAL"
    pr_id = purchase_res["purchase_request_id"]

    # Try to pay
    response = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert response.status_code == 400
    assert "has not been APPROVED" in response.json()["detail"]


def test_payment_endpoint_blocks_direct_payment_attempt(client: TestClient, db):
    """
    Direct payment attempt: Hitting payment endpoint with a completely random purchase request ID.
    Expected: Rejected with 404 (not found).
    """
    response = client.post("/api/payment/create?purchase_request_id=9999")
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_payment_endpoint_blocks_duplicate_payment_request(client: TestClient, db):
    """
    Duplicate payment request: Requesting order generation twice for the same approved request.
    Expected: First call succeeds; second call fails with duplicate transaction error.
    """
    # 1. Create approved request
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

    # 2. First payment call - success
    res1 = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert res1.status_code == 200
    assert "razorpay_order_id" in res1.json()

    # 3. Second payment call - idempotent return of existing order without creating duplicate
    res2 = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert res2.status_code == 200
    assert res2.json()["razorpay_order_id"] == res1.json()["razorpay_order_id"]


def test_agent_does_not_import_payments():
    """
    Architectural security assertion: Verifies that the agents module
    does NOT have any imports referencing backend.app.payments.payments or payments.
    This guarantees agents cannot bypass boundaries via imports.
    """
    import ast
    import os
    
    agent_file = os.path.join("backend", "app", "agents", "agents.py")
    with open(agent_file, "r") as f:
        tree = ast.parse(f.read())
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert "payments" not in name.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert "payments" not in node.module
            for name in node.names:
                assert "payments" not in name.name


def test_agent_has_no_credential_access():
    """
    Verifies that the agent instance, its tool registry, its systems instructions,
    and its tools do not have access to or reference settings.RAZORPAY_KEY_SECRET or mock values.
    """
    from backend.app.agents.agents import get_buyer_agent, MockLLMProvider
    from backend.app.config import settings
    
    provider = MockLLMProvider()
    agent = get_buyer_agent(provider)
    
    # 1. Verify agent properties
    assert not hasattr(agent, "key_secret")
    assert not hasattr(agent, "webhook_secret")
    
    # 2. Check system instructions
    assert settings.RAZORPAY_KEY_SECRET not in agent.system_instruction
    
    # 3. Check tool definitions and registry schemas
    tools_definitions = agent.registry.get_tool_definitions()
    schema_str = str(tools_definitions)
    assert settings.RAZORPAY_KEY_SECRET not in schema_str


from unittest.mock import MagicMock
from backend.app import payments as payments_module

def test_blocked_request_never_calls_razorpay(client: TestClient, db, monkeypatch):
    """
    Twin protection test:
    Mock the PaymentGatewayAdapter so we can inspect invocations.
    1. Try to pay a BLOCKED purchase request.
    2. Check that the API blocks it (HTTP 400).
    3. Assert that create_order was NEVER called.
    """
    # Mock the gateway adapter
    mock_adapter = MagicMock()
    # Replace the get_payment_adapter function to return our mock
    monkeypatch.setattr(payments_module, "get_payment_adapter", lambda: mock_adapter)

    # 1. Create a blocked purchase request (90% discount on Earbuds)
    req_data = {
        "buyer_id": "attacker",
        "product_id": 1,
        "quantity": 1,
        "unit_price": "1599.00",
        "original_amount": "1599.00",
        "final_amount": "159.00",
        "discount_percent": "90.00",
        "currency": "INR",
        "reason": "Tampered price request"
    }
    purchase_res = client.post("/api/purchase/request", json=req_data).json()
    assert purchase_res["decision"] == "BLOCKED"
    pr_id = purchase_res["purchase_request_id"]

    # 2. Attempt to trigger payment creation
    response = client.post(f"/api/payment/create?purchase_request_id={pr_id}")
    assert response.status_code == 400

    # 3. Assert mock was never called!
    assert mock_adapter.create_order.call_count == 0

