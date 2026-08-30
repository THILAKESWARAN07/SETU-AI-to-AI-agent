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
  
  // Payment mode configuration state
  const [paymentMode, setPaymentMode] = useState<string>('mock');
  const [razorpayKeyId, setRazorpayKeyId] = useState<string>('');
  const [isProcessingRazorpay, setIsProcessingRazorpay] = useState(false);

  const paymentCalled = useRef(false);
  const pollingTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load payment gateway settings
  useEffect(() => {
    apiService.getPaymentConfig()
      .then((cfg) => {
        setPaymentMode(cfg.payment_mode);
        setRazorpayKeyId(cfg.razorpay_key_id);
      })
      .catch((err) => {
        console.error('Failed to retrieve payment configuration:', err);
      });
  }, []);

  // Razorpay Checkout dynamic loader
  const loadRazorpayScript = (): Promise<boolean> => {
    return new Promise((resolve) => {
      if ((window as any).hasOwnProperty('Razorpay')) {
        resolve(true);
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://checkout.razorpay.com/v1/checkout.js';
      script.onload = () => resolve(true);
      script.onerror = () => resolve(false);
      document.body.appendChild(script);
    });
  };

  const handleRazorpayPayment = async () => {
    if (!transaction || !razorpayKeyId) return;

    setIsProcessingRazorpay(true);
    setError(null);

    const loaded = await loadRazorpayScript();
    if (!loaded) {
      setError("Failed to load Razorpay checkout widget script. Please check your internet connection.");
      setIsProcessingRazorpay(false);
      return;
    }

    const options = {
      key: razorpayKeyId,
      amount: Math.round(Number(transaction.amount) * 100),
      currency: "INR",
      name: "SETU AI Commerce",
      description: `Order checkout for Request #${transaction.purchase_request_id}`,
      order_id: transaction.razorpay_order_id,
      prefill: {
        name: "Test Buyer",
        email: "buyer@example.com",
        contact: "9999999999"
      },
      theme: {
        color: "#3b82f6"
      },
      handler: async (response: any) => {
        setIsSecuring(true);
        try {
          const updatedTx = await apiService.verifyPayment({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature
          });
          setTransaction(updatedTx);
          setLocalStatus('SUCCESS');
        } catch (err: any) {
          setError(err instanceof Error ? err.message : 'Razorpay payment signature verification failed.');
          setLocalStatus('FAILED');
        } finally {
          setIsSecuring(false);
          setIsProcessingRazorpay(false);
        }
      },
      modal: {
        ondismiss: () => {
          setIsProcessingRazorpay(false);
          console.log("Razorpay Checkout payment widget modal dismissed.");
        }
      }
    };

    try {
      const rzp = new (window as any).Razorpay(options);
      rzp.open();
    } catch (err: any) {
      setError(`Failed to initialize Razorpay checkout popup: ${err.message || err}`);
      setIsProcessingRazorpay(false);
    }
  };

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

            <div className="payment-header-status" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px', background: 'none', border: 'none', padding: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: 'rgba(34, 197, 94, 0.05)', border: '1px solid rgba(34, 197, 94, 0.15)', padding: '6px 12px', borderRadius: '6px', fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--accent-green)' }}>
                <span className="gateway-dot"></span>
                <span>SECURED</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', padding: '4px 8px', borderRadius: '4px', border: paymentMode === 'razorpay' ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid rgba(156, 163, 175, 0.3)', backgroundColor: paymentMode === 'razorpay' ? 'rgba(59, 130, 246, 0.05)' : 'rgba(156, 163, 175, 0.05)', color: paymentMode === 'razorpay' ? '#3b82f6' : '#9ca3af' }}>
                <span>{paymentMode === 'razorpay' ? 'RAZORPAY TEST MODE' : 'OFFLINE MOCK'}</span>
              </div>
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

              {/* Conditional Payment Gateway Controls */}
              {paymentMode === 'razorpay' ? (
                /* Razorpay Test Mode Card */
                <div className="gateway-simulator-card razorpay-test-mode-card animate-fade-in" style={{ borderStyle: 'solid', borderColor: '#3b82f6' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ width: '8px', height: '8px', backgroundColor: '#3b82f6', borderRadius: '50%', boxShadow: '0 0 8px #3b82f6' }} />
                    <h3 className="sim-title font-mono" style={{ color: '#3b82f6' }}>RAZORPAY TEST MODE ACTIVE</h3>
                  </div>
                  <p className="sim-desc text-dimmed">
                    SETU is currently integrated with **Razorpay Checkout (Test Mode)**. Press checkout below to complete the secure payment flow using Razorpay's checkout widget.
                  </p>

                  <div className="sim-actions" style={{ flexDirection: 'column', gap: '12px' }}>
                    <button 
                      onClick={handleRazorpayPayment} 
                      disabled={isProcessingRazorpay}
                      className="btn btn-primary btn-glow razorpay-pay-btn"
                      style={{ width: '100%', padding: '14px', fontSize: '1rem', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}
                    >
                      {isProcessingRazorpay ? (
                        <Loader2 className="btn-icon animate-spin" />
                      ) : (
                        <Lock className="btn-icon" />
                      )}
                      <span>Pay with Razorpay Test Mode</span>
                    </button>
                    
                    <button 
                      onClick={handleSimulateFailure}
                      className="btn btn-secondary sim-btn-failed"
                      style={{ width: '100%', padding: '12px' }}
                    >
                      <AlertTriangle className="btn-icon" />
                      <span>Cancel Checkout Session</span>
                    </button>
                  </div>
                </div>
              ) : (
                /* Gateway Webhook simulator card */
                <div className="gateway-simulator-card animate-fade-in">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ width: '8px', height: '8px', backgroundColor: 'var(--accent-orange)', borderRadius: '50%', boxShadow: '0 0 8px var(--accent-orange)' }} />
                    <h3 className="sim-title font-mono">OFFLINE MOCK MODE ACTIVE</h3>
                  </div>
                  <p className="sim-desc text-dimmed">
                    SETU is currently running in **Offline Mock Mode**. Use these controls to simulate webhook callbacks with correct cryptographic signatures over secure channels.
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
              )}
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

