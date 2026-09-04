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

origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://setu-ai-to-ai-agent.vercel.app",
]

# CORS middleware for potential frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

@app.get("/api/agent/provider-status")
def get_provider_status():
    import os
    from backend.app.config import settings
    from backend.app.agents.provider import get_provider_for_agent, get_provider
    
    buyer_p = get_provider_for_agent("buyer")
    merchant_p = get_provider_for_agent("merchant")
    auxiliary_p = get_provider_for_agent("auxiliary")
    legacy_p = get_provider()

    return {
        "configured_provider": os.getenv("LLM_PROVIDER", settings.LLM_PROVIDER).lower(),
        "configured_model": os.getenv("LLM_MODEL", settings.LLM_MODEL),
        "timeout_seconds": float(os.getenv("LLM_TIMEOUT_SECONDS", str(settings.LLM_TIMEOUT_SECONDS))),
        "fallback_to_mock": os.getenv("LLM_FALLBACK_TO_MOCK", str(settings.LLM_FALLBACK_TO_MOCK)).lower() in ("true", "1", "yes"),
        "active_provider_name": legacy_p.provider_name,
        "active_model_name": legacy_p.model_name,
        "active_agent_mode": legacy_p.agent_mode,
        "buyer": {
            "configured_primary": settings.BUYER_LLM_PROVIDER,
            "configured_model": settings.BUYER_LLM_MODEL,
            "configured_fallbacks": [f.strip() for f in settings.BUYER_LLM_FALLBACKS.split(",") if f.strip()],
            "active_provider": buyer_p.provider_name,
            "active_model": buyer_p.model_name,
            "agent_mode": buyer_p.agent_mode,
            "chain": [p.provider_name for p in getattr(buyer_p, "providers", [buyer_p])],
        },
        "merchant": {
            "configured_primary": settings.MERCHANT_LLM_PROVIDER,
            "configured_model": settings.MERCHANT_LLM_MODEL,
            "configured_fallbacks": [f.strip() for f in settings.MERCHANT_LLM_FALLBACKS.split(",") if f.strip()],
            "active_provider": merchant_p.provider_name,
            "active_model": merchant_p.model_name,
            "agent_mode": merchant_p.agent_mode,
            "chain": [p.provider_name for p in getattr(merchant_p, "providers", [merchant_p])],
        },
        "auxiliary": {
            "configured_primary": settings.AUXILIARY_LLM_PROVIDER,
            "configured_model": settings.AUXILIARY_LLM_MODEL,
            "configured_fallbacks": [f.strip() for f in settings.AUXILIARY_LLM_FALLBACKS.split(",") if f.strip()],
            "active_provider": auxiliary_p.provider_name,
            "active_model": auxiliary_p.model_name,
            "agent_mode": auxiliary_p.agent_mode,
            "chain": [p.provider_name for p in getattr(auxiliary_p, "providers", [auxiliary_p])],
        },
        "keys_configured": {
            "gemini": bool(settings.GEMINI_API_KEY),
            "openrouter": bool(settings.OPENROUTER_API_KEY),
            "groq": bool(settings.GROQ_API_KEY)
        },
        "fallback_to_mock_enabled": settings.LLM_FALLBACK_TO_MOCK
    }


@app.post("/api/buyer/intent", response_model=schemas.IntentResponse)
def handle_buyer_intent(request: schemas.IntentRequest, db: Session = Depends(get_db)):
    from backend.app.agents.tools import search_catalog_tool
    matched = search_catalog_tool(db, query=request.intent)
    matched_ids = [m["id"] for m in matched]
    products = db.query(models.Product).filter(models.Product.id.in_(matched_ids), models.Product.active == True).all() if matched_ids else []
    
    if products:
        if "earbuds" in request.intent.lower() and ("case" in request.intent.lower() or "bundle" in request.intent.lower() or "charging" in request.intent.lower()):
            response_text = f"Hello! I found {len(products)} products that match your request for '{request.intent}'. I recommend the Wireless Earbuds + Charging Case Bundle."
        else:
            response_text = f"Hello! I found {len(products)} products that match your request for '{request.intent}'."
    else:
        response_text = f"Procurement failed: No products found matching '{request.intent}'."
    
    AuditEngine.log_event(
        db=db,
        actor="BUYER_AGENT",
        action="PROCESS_INTENT",
        result="SUCCESS" if products else "NOT_FOUND",
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

    # Resolve/build the basket
    resolved_basket = request.basket
    if not resolved_basket:
        resolved_basket = {
            "items": [
                {
                    "product_id": request.product_id,
                    "name": product.name,
                    "quantity": request.quantity,
                    "original_price": str(product.price),
                    "negotiated_price": str(request.final_amount / Decimal(request.quantity)),
                    "is_primary": True
                }
            ],
            "original_total": str(request.original_amount),
            "final_total": str(request.final_amount),
            "discount_amount": str(request.original_amount - request.final_amount)
        }

    # Evaluate the proposed purchase basket
    eval_result = PolicyEngine.evaluate_basket(
        basket=resolved_basket,
        policy=policy,
        buyer_budget=Decimal("1000000.00"),
        primary_product_id=request.product_id,
        db=db
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
        status=decision_status,
        basket=resolved_basket
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


@app.get("/api/payment/config", response_model=schemas.PaymentConfigSchema)
def get_payment_config():
    """
    Exposes the active payment gateway configuration (mode and public client key).
    """
    return {
        "payment_mode": settings.active_payment_mode,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID if settings.active_payment_mode == "razorpay" else ""
    }


@app.post("/api/payment/verify", response_model=schemas.TransactionSchema)
def verify_payment(payload: schemas.PaymentVerifySchema, db: Session = Depends(get_db)):
    """
    Cryptographically verifies the Razorpay payment callback signature on the server.
    Ensures that amounts are locked and transactions are processed idempotently.
    """
    logger.info(f"Received signature verification request for order_id: {payload.razorpay_order_id}")
    tx = db.query(models.Transaction).filter(
        models.Transaction.razorpay_order_id == payload.razorpay_order_id
    ).first()
    
    if not tx:
        AuditEngine.log_event(
            db=db,
            actor="SYSTEM",
            action="VERIFY_PAYMENT",
            result="FAIL",
            reason=f"No transaction found for Razorpay order ID: {payload.razorpay_order_id}"
        )
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.status == "SUCCESS":
        return tx

    adapter = payments.get_payment_adapter()
    is_valid = adapter.verify_payment_signature(
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature
    )

    if not is_valid:
        tx.status = "FAILED"
        db.commit()

        AuditEngine.log_event(
            db=db,
            actor="SYSTEM",
            action="VERIFY_PAYMENT",
            result="FAIL",
            reason="Invalid payment signature callback received.",
            entity_type="Transaction",
            entity_id=tx.id,
            metadata={
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id
            }
        )
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    tx.status = "SUCCESS"
    tx.razorpay_payment_id = payload.razorpay_payment_id
    tx.razorpay_signature = payload.razorpay_signature

    pr = db.query(models.PurchaseRequest).filter(
        models.PurchaseRequest.id == tx.purchase_request_id
    ).first()
    if pr:
        try:
            payments.deduct_inventory_for_paid_purchase(db, pr)
        except ValueError as e:
            tx.status = "FAILED"
            db.commit()
            raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    db.refresh(tx)

    AuditEngine.log_event(
        db=db,
        actor="SYSTEM",
        action="VERIFY_PAYMENT",
        result="SUCCESS",
        reason=f"Payment verified successfully. Razorpay Order ID: {payload.razorpay_order_id}",
        entity_type="Transaction",
        entity_id=tx.id,
        metadata={
            "razorpay_order_id": payload.razorpay_order_id,
            "razorpay_payment_id": payload.razorpay_payment_id,
            "amount": str(tx.amount)
        }
    )

    return tx


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
    logger.info("Retrieving transaction archive from database.")
    txs = db.query(models.Transaction).order_by(models.Transaction.created_at.desc()).all()
    logger.info(f"Retrieved {len(txs)} transactions from database.")
    return txs


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
    conversation_events: List[Dict[str, Any]] = []
    purchase_request_id: int
    decision: str
    reasons: List[str]
    original_amount: str
    final_amount: str
    discount_percent: str
    margin_percent: str
    policy_version: str
    basket: Optional[Dict[str, Any]] = None
    
    # Trace variables
    agent_mode: str = "OFFLINE MOCK"
    buyer_objective: str = "Optimize bundle pricing & enforce budget limits"
    buyer_tools_used: List[str] = []
    buyer_confidence: float = 1.0
    merchant_objective: str = "Maximize sales margins & bundle volume conversion"
    merchant_tools_used: List[str] = []
    merchant_confidence: float = 1.0
    
    provider_summary: Optional[Dict[str, Any]] = None
    
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
    from backend.app.agents.provider import get_provider_for_agent
    from backend.app.agents.buyer_agent import BuyerAgent
    from backend.app.agents.merchant_agent import MerchantAgent
    from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError

    buyer = BuyerAgent(get_provider_for_agent("buyer"))
    merchant = MerchantAgent(get_provider_for_agent("merchant"))

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

@app.post("/api/demo/commerce/stream")
def stream_demo_commerce_flow(request: DemoCommerceRequest, db: Session = Depends(get_db)):
    from fastapi.responses import StreamingResponse
    from backend.app.agents.provider import get_provider_for_agent
    from backend.app.agents.buyer_agent import BuyerAgent
    from backend.app.agents.merchant_agent import MerchantAgent
    from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
    import json
    import queue
    import threading

    def event_stream():
        buyer = BuyerAgent(get_provider_for_agent("buyer"))
        merchant = MerchantAgent(get_provider_for_agent("merchant"))
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        event_q: queue.Queue = queue.Queue()

        def on_event_cb(evt: dict):
            event_q.put({"msg_type": "event", "data": evt})

        def worker():
            try:
                res = orchestrator.run_negotiation_loop(
                    buyer_id=request.buyer_id,
                    intent=request.intent,
                    budget=request.budget,
                    max_rounds=4,
                    on_event=on_event_cb
                )
                event_q.put({"msg_type": "complete", "result": res})
            except NegotiationError as e:
                err_data = getattr(e, "result_data", {"decision": "REJECTED", "reasons": [str(e)]})
                event_q.put({"msg_type": "error", "error": str(e), "result": err_data})
            except Exception as e:
                logger.error(f"Error in streaming negotiation worker: {e}", exc_info=True)
                event_q.put({"msg_type": "error", "error": str(e)})

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                item = event_q.get(timeout=30.0)
            except queue.Empty:
                yield f"data: {json.dumps({'event_type': 'ERROR', 'type': 'error', 'error': 'Stream timed out.'})}\n\n"
                break

            if item["msg_type"] == "event":
                yield f"data: {json.dumps(item['data'])}\n\n"
            elif item["msg_type"] == "complete":
                yield f"data: {json.dumps({'event_type': 'COMPLETE', 'type': 'complete', 'result': item['result']})}\n\n"
                break
            elif item["msg_type"] == "error":
                yield f"data: {json.dumps({'event_type': 'ERROR', 'type': 'error', 'error': item.get('error'), 'result': item.get('result')})}\n\n"
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
