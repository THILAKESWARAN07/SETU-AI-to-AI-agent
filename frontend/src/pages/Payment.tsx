import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  ShieldAlert, 
  Lock, 
  Loader2, 
  AlertTriangle,
  Play
} from 'lucide-react';
import TransactionStatus from '../components/payment/TransactionStatus';
import PaymentSecurity from '../components/payment/PaymentSecurity';
import TransactionSummary from '../components/payment/TransactionSummary';
import PaymentConfirmation from '../components/payment/PaymentConfirmation';
import PaymentResult from '../components/payment/PaymentResult';
import { apiService } from '../services/api';
import type { DemoCommerceResponse, Transaction } from '../types';
import './Payment.css';

// Crypto helper to sign raw payload with HMAC-SHA256
async function signPayload(payload: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const keyData = encoder.encode(secret);
  const messageData = encoder.encode(payload);
  const cryptoKey = await window.crypto.subtle.importKey(
    'raw',
    keyData,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const signatureBuffer = await window.crypto.subtle.sign(
    'HMAC',
    cryptoKey,
    messageData
  );
  return Array.from(new Uint8Array(signatureBuffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

export default function Payment() {
  const navigate = useNavigate();
  const location = useLocation();
  const result = location.state?.result as DemoCommerceResponse | undefined;

  const [isSecuring, setIsSecuring] = useState(false);
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [localStatus, setLocalStatus] = useState<'PENDING' | 'SUCCESS' | 'FAILED'>('PENDING');
  const [error, setError] = useState<string | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  
  const paymentCalled = useRef(false);
  const pollingTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // 1. Create payment transaction on mount
  useEffect(() => {
    if (!result || paymentCalled.current) return;
    
    paymentCalled.current = true;
    setIsSecuring(true);
    setError(null);

    apiService.createPayment(result.purchase_request_id)
      .then((tx) => {
        setTransaction(tx);
        setLocalStatus(tx.status);
        setIsSecuring(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to secure payment channel.');
        setIsSecuring(false);
        setLocalStatus('FAILED');
      });
  }, [result]);

  // 2. Poll transaction status while transaction is PENDING
  useEffect(() => {
    if (!transaction || localStatus !== 'PENDING') {
      if (pollingTimer.current) {
        clearInterval(pollingTimer.current);
        pollingTimer.current = null;
      }
      return;
    }

    const poll = async () => {
      try {
        const txList = await apiService.getTransactions();
        const activeTx = txList.find(tx => tx.razorpay_order_id === transaction.razorpay_order_id);
        if (activeTx) {
          // If transaction status has updated on backend, update frontend state
          if (activeTx.status !== 'PENDING') {
            setTransaction(activeTx);
            setLocalStatus(activeTx.status);
            if (pollingTimer.current) {
              clearInterval(pollingTimer.current);
              pollingTimer.current = null;
            }
          }
        }
      } catch (err) {
        console.error('Polling error:', err);
      }
    };

    // Avoid multiple intervals
    if (!pollingTimer.current) {
      pollingTimer.current = setInterval(poll, 3000);
    }

    return () => {
      if (pollingTimer.current) {
        clearInterval(pollingTimer.current);
        pollingTimer.current = null;
      }
    };
  }, [transaction, localStatus]);

  // 3. Auto-redirect to order details on payment success
  useEffect(() => {
    if (transaction && localStatus === 'SUCCESS') {
      const timer = setTimeout(() => {
        navigate(`/orders/${transaction.id}`);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [transaction, localStatus, navigate]);

  const handleBack = () => {
    if (transaction && localStatus === 'PENDING') {
      const confirmLeave = window.confirm(
        "Warning: This payment order is locked in the backend database. Leaving this page will close the active gateway checkout session. Do you wish to continue?"
      );
      if (!confirmLeave) return;
    }
    navigate('/negotiation', { state: { result } });
  };

  // Webhook Simulator: Payment Success
  const handleSimulateSuccess = async () => {
    if (!transaction || isSimulating) return;

    setIsSimulating(true);
    try {
      const orderId = transaction.razorpay_order_id;
      const amountPaise = Math.round(transaction.amount * 100);
      const eventId = "evt_sim_" + Math.random().toString(36).substring(2, 10);
      const paymentId = "pay_sim_" + Math.random().toString(36).substring(2, 10);

      const payload = {
        entity: "event",
        event: "order.paid",
        id: eventId,
        payload: {
          order: {
            entity: {
              id: orderId,
              amount: amountPaise,
              status: "paid"
            }
          },
          payment: {
            entity: {
              id: paymentId,
              order_id: orderId,
              amount: amountPaise,
              status: "captured"
            }
          }
        }
      };

      const payloadStr = JSON.stringify(payload);
      // Backend defaults to "mockwebhooksecret123" for testing signature validation
      const signature = await signPayload(payloadStr, "mockwebhooksecret123");

      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
      const response = await fetch(`${apiBaseUrl}/api/webhooks/razorpay`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Razorpay-Signature': signature
        },
        body: payloadStr
      });

      if (!response.ok) {
        const errBody = await response.json();
        throw new Error(errBody.detail || 'Webhook validation failed.');
      }
    } catch (err: any) {
      console.error('Simulation success failed:', err);
      setError(err.message || 'Failed to trigger success simulation.');
      setLocalStatus('FAILED');
    } finally {
      setIsSimulating(false);
    }
  };

  // Webhook Simulator: Payment Failure
  const handleSimulateFailure = () => {
    // Stop polling and transition directly to simulated FAILED state
    if (pollingTimer.current) {
      clearInterval(pollingTimer.current);
      pollingTimer.current = null;
    }
    setError('Payment processing was cancelled by the user during the checkout gateway session.');
    setLocalStatus('FAILED');
  };

  // Navigate to shopping
  const handleGoToShopping = () => {
    navigate('/shopping');
  };

  // Navigate to negotiation
  const handleRetryNegotiation = () => {
    navigate('/negotiation', { state: { result } });
  };

  // Navigate to dashboard
  const handleBackToDashboard = () => {
    navigate('/');
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
          <button onClick={handleGoToShopping} className="btn btn-primary">
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

      {/* SUCCESS Screen rendering */}
      {transaction && localStatus === 'SUCCESS' && (
        <PaymentConfirmation 
          transaction={transaction}
          result={result}
          onBackToDashboard={handleBackToDashboard}
        />
      )}

      {/* FAILED Screen rendering */}
      {localStatus === 'FAILED' && (
        <PaymentResult 
          errorMsg={error}
          onRetry={handleRetryNegotiation}
          onGoToShopping={handleGoToShopping}
        />
      )}

      {/* PENDING Screen rendering (Active checkout) */}
      {transaction && localStatus === 'PENDING' && !isSecuring && (
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
              {/* Order Summary Snapshot */}
              <TransactionSummary transaction={transaction} result={result} />

              {/* Status Step Flow */}
              <TransactionStatus status={localStatus} />

              {/* Gateway Webhook simulator card */}
              <div className="gateway-simulator-card animate-fade-in">
                <h3 className="sim-title font-mono">GATEWAY SIMULATOR CONTROLS</h3>
                <p className="sim-desc text-dimmed">
                  SETU is currently running in **Test Mode**. Use these controls to simulate webhook callbacks with correct cryptographic signatures over secure channels.
                </p>

                <div className="sim-actions">
                  <button 
                    onClick={handleSimulateSuccess} 
                    disabled={isSimulating}
                    className="btn btn-primary btn-glow sim-btn-success"
                  >
                    {isSimulating ? (
                      <Loader2 className="btn-icon animate-spin" />
                    ) : (
                      <Play className="btn-icon" />
                    )}
                    <span>Simulate Payment Success</span>
                  </button>
                  <button 
                    onClick={handleSimulateFailure}
                    disabled={isSimulating}
                    className="btn btn-secondary sim-btn-failed"
                  >
                    <AlertTriangle className="btn-icon" />
                    <span>Simulate Payment Failure</span>
                  </button>
                </div>
              </div>
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
                    <p className="side-price-value text-green font-mono">
                      ₹{parseFloat(transaction.amount.toString()).toLocaleString('en-IN')}
                    </p>
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

