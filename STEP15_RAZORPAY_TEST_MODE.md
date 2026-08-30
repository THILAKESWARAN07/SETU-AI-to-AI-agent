# SETU - STEP 15 Razorpay Test Mode Documentation

This document describes how to configure, start, and manually verify the **Real Razorpay Test Mode** payment integration alongside the **Offline Mock Mode** fallback in the SETU AI Commerce Trust Layer project.

---

## 1. How to Create Razorpay Test Mode Keys

1. Sign up or log into your [Razorpay Dashboard](https://dashboard.razorpay.com/).
2. Switch to **Test Mode** (usually toggled in the top-right corner or menu sidebar of the dashboard).
3. Navigate to **Account & Settings** -> **API Keys**.
4. Click **Generate Key** to generate a new `Key ID` and `Key Secret`.
5. Note them down safely (never share or commit them).
6. To test webhook processing, navigate to **Webhooks** -> **Add New Webhook**:
   - Set Webhook URL to: `http://<your-public-ngrok-or-domain>/api/webhooks/razorpay` (or use the simulated local triggers).
   - Enter a secure string in **Secret** (this is your `RAZORPAY_WEBHOOK_SECRET`).
   - Select Event: `order.paid` (or `payment.captured`).

---

## 2. Environment Configuration (`.env`)

Add the following environment variables to your `.env` file in the project root directory. Do NOT commit the `.env` file to Git.

```env
# Mode selection: 'razorpay' or 'mock' (defaults safely to mock if unset/keys are defaults)
PAYMENT_MODE=razorpay

# Razorpay Test Mode Keys
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxx
RAZORPAY_KEY_SECRET=your_test_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
RAZORPAY_MODE=test

# Other configurations
LLM_PROVIDER=mock
DATABASE_URL=sqlite:///./setu.db
```

---

## 3. How to Start the Backend Server

Start the FastAPI backend server using Uvicorn from the root folder:

```bash
uvicorn backend.app.main:app --reload
```

The backend API will run at `http://localhost:8000`.

---

## 4. How to Start the Frontend Dev Server

Navigate to the `frontend` folder, install dependencies if necessary, and run the development server:

```bash
cd frontend
npm install
npm run dev
```

The frontend application will run at `http://localhost:5173`.

---

## 5. How to Select Razorpay Test Mode vs Offline Mock Mode

To switch modes, open your `.env` file and change the `PAYMENT_MODE` value:
- **For Real Razorpay Test Mode**: `PAYMENT_MODE=razorpay` (requires valid keys).
- **For Offline Mock Mode**: `PAYMENT_MODE=mock`.

The UI will automatically display a status badge in the checkout header:
- **`RAZORPAY TEST MODE`** in blue.
- **`OFFLINE MOCK`** in grey.

---

## 6. How to Perform a Test Checkout

1. Open the frontend dashboard at `http://localhost:5173`.
2. Click **Go to Shopping** and select the **Wireless Earbuds** (or any category containing electronics).
3. Open the **Procurement Hub** to begin negotiations.
4. Input a prompt (e.g., "I want earbuds under 2000 INR").
5. The Buyer and Merchant agents will autonomously negotiate. Once approved, the Policy Engine will validate the final price.
6. Click **Proceed to Secure Checkout**.
7. The payment page will load, creating a corresponding Razorpay order on the backend securely.
8. Click **Pay with Razorpay Test Mode**. The Razorpay Standard Checkout modal will open.

---

## 7. Razorpay Test Payment Details

Use the following test credentials inside the Razorpay Checkout widget:
- **Phone Number**: Any valid 10-digit number (e.g. `9999999999`).
- **Email**: Any valid email (e.g. `buyer@example.com`).
- **Payment Method**: Card.
- **Card Number**: Use any standard Razorpay test card:
  - `4111 1111 1111 1111` (Visa - Success)
  - `4111 1111 1111 1129` (Visa - Fail)
- **Expiry Date**: Any future date (e.g., `12/28`).
- **Cardholder Name**: Test Buyer.
- **CVV**: `123`.
- Click **Pay** and select **Success** in the mock bank authorization prompt.

---

## 8. How to Verify Transaction Status

Upon completing payment:
1. The checkout widget closes, and the client forwards checkout parameters (`razorpay_order_id`, `razorpay_payment_id`, `razorpay_signature`) to the backend `/api/payment/verify` endpoint.
2. The server verifies the cryptographic signature using the `RAZORPAY_KEY_SECRET`.
3. On successful validation, the transaction state transitions to `SUCCESS` and the page redirects to **Track Order & Fulfillment** (`/orders/:transaction_id`).
4. You can inspect all ledger transactions by clicking **Transactions** in the dashboard navigation sidebar.

---

## 9. How to Verify Webhook Processing

If you are using real webhooks (e.g. via ngrok tunnel), you can verify webhook signature verification:
1. Check the Razorpay Dashboard's webhook delivery logs.
2. View the backend console logs; you will see `[AUDIT] Actor: WEBHOOK | Action: PROCESS_WEBHOOK | Result: SUCCESS` messages.
3. In the database, check the `processed_webhook_events` table to confirm that webhook event IDs are logged, ensuring idempotency.

---

## 10. How to Verify Audit Logs

Click **Audit Trail** in the frontend sidebar or navigate to `/trust` (Trust Center) to verify:
- `CREATE_PAYMENT` logs representing successful secure order locks.
- `VERIFY_PAYMENT` logs representing valid cryptographic signature checks.
- `PROCESS_WEBHOOK` logs representing webhook processing.

---

## 11. Security Precautions

- **Never Commit Secrets**: Do not add `RAZORPAY_KEY_SECRET` or `RAZORPAY_WEBHOOK_SECRET` to version control. Keep `.env` listed in `.gitignore`.
- **Strict Sandbox**: LLM and AI agents have absolutely zero access to payment credentials or payment SDK adapters.
- **Authoritative Locking**: The transaction amount is always fetched from the database-locked `PurchaseRequest` record. Any tampered frontend payment parameters will result in transaction rejection.
