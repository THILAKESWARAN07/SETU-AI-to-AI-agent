# SETU Project Walkthrough

## Frontend Step 8: Post-Transaction Order & Fulfillment Experience

This document details the implementation of Step 8: a dedicated, secure post-payment order and fulfillment tracking panel built on top of the existing SQLite and policy engine backend.

### 1. Files Created
- **Pages**:
  - [`frontend/src/pages/Orders.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/pages/Orders.tsx): Main Orders Dashboard with status tabs and search options.
  - [`frontend/src/pages/Orders.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/pages/Orders.css): Styling for the Orders list dashboard.
  - [`frontend/src/pages/OrderDetails.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/pages/OrderDetails.tsx): Specific order inspection screen displaying compliance checkpoints and audit trails.
  - [`frontend/src/pages/OrderDetails.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/pages/OrderDetails.css): Layout styles for the order details grid.
- **Components**:
  - [`frontend/src/components/orders/OrderStatus.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderStatus.tsx): Status badge mapping.
  - [`frontend/src/components/orders/OrderStatus.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderStatus.css): Badge color configurations.
  - [`frontend/src/components/orders/OrderSummary.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderSummary.tsx): Compliance financial snapshot card.
  - [`frontend/src/components/orders/OrderSummary.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderSummary.css): Summary style definitions.
  - [`frontend/src/components/orders/OrderTimeline.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderTimeline.tsx): Reconstructed session flow merging audit logs and downstream mock steps.
  - [`frontend/src/components/orders/OrderTimeline.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderTimeline.css): Chronological flow connector lines and step highlights.
  - [`frontend/src/components/orders/OrderItems.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderItems.tsx): Product details grid wrapper.
  - [`frontend/src/components/orders/OrderItems.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderItems.css): Grid layout stylesheet.
  - [`frontend/src/components/orders/OrderEmptyState.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderEmptyState.tsx): Fallback view for empty orders registry.
  - [`frontend/src/components/orders/OrderEmptyState.css`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/orders/OrderEmptyState.css): Glow styling for empty bag indicator.

### 2. Files Modified
- [`frontend/src/types/index.ts`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/types/index.ts): Declared typed interfaces (`Order`, `OrderStatus`, `OrderItem`, `FulfillmentEvent`).
- [`frontend/src/App.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/App.tsx): Registered `/orders` and `/orders/:id` routes.
- [`frontend/src/layouts/DashboardLayout.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/layouts/DashboardLayout.tsx): Added NavLink for "Orders".
- [`frontend/src/components/payment/PaymentConfirmation.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/payment/PaymentConfirmation.tsx): Integrated "Track Order & Fulfillment" button.
- [`frontend/src/pages/TransactionDetails.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/pages/TransactionDetails.tsx): Integrated "View Order & Fulfillment" button.

### 3. Routes Added
- `/orders`
- `/orders/:id`

### 4. API Endpoints Reused
- `GET /api/transactions`: Retrieves transaction listings.
- `GET /api/audit`: Reconstructs negotiation rounds, intent boundaries, and policy outputs.
- `GET /api/catalog`: Resolves product characteristics and merchant details.

### 5. Security Considerations
- **No Client Calculations**: Financial totals, discounts, and margins are reconstructed purely from backend database logs (Transaction and PolicyDecision records).
- **Backend Authoritative Statuses**: Order progress is derived strictly from real transaction statuses in the database.
- **Razorpay Safety**: No private Razorpay keys or checkout authorization logic is exposed.

### 6. Limitations & Unavailable Backend Data
- **Downstream Fulfillment**: The SQLite database and FastAPI application do not feature physical shipping tracking tables (for `ORDER_ACCEPTED`, `PROCESSING`, `SHIPPED`, `DELIVERED` events).
- **Graceful Indication**: The UI explicitly flags these phases as `"Fulfillment data unavailable"` and displays descriptive text explaining this sandbox limitation, avoiding fabrication of shipping dates or courier reference tracking.

### 7. Verification Outcomes
- **Frontend Build**: Compiled successfully via `npm run build` with zero TypeScript errors.
- **Backend pytest**: Passed all 41 test scenarios (concurrency, demo, E2E, webhook logic, and policies) cleanly.
- **Regressions**: Backend source files were kept 100% untouched.

---

## Frontend & Backend Step 9: Real AI Agent Runtime & Autonomous Negotiation

This step replaces the mock UI-only negotiation with two schema-driven autonomous agent runtimes, executing a bounded turn-based negotiation loop controlled by a system orchestrator.

### 1. New & Refactored Agent Files
- [`backend/app/agents/orchestrator.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/backend/app/agents/orchestrator.py): Orchestrates the bounded turn-based loop, executes permitted tools, maintains status transitions, and enforces budget constraints.
- [`backend/app/agents/provider.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/backend/app/agents/provider.py): Declares structured output schemas (`BuyerDecision` and `MerchantDecision`) and implements deterministic, offline-capable Mock LLM response generation.
- [`backend/app/agents/tools.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/backend/app/agents/tools.py): Implements agentic sandboxed tools (`get_policy_constraints`, `evaluate_budget`, `get_inventory`, `get_product_price`, `get_merchant_constraints`, `evaluate_margin`).
- [`backend/app/agents/buyer_agent.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/backend/app/agents/buyer_agent.py): Restricts generative tools to catalog search, product details, policies, and budget checks.
- [`backend/app/agents/merchant_agent.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/backend/app/agents/merchant_agent.py): Restricts generative tools to inventory, product price, merchant policy constraints, and profit margin evaluations.

### 2. Main API & UI Wiring
- [`backend/app/main.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/backend/app/main.py): Modified `/api/demo/commerce` to instantiate the orchestrator loop and run real negotiation cycles. Broadened attack payload detection limits.
- [`frontend/src/components/negotiation/NegotiationTimeline.tsx`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/frontend/src/components/negotiation/NegotiationTimeline.tsx): Cleaned up rendering to display actual session history events, prices, and reasoning logs. Added catalog base value header.

### 3. Permitted Sandbox Tools
- **Buyer Agent**: `search_catalog`, `get_product_details`, `get_policy_constraints`, `evaluate_budget`.
- **Merchant Agent**: `get_inventory`, `get_product_price`, `get_merchant_constraints`, `evaluate_margin`.
- **Sandbox Guarantees**: Neither agent has access to payment processing adapters, credentials, or private Razorpay libraries.

### 4. Verification & Testing Coverage
Twelve new test cases were added to [`tests/unit/test_agents.py`](file:///c:/Users/HP/OneDrive/Pictures/Desktop/SETU-AI-to-AI-agent/tests/unit/test_agents.py) covering all requirements:
1. **Offer Generation**: Verified Buyer Agent creates valid OFFERS.
2. **Counter Offer**: Verified Merchant Agent counter-offers with structured items.
3. **Acceptance**: Verified Buyer accepts valid Merchant counter-offers.
4. **Budget Boundary**: Verified Buyer rejects counter-offers exceeding maximum budgets.
5. **Margin Boundary**: Verified Merchant rejects offers violating min profit margin limits.
6. **Output Validation**: Verified validation errors are raised for schema violations.
7. **Tool Sandbox**: Verified payment tools are strictly unavailable to both agents.
8. **Loop Bounds**: Verified Orchestrator stops turn loops exceeding `max_rounds`.
9. **Failed Negotiation Safety**: Verified failed negotiations do not trigger payments or approve requests.
10. **Policy Engine Authority**: Verified all deals run through Policy Engine verification.
11. **Event Persistence**: Verified full session audit logs are persisted in SQLite.
12. **Provider Failure**: Verified exceptions are handled gracefully if LLM provider fails.

### 5. Final Verification Outcomes
- **Frontend Build**: Compiled successfully (`npm run build`) with zero errors.
- **Backend pytest**: All **53 tests** (including legacy integration and new agent tests) pass successfully.
