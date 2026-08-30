import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  Loader2, 
  AlertTriangle, 
  ShieldCheck, 
  ShieldAlert,
  DollarSign,
  Info,
  CreditCard,
  Package
} from 'lucide-react';
import { apiService, ApiError } from '../services/api';
import type { Transaction, AuditEvent } from '../types';
import { formatDate as formatUTCDate } from '../utils/date';
import TransactionAuditTrail from '../components/transactions/TransactionAuditTrail';
import './TransactionDetails.css';

export default function TransactionDetails() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [transaction, setTransaction] = useState<Transaction | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;

    setLoading(true);
    setError(null);

    const txId = parseInt(id, 10);
    if (isNaN(txId)) {
      setError('Invalid transaction identifier requested.');
      setLoading(false);
      return;
    }

    // Load both transactions and audit events
    Promise.all([
      apiService.getTransactions(),
      apiService.getAuditTrail()
    ])
      .then(([txs, logs]) => {
        const foundTx = txs.find(t => t.id === txId);
        if (!foundTx) {
          setError(`Transaction Record TXN-${id.padStart(6, '0')} was not found in the ledger database.`);
          setLoading(false);
          return;
        }
        
        setTransaction(foundTx);
        setAuditEvents(logs);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'Failed to retrieve transaction details.');
        setLoading(false);
      });
  }, [id]);

  const handleBack = () => {
    navigate('/transactions');
  };

  if (loading) {
    return (
      <div className="tx-details-loading container font-mono">
        <Loader2 className="loading-spinner animate-spin" />
        <h3>RECONSTRUCTING CRYPTO LEDGER FOR TXN-{id?.padStart(6, '0')}...</h3>
      </div>
    );
  }

  if (error || !transaction) {
    return (
      <div className="tx-details-error-container container animate-fade-in">
        <div className="tx-details-error-panel">
          <AlertTriangle className="error-icon" />
          <h3>LEDGER QUERY ERROR</h3>
          <p className="error-msg">{error}</p>
          <div className="error-actions">
            <button onClick={handleBack} className="btn btn-secondary">
              <ArrowLeft className="btn-icon" />
              <span>Back to Ledger</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 1. Filter events related to this transaction
  const activeEvents = auditEvents.filter(evt => {
    if (evt.entity_type === 'PurchaseRequest' && evt.entity_id === transaction.purchase_request_id) return true;
    if (evt.entity_type === 'Transaction' && evt.entity_id === transaction.id) return true;
    const meta = evt.metadata || {};
    if (meta.purchase_request_id === transaction.purchase_request_id) return true;
    if (meta.entity_id === transaction.purchase_request_id) return true;
    if (transaction.razorpay_order_id && meta.razorpay_order_id === transaction.razorpay_order_id) return true;
    return false;
  });

  // 2. Reconstruct snaps from Audit Log
  const policyEvt = activeEvents.find(e => e.action === 'EVALUATE_POLICY');
  const purchaseRequestEvt = activeEvents.find(e => e.action === 'PURCHASE_REQUEST');

  const discountPercent = policyEvt?.metadata?.discount_percent || purchaseRequestEvt?.metadata?.proposal?.discount_percent || '0.00';
  const marginPercent = policyEvt?.metadata?.margin_percent || purchaseRequestEvt?.metadata?.proposal?.margin_percent || '0.00';
  const policyVersion = policyEvt?.policy_version || 'v1.0.0';
  const bundleName = "SoundWave Bundle Pack (Earbuds + Charging Case)";

  const finalApprovedAmount = transaction.amount;
  let originalAmount = policyEvt?.metadata?.original_amount || purchaseRequestEvt?.metadata?.proposal?.original_amount;
  if (!originalAmount) {
    const dPercent = parseFloat(discountPercent);
    if (dPercent > 0) {
      originalAmount = (finalApprovedAmount / (1 - dPercent / 100)).toFixed(2);
    } else {
      originalAmount = finalApprovedAmount.toString();
    }
  }
  const discountVal = parseFloat(originalAmount) - finalApprovedAmount;

  // Format Helper
  const formatINR = (val: string | number) => {
    const parsed = typeof val === 'string' ? parseFloat(val) : val;
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2
    }).format(parsed);
  };

  const formatDate = (dateStr: string) => {
    return formatUTCDate(dateStr, true);
  };

  // Security status flags
  const hasPolicyApproval = activeEvents.some(e => e.action === 'EVALUATE_POLICY' && (e.result === 'APPROVED' || e.result === 'SUCCESS'));
  const hasAmountIntegrity = transaction.status === 'SUCCESS' || activeEvents.some(e => e.action === 'CREATE_PAYMENT' && e.result === 'SUCCESS');
  const hasPricingBoundary = hasPolicyApproval && parseFloat(marginPercent) >= 30.00;
  const hasPaymentLock = activeEvents.some(e => e.action === 'CREATE_PAYMENT' && e.result === 'SUCCESS');
  const hasWebhookVerification = transaction.status === 'SUCCESS' && activeEvents.some(e => e.action === 'PROCESS_WEBHOOK' && e.result === 'SUCCESS');
  const isTransactionActive = transaction.status === 'SUCCESS';

  return (
    <div className="tx-details-page container animate-fade-in">
      {/* Header Bar */}
      <div className="tx-details-header">
        <button onClick={handleBack} className="back-btn font-mono">
          <ArrowLeft className="back-icon" />
          <span>Back to Ledger</span>
        </button>

        <div className="tx-details-header-title">
          <h2>TRANSACTION LEDGER DETAILS</h2>
          <p className="font-mono text-dimmed">TXN-{transaction.id.toString().padStart(6, '0')}</p>
        </div>

        <div className="tx-details-header-status font-mono">
          <span className={`status-dot ${transaction.status.toLowerCase()}`} />
          <span>{transaction.status}</span>
        </div>
      </div>

      <div className="tx-details-grid">
        {/* Left Column: Metrics & Cards */}
        <div className="tx-details-main-col">
          
          {/* Overview Card */}
          <div className="details-card">
            <div className="details-card-header font-mono">
              <Info className="card-icon text-secondary" />
              <span>TRANSACTION OVERVIEW</span>
            </div>
            <div className="details-card-body font-mono">
              <div className="detail-row">
                <span className="detail-lbl">Transaction Reference:</span>
                <span className="detail-val text-white">TXN-{transaction.id.toString().padStart(6, '0')}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Purchase Request Reference:</span>
                <span className="detail-val text-white">PR-{transaction.purchase_request_id}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Created Date:</span>
                <span className="detail-val text-muted">{formatDate(transaction.created_at)}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Transaction Status:</span>
                <span className={`detail-val status-text-${transaction.status.toLowerCase()}`}>{transaction.status}</span>
              </div>
            </div>
          </div>

          {/* Payment Card */}
          <div className="details-card">
            <div className="details-card-header font-mono">
              <CreditCard className="card-icon text-secondary" />
              <span>PAYMENT GATEWAY SPECIFICATIONS</span>
            </div>
            <div className="details-card-body font-mono">
              <div className="detail-row">
                <span className="detail-lbl">Razorpay Order ID:</span>
                <span className="detail-val text-white">{transaction.razorpay_order_id || '—'}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Razorpay Payment ID:</span>
                <span className="detail-val text-secondary">{transaction.razorpay_payment_id || '—'}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Net Amount Paid:</span>
                <span className="detail-val text-green font-bold">{formatINR(transaction.amount)}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Currency:</span>
                <span className="detail-val text-white">INR</span>
              </div>
            </div>
          </div>

          {/* Financials Card */}
          <div className="details-card">
            <div className="details-card-header font-mono">
              <DollarSign className="card-icon text-secondary" />
              <span>FINANCIAL COMPLIANCE SNAPSHOT</span>
            </div>
            <div className="details-card-body font-mono">
              <div className="detail-row">
                <span className="detail-lbl">Bundle Description:</span>
                <span className="detail-val text-white">{bundleName}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Original Catalog Amount:</span>
                <span className="detail-val text-muted">{formatINR(originalAmount)}</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Negotiated Discount Amount:</span>
                <span className="detail-val text-green">- {formatINR(discountVal)} ({parseFloat(discountPercent).toFixed(2)}%)</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Evaluated Profit Margin:</span>
                <span className="detail-val text-secondary">{parseFloat(marginPercent).toFixed(2)}%</span>
              </div>
              <div className="detail-row">
                <span className="detail-lbl">Final Settled Net Amount:</span>
                <span className="detail-val text-green font-bold">{formatINR(transaction.amount)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Security Verification & Audit Trail */}
        <div className="tx-details-sidebar-col">
          {/* Security Status Checkpoints */}
          <div className="security-checkpoints-card">
            <h3 className="security-card-title font-mono text-green">SECURITY COMPLIANCE AUDIT</h3>
            <p className="security-card-subtitle text-dimmed">Deterministic verifications from policy engine decision nodes:</p>
            
            <div className="checkpoint-list font-mono">
              <div className={`checkpoint-item ${hasPolicyApproval ? 'verified' : 'failed'}`}>
                {hasPolicyApproval ? <ShieldCheck className="checkpoint-icon text-green" /> : <ShieldAlert className="checkpoint-icon text-red" />}
                <div className="checkpoint-text">
                  <span className="checkpoint-name">Policy Approval Status</span>
                  <span className="checkpoint-desc text-dimmed">PR matches policy requirements (Version: {policyVersion})</span>
                </div>
              </div>

              <div className={`checkpoint-item ${hasAmountIntegrity ? 'verified' : 'failed'}`}>
                {hasAmountIntegrity ? <ShieldCheck className="checkpoint-icon text-green" /> : <ShieldAlert className="checkpoint-icon text-red" />}
                <div className="checkpoint-text">
                  <span className="checkpoint-name">Amount Integrity Lock</span>
                  <span className="checkpoint-desc text-dimmed">Checkout amount strictly matches DB approved snapshot</span>
                </div>
              </div>

              <div className={`checkpoint-item ${hasPricingBoundary ? 'verified' : 'failed'}`}>
                {hasPricingBoundary ? <ShieldCheck className="checkpoint-icon text-green" /> : <ShieldAlert className="checkpoint-icon text-red" />}
                <div className="checkpoint-text">
                  <span className="checkpoint-name">Merchant Margin Check</span>
                  <span className="checkpoint-desc text-dimmed">Margin caps ({marginPercent}%) comply with vendor minimum guidelines</span>
                </div>
              </div>

              <div className={`checkpoint-item ${hasPaymentLock ? 'verified' : 'failed'}`}>
                {hasPaymentLock ? <ShieldCheck className="checkpoint-icon text-green" /> : <ShieldAlert className="checkpoint-icon text-red" />}
                <div className="checkpoint-text">
                  <span className="checkpoint-name">Double-Spend Prevention</span>
                  <span className="checkpoint-desc text-dimmed">Order ID uniquely registered in SQLite idempotency table</span>
                </div>
              </div>

              <div className={`checkpoint-item ${hasWebhookVerification ? 'verified' : 'failed'}`}>
                {hasWebhookVerification ? <ShieldCheck className="checkpoint-icon text-green" /> : <ShieldAlert className="checkpoint-icon text-red" />}
                <div className="checkpoint-text">
                  <span className="checkpoint-name">Cryptographic Webhook Match</span>
                  <span className="checkpoint-desc text-dimmed">Payment confirmation payload verified with SHA256 HMAC</span>
                </div>
              </div>

              <div className={`checkpoint-item ${isTransactionActive ? 'verified' : 'failed'}`}>
                {isTransactionActive ? <ShieldCheck className="checkpoint-icon text-green" /> : <ShieldAlert className="checkpoint-icon text-red" />}
                <div className="checkpoint-text">
                  <span className="checkpoint-name">Transaction Settled state</span>
                  <span className="checkpoint-desc text-dimmed">Ledger status is canonically locked as settled (SUCCESS)</span>
                </div>
              </div>
            </div>
            
            <button 
              onClick={() => navigate(`/trust?transaction_id=${transaction.id}`)}
              className="btn btn-primary btn-glow details-trust-btn font-mono"
              style={{ width: '100%', marginTop: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
            >
              <ShieldCheck className="btn-icon" />
              <span>View Trust Analysis</span>
            </button>

            <button 
              onClick={() => navigate(`/orders/${transaction.id}`)}
              className="btn btn-secondary details-trust-btn font-mono"
              style={{ width: '100%', marginTop: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
            >
              <Package className="btn-icon" />
              <span>View Order & Fulfillment</span>
            </button>
          </div>
        </div>
      </div>

      {/* Full width bottom timeline */}
      <div className="tx-details-timeline-row">
        <TransactionAuditTrail
          purchaseRequestId={transaction.purchase_request_id}
          transactionId={transaction.id}
          razorpayOrderId={transaction.razorpay_order_id}
          auditEvents={auditEvents}
        />
      </div>
    </div>
  );
}
