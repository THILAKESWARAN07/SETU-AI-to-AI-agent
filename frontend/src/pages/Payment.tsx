import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  ShieldAlert, 
  Lock, 
  Loader2, 
  AlertTriangle,
  RefreshCw
} from 'lucide-react';
import TransactionStatus from '../components/payment/TransactionStatus';
import PaymentSecurity from '../components/payment/PaymentSecurity';
import { apiService } from '../services/api';
import type { DemoCommerceResponse, Transaction } from '../types';
import './Payment.css';

export default function Payment() {
  const navigate = useNavigate();
  const location = useLocation();
  const result = location.state?.result as DemoCommerceResponse | undefined;

  const [isSecuring, setIsSecuring] = useState(false);
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const paymentCalled = useRef(false);

  useEffect(() => {
    // If no purchase request exists or we already initiated, do nothing
    if (!result || paymentCalled.current) return;
    
    // Guard against duplicate execution (especially in Strict Mode)
    paymentCalled.current = true;
    setIsSecuring(true);
    setError(null);

    // Call payment API
    apiService.createPayment(result.purchase_request_id)
      .then((tx) => {
        setTransaction(tx);
        setIsSecuring(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to secure payment channel.');
        setIsSecuring(false);
      });
  }, [result]);

  const handleBack = () => {
    if (transaction) {
      const confirmLeave = window.confirm(
        "Warning: This payment order is locked in the backend database. Leaving this page will close the active gateway checkout session. Do you wish to continue?"
      );
      if (!confirmLeave) return;
    }
    navigate('/negotiation', { state: { result } });
  };

  // If no result is present, render empty state
  if (!result) {
    return (
      <div className="payment-page-container container animate-fade-in">
        <div className="empty-payment-state">
          <ShieldAlert className="empty-state-icon animate-float" />
          <h3>No Active Payment Session Found</h3>
          <p className="empty-state-desc">
            To view the secure payment gateway, you must first describe a purchase intent and complete the AI negotiation.
          </p>
          <button onClick={() => navigate('/shopping')} className="btn btn-primary">
            <ArrowLeft className="btn-icon" />
            <span>Go to Shopping</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="payment-page-container container animate-fade-in">
      {/* Loading Securing State */}
      {isSecuring && (
        <div className="securing-loader-overlay">
          <div className="securing-loader-box">
            <Loader2 className="securing-spinner animate-spin" />
            <h3>SECURING PAYMENT CHANNEL...</h3>
            <p>Locking approved transaction amount against database snapshots...</p>
          </div>
        </div>
      )}

      {/* Error / Blocked State */}
      {error && (
        <div className="payment-error-panel animate-fade-in">
          <AlertTriangle className="error-icon" />
          <h3>PAYMENT REQUEST BLOCKED</h3>
          <p className="error-msg">{error}</p>
          <p className="error-tip">
            SETU security validation rejected this payment request. The final checkout amount must exactly match the approved policy snapshot.
          </p>
          <div className="error-actions">
            <button onClick={() => navigate('/shopping')} className="btn btn-secondary">
              <span>Back to Shopping</span>
            </button>
            <button onClick={() => navigate('/negotiation', { state: { result } })} className="btn btn-primary">
              <RefreshCw className="btn-icon" />
              <span>Retry Validation</span>
            </button>
          </div>
        </div>
      )}

      {/* Transaction Details Layout (Active checkout) */}
      {transaction && !isSecuring && (
        <>
          {/* Header Bar */}
          <div className="payment-header">
            <button onClick={handleBack} className="back-btn">
              <ArrowLeft className="back-icon" />
              <span>Back to Negotiation</span>
            </button>

            <div className="payment-header-title">
              <h2>SETU SECURE PAYMENT GATEWAY</h2>
              <p>Locked Transaction Session Gateway</p>
            </div>

            <div className="payment-header-status">
              <span className="gateway-dot"></span>
              <span>PAYMENT CHANNEL SECURED</span>
            </div>
          </div>

          {/* Main Layout Columns */}
          <div className="payment-grid">
            {/* Left Column: Order Summary & Status */}
            <div className="payment-main-col">
              {/* Order Summary Card */}
              <div className="order-summary-card">
                <h3 className="summary-card-title">Order Summary</h3>
                <div className="summary-product-details">
                  <div className="product-row-detail">
                    <span className="product-lbl">Bundle Pack:</span>
                    <span className="product-val">{result.bundle_offer.name || "SoundWave Bundle"}</span>
                  </div>
                  <div className="product-row-detail sub-row">
                    <span className="product-lbl">• Wireless Earbuds:</span>
                    <span className="product-val">₹1,599.00</span>
                  </div>
                  <div className="product-row-detail sub-row">
                    <span className="product-lbl">• Smart Charging Case:</span>
                    <span className="product-val">₹399.00</span>
                  </div>
                  <div className="product-divider" />
                  <div className="product-row-detail">
                    <span className="product-lbl">Standard Price:</span>
                    <span className="product-val text-dimmed">₹{parseFloat(result.original_amount).toLocaleString('en-IN')}</span>
                  </div>
                  <div className="product-row-detail text-green font-mono">
                    <span className="product-lbl">Negotiated Discount:</span>
                    <span className="product-val">- ₹99.00 ({parseFloat(result.discount_percent).toFixed(2)}%)</span>
                  </div>
                  <div className="product-divider" />
                  <div className="product-row-detail final-total-row">
                    <span className="product-lbl font-white">Final Amount:</span>
                    <span className="product-val highlight-blue">₹{parseFloat(result.final_amount).toLocaleString('en-IN')}</span>
                  </div>
                  <div className="product-row-detail pr-id-row font-mono">
                    <span className="product-lbl">PURCHASE REQUEST ID:</span>
                    <span className="product-val text-white">PR-{result.purchase_request_id}</span>
                  </div>
                </div>
              </div>

              {/* Status Step Flow */}
              <TransactionStatus status={transaction.status} />
            </div>

            {/* Right Column: Order lock Details & security checkpoints */}
            <div className="payment-sidebar-col">
              {/* Order Locked details card */}
              <div className="order-locked-card">
                <div className="locked-badge-row">
                  <span className="locked-badge-dot" />
                  <span>PAYMENT ORDER LOCKED</span>
                </div>
                
                <div className="locked-metric-row">
                  <span className="locked-lbl">RAZORPAY ORDER ID:</span>
                  <p className="locked-val font-mono">{transaction.razorpay_order_id}</p>
                </div>

                <div className="locked-side-pricing">
                  <div className="side-price-item">
                    <span className="locked-lbl">AMOUNT RECORDED</span>
                    <p className="side-price-value text-green">₹{parseFloat(transaction.amount.toString()).toLocaleString('en-IN')}</p>
                  </div>
                  <div className="side-price-item">
                    <span className="locked-lbl">CURRENCY</span>
                    <p className="side-price-value">INR</p>
                  </div>
                </div>

                <div className="locked-divider" />

                <div className="amount-secure-notice">
                  <Lock className="amount-secure-icon" />
                  <span>Amount Snapshot Secured</span>
                </div>
              </div>

              {/* Security checkpoint list */}
              <PaymentSecurity />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
