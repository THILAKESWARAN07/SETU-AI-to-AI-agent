# SETU — Buildathon Presentation Script & Demo Guide

This guide details a step-by-step 3-5 minute presentation script for judges. It highlights the problem, the SETU trust layer architecture, live negotiations, policy boundaries, and checkout execution.

---

## ⏱️ Timeline & Presentation Flow

### 0:00 - 0:30 | The Problem
* **What to say**: 
  > "As AI agents are given buying power, they must interact with payment gateways. However, if we give an LLM direct access to credit cards or payment APIs, it faces massive risks: prompt injection can bypass business rules, raw gateway credentials can leak, and infinite negotiation loops can blow token budgets. The LLM is untrusted."
* **What to click**: Show the home page (landing/hero experience) containing the title: **"SETU — AI Agents That Negotiate Commerce Safely"**.
* **What the judge should notice**: The professional, dark-themed, premium hackathon interface with clear architectural steps.

### 0:30 - 1:00 | The SETU Solution
* **What to say**: 
  > "SETU solves this by separating the Proposer (the LLM agents) from the Decider (our deterministic Python Policy Engine). AI agents discover products and negotiate offers in a sandboxed tool registry, but the final transaction and payment handoff are locked and verified server-side. Payment amounts cannot be altered by LLMs."
* **What to click**: Hover over the steps in the **"Platform Architecture Flow"** panel on the home page (Step 1 to Step 5) to highlight:
  1. *Buyer Agent (LLM Isolated)*
  2. *Merchant Agent (LLM Isolated)*
  3. *Negotiation Engine (AI-to-AI Dialog)*
  4. *Policy Engine (Fixed-Point Math)*
  5. *Secure Payment Gateway (Database Locked)*
* **What the judge should notice**: The active gating statuses indicating that the engine, database, and adapters are running with active security restrictions.

### 1:00 - 2:00 | Live Buyer ↔ Merchant Negotiation
* **What to say**: 
  > "Let's launch a live procurement negotiation. We'll start Scenario 1: A buyer needs wireless earbuds under ₹2,000. Here, our Buyer Agent and Merchant Agent will negotiate autonomously in real-time."
* **What to click**: Click the **"START AI COMMERCE DEMO"** button on the home page. This instantly redirects to `/negotiation` and triggers the live/mock negotiation flow.
* **What the judge should notice**:
  - The live animation stepping through agent events.
  - The left column: **Buyer AI Agent** executing tools (`search_catalog`, `evaluate_budget`) and proposing offers (e.g. ₹1,400.00).
  - The right column: **Merchant AI Agent** executing tools (`get_product_price`, `evaluate_margin`) and proposing counter-offers (e.g. ₹1,440.00).
  - The center column: **SETU Policy Engine** actively auditing each step.
  - The **"Real vs Mock Provider Visibility"** tag at the top right indicating the mode (`MODE: LIVE LLM` or `MODE: OFFLINE MOCK`).

### 2:00 - 2:30 | SETU Policy & Security Boundary
* **What to say**: 
  > "Once the agents agree, the SETU Policy Engine runs deterministic budget and minimum margin checks on the server. If approved, SETU generates an immutable transaction record in the database, locking the final value. If any rule is broken—for example, if the proposed price is below the merchant cost, or exceeds the buyer budget—SETU blocks it immediately."
* **What to click**:
  - If showing the successful negotiation, point out the **"AGREEMENT LOCKED"** status.
  - Return to shopping and click **"Scenario 2: Budget Protection"** to demonstrate how a restricted budget causes a structured block:
    - *What Happened*: `REQUEST BLOCKED`
    - *Why SETU Stopped It*: `Proposed amount violates buyer budget limits`
    - *Enforcing Authority*: `SETU PolicyEngine`
* **What the judge should notice**: The structured block evidence cards proving that the Policy Engine, not the LLM, holds final authority.

### 2:30 - 3:30 | Razorpay Payment Handoff
* **What to say**: 
  > "For the approved deal, SETU hands off a pre-calculated order token to the frontend. The checkout modal retrieves the price directly from the server-side locked record. The client cannot inject a modified amount."
* **What to click**: In Scenario 1, click **"Proceed to Secure Checkout"**. When the mock Razorpay checkout panel appears, click **"Simulate Razorpay Gateway Success"**.
* **What the judge should notice**: The modal showing the exact locked negotiated price, demonstrating zero frontend tampering vectors.

### 3:30 - 4:00 | Order + Audit Trail
* **What to say**: 
  > "After payment, the webhook verification adapter verifies the HMAC SHA256 signature to settle order states. Let's inspect the secure audit trace of the entire session."
* **What to click**: Let the payment transition load the success screen. Click **"View Full Agent Trace"** to view the chronological log:
  `SESSION START -> CATALOG_SEARCH -> EVALUATE_BUDGET -> NEGOTIATION -> POLICY_CHECK -> TRANSACTION_APPROVED -> PAYMENT -> WEBHOOK -> ORDER_CREATED`.
* **What the judge should notice**: The raw database log showing exact event entries, confirming the system ran real tools rather than displaying hardcoded text.

### 4:00 - 5:00 | Security / Differentiation / Impact
* **What to say**: 
  > "By restricting tool registries, enforcing deterministic policies, and locking payments at the server level, SETU turns generative commerce into a reliable, secure business transaction model suitable for production environments. Thank you!"

---

## 🛠️ Fallback Plan (If Gemini API is Rate-Limited/HTTP 429)

1. **How to identify**: The negotiation screen will display a red header tag: **`MODE: PROVIDER ERROR`** and alert banner: **`LLM Provider Connection Interrupted: 429 Quota Exceeded`**.
2. **What to do**: Click the **"RESET DEMO"** button to go back to Shopping. Set the environment variable `$env:LLM_PROVIDER="mock"` to run the local mock simulations, which showcase identical security controls and policy enforcement using preconfigured mock responses.
