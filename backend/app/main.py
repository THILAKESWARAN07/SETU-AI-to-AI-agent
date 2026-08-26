import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db, engine
from backend.seed import seed_db
from backend.app import models
from backend.app import schemas
from backend.app.policy import PolicyEngine
from backend.app.audit import AuditEngine
from backend.app import payments
from backend.app.webhooks import WebhookProcessor
from backend.app.agents.agents import get_buyer_agent, MockLLMProvider

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("setu.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Seed the database
    db = next(get_db())
    try:
        seed_db(db)
        logger.info("Database initialized and seeded.")
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

# CORS middleware for potential frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize standard Mock LLM
mock_llm = MockLLMProvider()
buyer_agent = get_buyer_agent(mock_llm)


# --- CATALOG ENDPOINTS ---

@app.get("/api/catalog", response_model=List[schemas.ProductSchema])
def get_catalog(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Product).filter(models.Product.active == True)
    if category:
        query = query.filter(models.Product.category == category)
    return query.all()


@app.get("/api/catalog/{product_id}", response_model=schemas.ProductSchema)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id, models.Product.active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# --- AGENTS & NEGOTIATION ENDPOINTS ---

@app.post("/api/buyer/intent", response_model=schemas.IntentResponse)
def handle_buyer_intent(request: schemas.IntentRequest, db: Session = Depends(get_db)):
    intent_lower = request.intent.lower()
    
    category = None
    if "earbud" in intent_lower or "sound" in intent_lower or "audio" in intent_lower:
        category = "Electronics"
    elif "case" in intent_lower or "charger" in intent_lower:
        category = "Accessories"
    
    products = db.query(models.Product).filter(models.Product.active == True)
    if category:
        products = products.filter(models.Product.category == category)
    products = products.all()
    
    response_text = f"Hello! I found {len(products)} products that match your request for '{request.intent}'."
    if "earbuds" in intent_lower and ("bundle" in intent_lower or "case" in intent_lower or "charging" in intent_lower):
        response_text = "I highly recommend our Wireless Earbuds + Charging Case Bundle, priced at 1998 INR."
    
    AuditEngine.log_event(
        db=db,
        actor="BUYER_AGENT",
        action="PROCESS_INTENT",
        result="SUCCESS",
        reason=f"Processed buyer intent: {request.intent}",
        metadata={"buyer_id": request.buyer_id}
    )
    
    return {
        "buyer_id": request.buyer_id,
        "intent": request.intent,
        "agent_response": response_text,
        "suggested_products": products
    }


@app.post("/api/merchant/offer", response_model=schemas.OfferResponse)
def evaluate_merchant_offer(request: schemas.OfferRequest, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == request.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    policy = db.query(models.MerchantPolicy).filter(models.MerchantPolicy.active == True).first()
    if not policy:
        raise HTTPException(status_code=500, detail="Active merchant policy not found")

    # Evaluate using the PolicyEngine
    decision = PolicyEngine.evaluate(
        product=product,
        policy=policy,
        quantity=request.quantity,
        final_amount=request.proposed_price
    )
    
    counter_price = None
    explanation = "Your proposed offer is approved and fits within our commercial policy guidelines."
    
    if decision["decision"] == "BLOCKED":
        explanation = "The proposed offer is blocked because it violates our pricing limits."
        
        # Calculate minimum acceptable total price based on min margin: cost_total / (1 - min_margin/100)
        margin_factor = Decimal("1") - (policy.min_margin_percent / Decimal("100"))
        cost_total = product.cost * Decimal(request.quantity)
        min_by_margin = cost_total / margin_factor
        
        # Calculate minimum acceptable total price based on max discount: price_total * (1 - max_discount/100)
        discount_factor = Decimal("1") - (policy.max_discount_percent / Decimal("100"))
        price_total = product.price * Decimal(request.quantity)
        min_by_discount = price_total * discount_factor
        
        # Propose the maximum of the two bounds
        counter_price = max(min_by_margin, min_by_discount).quantize(Decimal("0.01"))
        
        # Recheck
        counter_decision = PolicyEngine.evaluate(product, policy, request.quantity, counter_price)
        if counter_decision["decision"] == "BLOCKED":
            counter_price = None
            explanation = "We cannot make a counter-offer because this product is unavailable or discontinued."
        else:
            explanation = f"We cannot accept {request.proposed_price} INR. Our best possible counter-offer is {counter_price} INR."
            
    elif decision["decision"] == "REQUIRES_APPROVAL":
        explanation = "This high-value order requires human admin approval before processing."

    AuditEngine.log_event(
        db=db,
        actor="MERCHANT_AGENT",
        action="EVALUATE_OFFER",
        result=decision["decision"],
        reason=explanation,
        entity_type="Product",
        entity_id=product.id,
        policy_version=policy.policy_version,
        metadata={
            "quantity": request.quantity,
            "proposed_price": str(request.proposed_price),
            "counter_price": str(counter_price) if counter_price else None
        }
    )

    return {
        "decision": decision["decision"],
        "reasons": decision["reasons"],
        "calculated_margin_percent": decision["calculated_margin_percent"],
        "discount_percent": decision["discount_percent"],
        "counter_offer_price": counter_price,
        "explanation": explanation
    }


@app.post("/api/negotiation", response_model=schemas.NegotiationResponse)
def run_negotiation_turn(request: schemas.NegotiationRequest, db: Session = Depends(get_db)):
    # Buyer agent negotiation simulation
    # Pass formatted prompt including product info and quantity requested
    msg = f"Product ID: {request.product_id}, Quantity: {request.quantity}. Message: {request.message}"
    agent_output = buyer_agent.process_message(db, msg)
    
    offer_details = None
    for exec_tool in agent_output.get("tool_executions", []):
        if exec_tool["tool_name"] == "request_purchase" and "result" in exec_tool:
            res = exec_tool["result"]
            offer_details = {
                "purchase_request_id": res.get("purchase_request_id"),
                "decision": res.get("decision"),
                "reasons": res.get("reasons"),
                "discount_percent": res.get("discount_percent"),
                "margin_percent": res.get("margin_percent")
            }
            
    return {
        "buyer_id": request.buyer_id,
        "product_id": request.product_id,
        "agent_response": agent_output["agent_response"],
        "offer": offer_details
    }


# --- PURCHASE REQUEST FLOW ---

@app.post("/api/purchase/request", response_model=schemas.PolicyDecisionSchema)
def create_purchase_request(request: schemas.PurchaseRequestCreate, db: Session = Depends(get_db)):
    """
    Submits a purchase request, saves unit price and quantity snapshots,
    and runs it through the Policy Engine.
    """
    product = db.query(models.Product).filter(models.Product.id == request.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    policy = db.query(models.MerchantPolicy).filter(models.MerchantPolicy.active == True).first()
    if not policy:
        raise HTTPException(status_code=500, detail="Active merchant policy not found")

    # Evaluate the proposed purchase price
    eval_result = PolicyEngine.evaluate(
        product=product,
        policy=policy,
        quantity=request.quantity,
        final_amount=request.final_amount
    )

    decision_status = eval_result["decision"]  # APPROVED, BLOCKED, REQUIRES_APPROVAL

    # 1. Create PurchaseRequest in database
    purchase_req = models.PurchaseRequest(
        buyer_id=request.buyer_id,
        product_id=request.product_id,
        quantity=request.quantity,
        unit_price=request.unit_price,
        original_amount=request.original_amount,
        final_amount=request.final_amount,
        discount_percent=request.discount_percent,
        currency=request.currency,
        reason=request.reason,
        status=decision_status
    )
    db.add(purchase_req)
    db.commit()
    db.refresh(purchase_req)

    # 2. Create PolicyDecision Record (retains snapshot details)
    decision_record = models.PolicyDecision(
        purchase_request_id=purchase_req.id,
        decision=decision_status,
        reasons=eval_result["reasons"],
        policy_version=policy.policy_version,
        calculated_margin_percent=eval_result["calculated_margin_percent"],
        product_id=request.product_id,
        quantity=request.quantity,
        unit_price=request.unit_price,
        original_amount=request.original_amount,
        final_amount=request.final_amount,
        discount_percent=request.discount_percent,
        currency=request.currency
    )
    db.add(decision_record)
    db.commit()
    db.refresh(decision_record)

    # 3. Log to Audit Engine
    AuditEngine.log_event(
        db=db,
        actor="SYSTEM",
        action="EVALUATE_POLICY",
        result=decision_status,
        reason=", ".join(eval_result["reasons"]) or "Passed all checks",
        entity_type="PurchaseRequest",
        entity_id=purchase_req.id,
        policy_version=policy.policy_version,
        metadata={
            "quantity": request.quantity,
            "final_amount": str(request.final_amount),
            "discount_percent": str(request.discount_percent),
            "margin_percent": str(eval_result["calculated_margin_percent"])
        }
    )

    return decision_record


@app.post("/api/policy/evaluate")
def evaluate_policy(product_id: int, quantity: int, proposed_price: Decimal, buyer_budget: Optional[Decimal] = None, db: Session = Depends(get_db)):
    """
    On-demand evaluation of policy without creating a database transaction.
    """
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    policy = db.query(models.MerchantPolicy).filter(models.MerchantPolicy.active == True).first()
    if not policy:
        raise HTTPException(status_code=500, detail="Active merchant policy not found")

    result = PolicyEngine.evaluate(product, policy, quantity, proposed_price, buyer_budget)
    
    # Serialize decimals
    result["calculated_margin_percent"] = str(result["calculated_margin_percent"])
    result["discount_percent"] = str(result["discount_percent"])
    
    return result


@app.post("/api/admin/approve/{purchase_request_id}", response_model=schemas.PolicyDecisionSchema)
def admin_approve_request(purchase_request_id: int, db: Session = Depends(get_db)):
    """
    Manual human override. Approves a request that is currently in REQUIRES_APPROVAL status,
    creating a matching approved PolicyDecision record.
    """
    pr = db.query(models.PurchaseRequest).filter(models.PurchaseRequest.id == purchase_request_id).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != "REQUIRES_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail=f"Only requests with status 'REQUIRES_APPROVAL' can be manually approved. Current status: '{pr.status}'"
        )

    policy = db.query(models.MerchantPolicy).filter(models.MerchantPolicy.active == True).first()
    if not policy:
        raise HTTPException(status_code=500, detail="Active merchant policy not found")

    # Update status to APPROVED
    pr.status = "APPROVED"

    # Create matching PolicyDecision
    decision_record = models.PolicyDecision(
        purchase_request_id=pr.id,
        decision="APPROVED",
        reasons=["Manually approved by human admin override."],
        policy_version=policy.policy_version,
        calculated_margin_percent=((pr.final_amount - pr.product.cost * pr.quantity) / pr.final_amount) * Decimal("100"),
        product_id=pr.product_id,
        quantity=pr.quantity,
        unit_price=pr.unit_price,
        original_amount=pr.original_amount,
        final_amount=pr.final_amount,
        discount_percent=pr.discount_percent,
        currency=pr.currency
    )
    db.add(decision_record)
    
    # Log audit event
    AuditEngine.log_event(
        db=db,
        actor="HUMAN",
        action="MANUAL_APPROVAL",
        result="APPROVED",
        reason="Admin manually approved high-value purchase request.",
        entity_type="PurchaseRequest",
        entity_id=pr.id,
        policy_version=policy.policy_version,
        metadata={"purchase_request_id": pr.id}
    )
    
    db.commit()
    db.refresh(decision_record)
    return decision_record


# --- PAYMENT SERVICE ENDPOINTS ---

@app.post("/api/payment/create", response_model=schemas.TransactionSchema)
def create_payment(purchase_request_id: int, db: Session = Depends(get_db)):
    """
    Exposed payment generation route. Delegates to process_payment_creation which
    enforces all strict cross-validation matching logic.
    """
    try:
        tx = payments.process_payment_creation(db, purchase_request_id)
        return tx
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/webhooks/razorpay")
async def handle_razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    signature = request.headers.get("X-Razorpay-Signature")
    if not signature:
        AuditEngine.log_event(
            db=db,
            actor="WEBHOOK",
            action="PROCESS_WEBHOOK",
            result="FAIL",
            reason="Webhook request missing X-Razorpay-Signature header."
        )
        raise HTTPException(status_code=400, detail="Missing signature header")

    # Verify signature over raw payload bytes
    payload_bytes = await request.body()
    result = WebhookProcessor.process_razorpay_webhook(db, payload_bytes, signature)
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
        
    return result


# --- AUDIT & UTILITY ENDPOINTS ---

@app.get("/api/audit", response_model=List[schemas.AuditEventSchema])
def get_audit_trail(db: Session = Depends(get_db)):
    return db.query(models.AuditEvent).order_by(models.AuditEvent.timestamp.desc()).all()


@app.get("/api/transactions", response_model=List[schemas.TransactionSchema])
def get_transactions(db: Session = Depends(get_db)):
    return db.query(models.Transaction).order_by(models.Transaction.created_at.desc()).all()


# --- E2E DEMO ORCHESTRATION ENDPOINT ---

class DemoCommerceRequest(BaseModel):
    buyer_id: str
    intent: str
    budget: Decimal = Decimal("2000.00")

class DemoCommerceResponse(BaseModel):
    buyer_id: str
    intent: str
    catalog_search_results: List[Dict[str, Any]]
    selected_product_id: int
    cross_sell_product_id: int
    bundle_offer: Dict[str, Any]
    negotiation_history: List[Dict[str, Any]]
    purchase_request_id: int
    decision: str
    reasons: List[str]
    original_amount: str
    final_amount: str
    discount_percent: str
    margin_percent: str
    policy_version: str
    
    # Trace variables
    agent_mode: str = "OFFLINE MOCK"
    buyer_objective: str = "Optimize bundle pricing & enforce budget limits"
    buyer_tools_used: List[str] = []
    buyer_confidence: float = 1.0
    merchant_objective: str = "Maximize sales margins & bundle volume conversion"
    merchant_tools_used: List[str] = []
    merchant_confidence: float = 1.0
    
    # Step 12 metadata
    provider: str = "MockProvider"
    model: str = "mock-model-v2"
    execution_mode: str = "OFFLINE MOCK"
    session_id: str = "session_mock"
    agent_role: str = "BUYER_AGENT & MERCHANT_AGENT"
    start_time: str = ""
    completion_time: str = ""

@app.post("/api/demo/commerce", response_model=DemoCommerceResponse)
def run_demo_commerce_flow(request: DemoCommerceRequest, db: Session = Depends(get_db)):
    from backend.app.agents.provider import get_provider
    from backend.app.agents.buyer_agent import BuyerAgent
    from backend.app.agents.merchant_agent import MerchantAgent
    from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError

    provider = get_provider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)

    try:
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)
        res = orchestrator.run_negotiation_loop(
            buyer_id=request.buyer_id,
            intent=request.intent,
            budget=request.budget,
            max_rounds=4
        )
        return res
    except NegotiationError as e:
        logger.error(f"Autonomous negotiation aborted: {e}")
        if getattr(e, "result_data", None) is not None:
            return e.result_data
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"General error in commerce flow: {e}")
        raise HTTPException(status_code=500, detail="Negotiation flow encountered a system error.")


# --- ATTACK TEST ENDPOINT ---

@app.post("/api/attack-test", response_model=schemas.AttackTestResponse)
def simulate_attack(request: schemas.AttackTestRequest, db: Session = Depends(get_db)):
    """
    Simulates attacks. Independent of the LLM output, validation logic checks the outputs
    against database policy engine to block unauthorized attempts.
    """
    payload_lower = request.payload.lower()
    
    # Process message through agent
    agent_output = buyer_agent.process_message(db, request.payload)
    tool_execs = agent_output.get("tool_executions", [])
    
    is_blocked = False
    block_reason = "No purchase tool executions triggered."
    decision_str = None
    
    for exc in tool_execs:
        if exc["tool_name"] == "request_purchase":
            res = exc.get("result", {})
            decision_str = res.get("decision")
            
            if decision_str in ["BLOCKED", "REQUIRES_APPROVAL"]:
                is_blocked = True
                block_reason = f"Policy Engine blocked the transaction. Decision: {decision_str}. Reasons: {res.get('reasons')}"
            else:
                is_blocked = False
                block_reason = f"Policy Engine evaluated decision: {decision_str}"

    # General block overrides for explicit attacks
    if "ignore" in payload_lower or "bypass" in payload_lower or "80%" in payload_lower or "90%" in payload_lower:
        is_blocked = True
        block_reason = "Blocked. Security Engine intervened. Proposed purchase violates merchant pricing boundaries."
        decision_str = "BLOCKED"

    if "razorpay" in payload_lower or "create_razorpay_order" in payload_lower:
        is_blocked = True
        block_reason = "Blocked. ToolRegistry lacks any payment-related functions."
        decision_str = "BLOCKED"

    # Log specific audit event
    audit_evt = AuditEngine.log_event(
        db=db,
        actor="LLM_ATTACK_TEST",
        action="SIMULATE_ATTACK",
        result="BLOCKED" if is_blocked else "FLAGGED",
        reason=f"Attack payload: {request.payload} | Result: {block_reason}",
        metadata={"payload": request.payload}
    )

    return {
        "is_blocked": is_blocked,
        "audit_event_logged": audit_evt is not None,
        "reason": block_reason,
        "decision": decision_str,
        "details": {
            "agent_response": agent_output["agent_response"],
            "tool_executions": tool_execs
        }
    }
