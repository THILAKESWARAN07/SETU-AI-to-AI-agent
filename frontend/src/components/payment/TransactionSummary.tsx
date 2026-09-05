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

  const discountAmount = result.final_amount && result.original_amount 
    ? parseFloat(result.original_amount) - parseFloat(result.final_amount)
    : 0;

  // Retrieve exact accepted proposal snapshot
  const acceptedProposal = result.proposals?.find(p => p.proposal_id === result.accepted_proposal_id);

  // Basket items strictly from accepted proposal snapshot or result.basket
  const basketItems = (acceptedProposal?.basket_items && acceptedProposal.basket_items.length > 0)
    ? acceptedProposal.basket_items
    : (result.basket?.items && result.basket.items.length > 0)
      ? result.basket.items
      : [];

  // Determine proposal type: STANDALONE_COUNTER vs BUNDLE_PROPOSAL
  const proposalType = acceptedProposal?.proposal_type 
    || (result.accepted_proposal_id?.includes('bundle') ? 'BUNDLE_PROPOSAL' : 'STANDALONE_COUNTER');
  const isBundle = proposalType === 'BUNDLE_PROPOSAL' || (basketItems.length > 1 && !result.accepted_proposal_id?.includes('standalone'));

  const sectionHeading = isBundle ? "PURCHASED BUNDLE" : "PURCHASED ITEM";
  const primaryItem = basketItems.find((item: any) => item.is_primary) || basketItems[0];
  const displayName = isBundle
    ? (result.bundle_offer?.name || "SoundWave Bundle Pack")
    : (primaryItem?.name || "Wireless Earbuds Pro");

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
        {/* Item or Bundle Details */}
        <div className="summary-section bundle-details">
          <h4 className="section-label">{sectionHeading}</h4>
          <p className="bundle-title text-main">{displayName}</p>
          <ul className="bundle-items font-mono">
            {basketItems.length > 0 ? (
              basketItems.map((item: any, idx: number) => (
                <li key={idx}>
                  • {item.name || `Item (ID: ${item.product_id})`} (Catalog ID: {item.product_id})
                  {item.quantity > 1 ? ` × ${item.quantity}` : ''}
                </li>
              ))
            ) : (
              <li>• {displayName} (Catalog ID: {result.selected_product_id || 1})</li>
            )}
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
            {result.accepted_proposal_id && (
              <div className="id-item">
                <span className="id-lbl">ACCEPTED PROPOSAL:</span>
                <span className="id-val text-secondary">{result.accepted_proposal_id}</span>
              </div>
            )}
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
              <span>Negotiated Discount ({parseFloat(result.discount_percent || '0').toFixed(2)}%):</span>
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
