# SETU — AI Commerce Trust Layer

SETU is a production-quality trust layer designed for AI Growth & Agentic Commerce. It enables secure, policy-controlled B2B and consumer transactions initiated by AI buyer agents, ensuring that untrusted LLMs cannot execute or manipulate financial transfers directly.

## Security Architecture & Boundaries

The core security principle is: **The LLM is UNTRUSTED.**

### 1. Architectural Tool Isolation
* The LLM/Agent registry **never** has tools/functions like `create_razorpay_order`, `capture_payment`, or `refund_payment`. Direct access to the payment provider API and raw API credentials is strictly isolated behind a secure backend.
* The Agent registry has a strict tool filter that rejects any tools containing keywords such as `payment`, `razorpay`, `capture`, or `refund`.
* The agent only has a `request_purchase` tool, which submits a structured request to the database and evaluates it via the deterministic policy engine.

### 2. Deterministic Policy Checks
All policy limits (discount caps, profit margins, auto-transaction thresholds, out-of-stock, and budgets) are calculated and enforced in **deterministic Python backend code** using fixed-point `Decimal` arithmetic. The LLM cannot override or influence these calculations.

### 3. Payment Verification Barrier
The payment creation route (`POST /api/payment/create`) does not accept arbitrary amounts or orders from the frontend or the LLM. It strictly requires a valid, `APPROVED` `PurchaseRequest` ID already registered and validated in the database.

### 4. Audit Log Integrity
Every commercial event, evaluation decision, payment attempt, webhook callback, and attack scenario is logged to the `audit_events` database table to maintain an immutable log of agent interactions.

---

## Directory Structure

```text
SETU-AI-to-AI-agent/
│
├── backend/
│   ├── app/
│   │   ├── config/
│   │   │   └── config.py          # App settings & key config loaders
│   │   ├── database/
│   │   │   ├── database.py        # SQLAlchemy engine and SQLite session
│   │   │   └── seed.py            # Initial seed catalog & policies
│   │   ├── models/
│   │   │   └── models.py          # Database models (Product, PurchaseRequest, etc.)
│   │   ├── schemas/
│   │   │   └── schemas.py         # Pydantic validation schemas
│   │   ├── policy/
│   │   │   └── policy.py          # Deterministic Policy Engine (Decimal math)
│   │   ├── audit/
│   │   │   └── audit.py           # Database audit logger
│   │   ├── payments/
│   │   │   └── payments.py        # PaymentGatewayAdapter and Razorpay adapter
│   │   ├── webhooks/
│   │   │   └── webhooks.py        # Webhook signature/idempotency processor
│   │   ├── agents/
│   │   │   └── agents.py          # Buyer Agent and registry
│   │   └── main.py                # FastAPI routes & application entrypoint
│   └── requirements.txt           # Project package dependencies
│
├── tests/
│   ├── unit/
│   │   └── test_policy.py         # Unit tests for policy margin/discount math
│   ├── security/
│   │   └── test_security.py       # Tests for tool registration & payment blocks
│   ├── integration/
│   │   ├── test_webhook.py        # Signature validation and idempotency tests
│   │   └── test_demo_flow.py      # E2E Earbuds/Soundbar demo flows & attack mode
│   └── conftest.py                # Shared in-memory DB & TestClient config
│
└── README.md                      # Architecture documentation
```

---

## Quickstart Guide

### 1. Install Dependencies
Ensure you have Python 3.10+ installed. Install the backend packages:
```bash
pip install -r backend/requirements.txt
```

### 2. Run the Test Suite
Verify that all policy engines, webhooks, security controls, and agent actions pass tests:
```bash
python -m pytest
```

### 3. Start the FastAPI Server
Run the local development server:
```bash
uvicorn backend.app.main:app --reload
```
Once started, you can access the interactive API docs at `http://127.0.0.1:8000/docs`.

---

## API Endpoints

* **Catalog**:
  * `GET /api/catalog`: Retrieve all active products.
  * `GET /api/catalog/{product_id}`: Retrieve a specific product.
* **Agents & Negotiation**:
  * `POST /api/buyer/intent`: Routes buyer intent to the Buyer Agent.
  * `POST /api/merchant/offer`: Evaluates buyer offer and recommends counter-offers if blocked.
  * `POST /api/negotiation`: Buyer agent and merchant agent dialogue turns.
* **Purchase Requests**:
  * `POST /api/purchase/request`: Creates a request and triggers the Policy Engine.
  * `POST /api/policy/evaluate`: On-demand policy evaluator.
* **Payments & Webhooks**:
  * `POST /api/payment/create`: Generates Razorpay orders for approved purchases.
  * `POST /api/webhooks/razorpay`: Razorpay webhook verifying signature and updating transaction.
* **Audit & Transactions**:
  * `GET /api/audit`: Returns audit event history.
  * `GET /api/transactions`: Returns transaction statuses.
* **Attack Simulator**:
  * `POST /api/attack-test`: Allows testing of malicious prompt payloads.

---

## Remaining Roadmap & TODOs
1. **Frontend Interface**: Build the React + TypeScript frontend using Tailwind CSS to showcase the negotiation dialogue, the admin policy panel, and transaction audit logs.
2. **PostgreSQL Adapter**: Swap SQLAlchemy SQLite configuration for PostgreSQL to support production workloads.
3. **Third-Party Agent Integrations**: Add support for production LLM calls (e.g. Gemini API, OpenAI) by supplying credentials in `.env`.
