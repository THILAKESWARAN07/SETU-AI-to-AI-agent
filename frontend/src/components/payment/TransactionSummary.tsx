import { ShieldCheck, Lock, Hash } from 'lucide-react';
import type { DemoCommerceResponse, Transaction } from '../../types';
import './TransactionSummary.css';

interface TransactionSummaryProps {
  transaction: Transaction;
  result: DemoCommerceResponse;
}

export default function TransactionSummary({ transaction, result }: TransactionSummaryProps) {
  // Safe parsing helper for currency
  const formatINR = (value: string | number) => {
    const parsed = typeof value === 'string' ? parseFloat(value) : value;
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2,
    }).format(parsed);
  };

  const discountAmount = parseFloat(result.original_amount) - parseFloat(result.final_amount);
  const bundleName = result.bundle_offer?.name || "SoundWave Bundle Pack";

  return (
    <div className="transaction-summary-card animate-fade-in">
      <div className="card-header-bar">
        <Hash className="card-hdr-icon" />
        <span className="card-hdr-title font-mono text-dimmed">TRANSACTION SNAPSHOT</span>
        <div className="hdr-status-badge">
          <Lock className="badge-lock-icon" />
          <span>LOCKED</span>
        </div>
      </div>

      <div className="summary-body">
        {/* Bundle Description */}
        <div className="summary-section bundle-details">
          <h4 className="section-label">Purchased Bundle</h4>
          <p className="bundle-title text-main">{bundleName}</p>
          <ul className="bundle-items font-mono">
            <li>• Wireless Earbuds (Catalog ID: 1)</li>
            <li>• Smart Charging Case (Catalog ID: 2)</li>
          </ul>
        </div>

        <div className="summary-divider" />

        {/* Database References */}
        <div className="summary-section system-identifiers">
          <h4 className="section-label">Cryptographic References</h4>
          <div className="id-grid font-mono">
            <div className="id-item">
              <span className="id-lbl">PURCHASE REQ ID:</span>
              <span className="id-val text-white">PR-{result.purchase_request_id}</span>
            </div>
            <div className="id-item">
              <span className="id-lbl">RAZORPAY ORDER ID:</span>
              <span className="id-val text-white">{transaction.razorpay_order_id}</span>
            </div>
            {transaction.razorpay_payment_id && (
              <div className="id-item">
                <span className="id-lbl">RAZORPAY PAYMENT ID:</span>
                <span className="id-val text-secondary">{transaction.razorpay_payment_id}</span>
              </div>
            )}
            <div className="id-item">
              <span className="id-lbl">TRANSACTION ID:</span>
              <span className="id-val text-white">TXN-{transaction.id.toString().padStart(6, '0')}</span>
            </div>
            <div className="id-item">
              <span className="id-lbl">POLICY ENGINE VER:</span>
              <span className="id-val text-dimmed">{result.policy_version || "v1.0.0"}</span>
            </div>
          </div>
        </div>

        <div className="summary-divider" />

        {/* Financial Details */}
        <div className="summary-section pricing-details">
          <h4 className="section-label">Financial Breakdown</h4>
          <div className="pricing-table">
            <div className="price-row text-dimmed">
              <span>Catalog Value:</span>
              <span className="font-mono">{formatINR(result.original_amount)}</span>
            </div>
            <div className="price-row text-green font-mono">
              <span>Negotiated Discount ({parseFloat(result.discount_percent).toFixed(2)}%):</span>
              <span>- {formatINR(discountAmount)}</span>
            </div>
            <div className="summary-subdivider" />
            <div className="price-row final-price text-main">
              <span>Net Transaction Amount:</span>
              <span className="highlight-amount font-mono">{formatINR(transaction.amount)}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="card-footer-notice">
        <ShieldCheck className="footer-check-icon text-green" />
        <span className="font-mono text-dimmed">Authoritative values verified by Policy Engine.</span>
      </div>
    </div>
  );
}
