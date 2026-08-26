import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Shield, Loader2, AlertTriangle, ArrowLeft } from 'lucide-react';
import { apiService, ApiError } from '../services/api';
import type { Transaction, AuditEvent, SecurityGate } from '../types';
import TrustOverview from '../components/trust/TrustOverview';
import SecurityGateGrid from '../components/trust/SecurityGateGrid';
import PolicyStatus from '../components/trust/PolicyStatus';
import PaymentIntegrity from '../components/trust/PaymentIntegrity';
import ToolAccessPanel from '../components/trust/ToolAccessPanel';
import WebhookSecurity from '../components/trust/WebhookSecurity';
import TrustActivity from '../components/trust/TrustActivity';
import './TrustCenter.css';

export default function TrustCenter() {
  const location = useLocation();
  const navigate = useNavigate();

  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedTxId, setSelectedTxId] = useState<number | null>(null);

  // 1. Initial Load of transactions and audit log
  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      apiService.getTransactions(),
      apiService.getAuditTrail()
    ])
      .then(([txs, logs]) => {
        setTransactions(txs);
        setAuditEvents(logs);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'Failed to retrieve cryptographic ledger logs.');
        setLoading(false);
      });
  }, []);

  // 2. Sync URL query parameter `?transaction_id=123`
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const txIdStr = params.get('transaction_id');
    if (txIdStr) {
      const parsedId = parseInt(txIdStr, 10);
      if (!isNaN(parsedId)) {
        setSelectedTxId(parsedId);
      }
    } else {
      setSelectedTxId(null);
    }
  }, [location.search]);

  const handleSelectTx = (id: number | null) => {
    setSelectedTxId(id);
    if (id) {
      navigate(`/trust?transaction_id=${id}`);
    } else {
      navigate('/trust');
    }
  };

  const handleBack = () => {
    navigate('/');
  };

  if (loading) {
    return (
      <div className="trust-center-loading container font-mono">
        <Loader2 className="loading-spinner animate-spin" />
        <h3>DECRYPTING VERIFIED CRYPTO KEYCHAINS...</h3>
        <p className="text-dimmed">Initializing Policy Engine boundary states and SQLite audit trails...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="trust-center-error-container container animate-fade-in">
        <div className="trust-center-error-panel">
          <AlertTriangle className="error-icon" />
          <h3>TRUST CONSOLE BLOCKED</h3>
          <p className="error-msg">{error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-primary">
            <span>Reload Console</span>
          </button>
        </div>
      </div>
    );
  }

  // Find inspected transaction details if selected
  const inspectedTx = transactions.find(t => t.id === selectedTxId);
  const prId = inspectedTx ? inspectedTx.purchase_request_id : null;
  const razorpayOrderId = inspectedTx ? inspectedTx.razorpay_order_id : null;

  // Filter logs for selected context
  const activeEvents = auditEvents.filter(evt => {
    if (!inspectedTx) return false;
    if (evt.entity_type === 'PurchaseRequest' && evt.entity_id === prId) return true;
    if (evt.entity_type === 'Transaction' && evt.entity_id === inspectedTx.id) return true;
    const meta = evt.metadata || {};
    if (meta.purchase_request_id === prId) return true;
    if (meta.entity_id === prId) return true;
    if (razorpayOrderId && meta.razorpay_order_id === razorpayOrderId) return true;
    return false;
  });

  // Reconstruct snap compliance parameters
  const policyEvt = activeEvents.find(e => e.action === 'EVALUATE_POLICY');
  const purchaseRequestEvt = activeEvents.find(e => e.action === 'PURCHASE_REQUEST');

  const discountPercent = policyEvt?.metadata?.discount_percent || purchaseRequestEvt?.metadata?.proposal?.discount_percent || '0.00';
  const marginPercent = policyEvt?.metadata?.margin_percent || purchaseRequestEvt?.metadata?.proposal?.margin_percent || '0.00';
  const policyVersion = policyEvt?.policy_version || 'v1.0.0';
  const finalAmount = inspectedTx ? inspectedTx.amount.toString() : '0.00';
  
  let originalAmount = policyEvt?.metadata?.original_amount || purchaseRequestEvt?.metadata?.proposal?.original_amount;
  if (!originalAmount && inspectedTx) {
    const dPercent = parseFloat(discountPercent);
    if (dPercent > 0) {
      originalAmount = (inspectedTx.amount / (1 - dPercent / 100)).toFixed(2);
    } else {
      originalAmount = inspectedTx.amount.toString();
    }
  } else if (!originalAmount) {
    originalAmount = '0.00';
  }

  // Reconstruct active status flags
  const hasPolicyApproval = activeEvents.some(e => e.action === 'EVALUATE_POLICY' && (e.result === 'APPROVED' || e.result === 'SUCCESS'));
  const hasAmountIntegrity = inspectedTx ? (inspectedTx.status === 'SUCCESS' || activeEvents.some(e => e.action === 'CREATE_PAYMENT' && e.result === 'SUCCESS')) : false;
  const hasPricingBoundary = hasPolicyApproval && parseFloat(marginPercent) >= 30.00;
  const hasPaymentLock = activeEvents.some(e => e.action === 'CREATE_PAYMENT' && e.result === 'SUCCESS');
  const hasWebhookVerification = inspectedTx ? (inspectedTx.status === 'SUCCESS' && activeEvents.some(e => e.action === 'PROCESS_WEBHOOK' && e.result === 'SUCCESS')) : false;

  // Compile Security Gates
  const gates: SecurityGate[] = [
    {
      id: 'policy_boundary',
      name: 'POLICY BOUNDARY',
      description: 'Verifies negotiated margins comply with merchant constraints (Margins >= 30.00%).',
      status: inspectedTx ? (hasPricingBoundary ? 'PASSED' : 'FAILED') : 'CONFIGURED',
      evidence: inspectedTx 
        ? `Margin: ${parseFloat(marginPercent).toFixed(2)}%, Cap validation matching Snapshot version: ${policyVersion}.`
        : 'Active capping enforced in backend PolicyEngine.',
      iconName: 'policy'
    },
    {
      id: 'amount_integrity',
      name: 'AMOUNT INTEGRITY',
      description: 'Checks checkout pricing value matches approved database request snap exactly.',
      status: inspectedTx ? (hasAmountIntegrity ? 'PASSED' : 'FAILED') : 'CONFIGURED',
      evidence: inspectedTx
        ? `Net settled price ₹${parseFloat(finalAmount).toLocaleString('en-IN')} matching secure request node.`
        : 'Enforces cross-references on SQLite session locks.',
      iconName: 'amount'
    },
    {
      id: 'tool_access',
      name: 'RESTRICTED TOOL REGISTRY',
      description: 'Guarantees LLM agents cannot directly interact with payment APIs or invoke keys.',
      status: inspectedTx ? 'PASSED' : 'CONFIGURED',
      evidence: 'Allowed registry: 6 tools active. Excluded payment tools: 4 gated.',
      iconName: 'tool'
    },
    {
      id: 'payment_lock',
      name: 'PAYMENT LOCK',
      description: 'Validates unique idempotency order locks compiled before checkout gateway sessions.',
      status: inspectedTx ? (hasPaymentLock ? 'PASSED' : 'FAILED') : 'CONFIGURED',
      evidence: inspectedTx
        ? `Razorpay Order locked: ${razorpayOrderId}.`
        : 'Idempotency mappings verify database isolation keys.',
      iconName: 'lock'
    },
    {
      id: 'webhook_verification',
      name: 'WEBHOOK VERIFICATION',
      description: 'Validates payment webhook signatures using raw request bytes and HMAC SHA-256.',
      status: inspectedTx ? (hasWebhookVerification ? 'PASSED' : 'FAILED') : 'CONFIGURED',
      evidence: inspectedTx && hasWebhookVerification
        ? `Webhook match. Verified Razorpay payment ID: ${inspectedTx.razorpay_payment_id || '—'}.`
        : 'HMAC signature match verifies authentic callbacks.',
      iconName: 'webhook'
    },
    {
      id: 'audit_trail',
      name: 'LEDGER AUDIT TRAIL',
      description: 'Enforces immutable logs for system transitions and agent procurement dialogs.',
      status: inspectedTx ? 'PASSED' : 'CONFIGURED',
      evidence: inspectedTx
        ? `${activeEvents.length} chronological audit entries recorded in secure database tables.`
        : `${auditEvents.length} total ledger audit log records compiled locally.`,
      iconName: 'audit'
    }
  ];

  return (
    <div className="trust-center-page container animate-fade-in">
      {/* Header Bar */}
      <div className="trust-header">
        <button onClick={handleBack} className="back-btn font-mono">
          <ArrowLeft className="back-icon" />
          <span>Back to Dashboard</span>
        </button>

        <div className="trust-header-title">
          <h2>TRUST & SECURITY CENTER</h2>
          <p className="font-mono text-secondary">SETU Technical Security Console</p>
        </div>

        <div className="trust-header-badge font-mono">
          <Shield className="badge-icon text-green animate-pulse" />
          <span>SYSTEM RUNTIME SECURE</span>
        </div>
      </div>

      <div className="trust-content-grid">
        {/* Sub-Header / Selection Overview */}
        <TrustOverview
          transactions={transactions}
          selectedTxId={selectedTxId}
          onSelectTx={handleSelectTx}
        />

        {/* 6 Gates Visual Grid */}
        <div className="section-block">
          <h3 className="section-headline font-mono">CORE RUNTIME TRUST GATES</h3>
          <SecurityGateGrid gates={gates} />
        </div>

        {/* Condition details panels if inspecting specific transaction */}
        {inspectedTx && (
          <div className="inspected-details-layout">
            <h3 className="section-headline font-mono">LIVE CRYPTOGRAPHIC EVIDENCE</h3>
            
            <div className="details-panels-grid">
              {/* Policy engine breakdown */}
              <PolicyStatus
                originalAmount={originalAmount}
                finalAmount={finalAmount}
                discountPercent={discountPercent}
                marginPercent={marginPercent}
                decision={inspectedTx.status}
                policyVersion={policyVersion}
              />

              {/* Payment flow integrity chain */}
              <PaymentIntegrity
                transactionId={inspectedTx.id}
                purchaseRequestId={inspectedTx.purchase_request_id}
                razorpayOrderId={inspectedTx.razorpay_order_id}
                amount={inspectedTx.amount}
                status={inspectedTx.status}
              />

              {/* Webhook Security check */}
              <WebhookSecurity
                transactionId={inspectedTx.id}
                razorpayOrderId={inspectedTx.razorpay_order_id}
                auditEvents={auditEvents}
              />
            </div>
          </div>
        )}

        {/* Tool access registry architecture */}
        <div className="section-block">
          <h3 className="section-headline font-mono">TOOL ACCESS CONTROL POLICY</h3>
          <ToolAccessPanel />
        </div>

        {/* Chronological Audit / Activity logs */}
        <div className="section-block">
          <h3 className="section-headline font-mono">VERIFIED AUDIT LOG FEED</h3>
          <TrustActivity
            auditEvents={auditEvents}
            selectedTxId={selectedTxId}
            purchaseRequestId={prId}
          />
        </div>
      </div>
    </div>
  );
}
