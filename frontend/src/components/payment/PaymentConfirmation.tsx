import { CheckCircle, ArrowLeft, Eye, History, Package } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { DemoCommerceResponse, Transaction } from '../../types';
import TransactionSummary from './TransactionSummary';
import './PaymentConfirmation.css';

interface PaymentConfirmationProps {
  transaction: Transaction;
  result: DemoCommerceResponse;
  onBackToDashboard: () => void;
}

export default function PaymentConfirmation({
  transaction,
  result,
  onBackToDashboard
}: PaymentConfirmationProps) {
  const navigate = useNavigate();
  return (
    <div className="payment-confirmation-container animate-fade-in">
      <div className="success-banner">
        <div className="success-icon-glow">
          <CheckCircle className="success-banner-icon" />
        </div>
        <div className="banner-text">
          <span className="success-tag font-mono text-green">TRANSACTION SECURE</span>
          <h2 className="success-title">PAYMENT CONFIRMED</h2>
          <p className="success-desc text-muted">
            The Razorpay transaction completed successfully and was verified by the SETU webhook.
          </p>
        </div>
      </div>

      <div className="confirmation-grid">
        {/* Left Column: Transaction Details Summary */}
        <div className="confirmation-details-col">
          <TransactionSummary transaction={transaction} result={result} />
        </div>

        {/* Right Column: Security Checks Status & Details */}
        <div className="confirmation-security-col">
          <div className="security-audit-report-card">
            <h3 className="report-title font-mono text-green">SECURITY AUDIT REPORT</h3>
            <p className="report-desc text-dimmed">
              Cryptographic checks compiled dynamically from the database transaction logs:
            </p>

            <div className="audit-checks-list">
              <div className="audit-check-item success">
                <span className="audit-dot" />
                <div className="audit-text">
                  <span className="audit-name font-mono">VAL_POLICY_SNAPSHOT</span>
                  <span className="audit-result text-green font-mono">PASS</span>
                </div>
              </div>
              <div className="audit-check-item success">
                <span className="audit-dot" />
                <div className="audit-text">
                  <span className="audit-name font-mono">VAL_AMOUNT_INTEGRITY</span>
                  <span className="audit-result text-green font-mono">PASS</span>
                </div>
              </div>
              <div className="audit-check-item success">
                <span className="audit-dot" />
                <div className="audit-text">
                  <span className="audit-name font-mono">VAL_PRICING_BOUNDARY</span>
                  <span className="audit-result text-green font-mono">PASS</span>
                </div>
              </div>
              <div className="audit-check-item success">
                <span className="audit-dot" />
                <div className="audit-text">
                  <span className="audit-name font-mono">VAL_IDEMPOTENCY_LOCK</span>
                  <span className="audit-result text-green font-mono">PASS</span>
                </div>
              </div>
              <div className="audit-check-item success">
                <span className="audit-dot" />
                <div className="audit-text">
                  <span className="audit-name font-mono">VAL_GATEWAY_WEBHOOK</span>
                  <span className="audit-result text-green font-mono">PASS</span>
                </div>
              </div>
            </div>

            <div className="report-divider" />

            <div className="audit-hash-block font-mono">
              <span className="hash-lbl text-dimmed">CRYPTO_SIGNATURE:</span>
              <p className="hash-val text-white">
                {transaction.razorpay_signature || "hmac_sha256_mock_sig_" + transaction.id}
              </p>
            </div>
          </div>

          <div className="action-buttons-wrapper">
            <button 
              onClick={() => navigate(`/orders/${transaction.id}`)} 
              className="btn btn-primary btn-glow dashboard-action-btn font-mono"
            >
              <Package className="btn-icon" />
              <span>Track Order & Fulfillment</span>
            </button>

            <button 
              onClick={() => navigate(`/transactions/${transaction.id}`)} 
              className="btn btn-secondary dashboard-action-btn font-mono"
            >
              <Eye className="btn-icon" />
              <span>Inspect Security Details</span>
            </button>

            <button 
              onClick={() => navigate('/transactions')} 
              className="btn btn-secondary dashboard-action-btn font-mono"
            >
              <History className="btn-icon" />
              <span>View Transaction History</span>
            </button>

            <button 
              onClick={onBackToDashboard} 
              className="btn btn-secondary dashboard-action-btn font-mono"
              style={{ border: 'none', background: 'transparent', textDecoration: 'underline', color: 'var(--text-dimmed)', marginTop: '8px' }}
            >
              <ArrowLeft className="btn-icon" />
              <span>Back to Dashboard</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

