import { ShieldCheck, CreditCard } from 'lucide-react';
import './FinalDealCard.css';

interface FinalDealCardProps {
  originalAmount: string;
  finalAmount: string;
  discountPercent: string;
  decision: string;
  onCheckout: () => void;
}

export default function FinalDealCard({
  originalAmount,
  finalAmount,
  discountPercent,
  decision,
  onCheckout
}: FinalDealCardProps) {
  const discountVal = parseFloat(originalAmount) - parseFloat(finalAmount);

  const handlePayment = () => {
    if (decision !== 'APPROVED') return;
    onCheckout();
  };

  return (
    <div className="final-deal-card animate-fade-in">
      <span className="deal-badge">APPROVED OFFER</span>
      <h3 className="deal-title">Earbuds + Charging Case Bundle</h3>
      
      <div className="deal-pricing-breakdown">
        <div className="deal-price-row">
          <span className="price-desc">Original Amount:</span>
          <span className="price-val original-crossed">₹{parseFloat(originalAmount).toLocaleString('en-IN')}</span>
        </div>
        <div className="deal-price-row">
          <span className="price-desc font-green">AI Negotiated Discount:</span>
          <span className="price-val font-green">- ₹{discountVal.toLocaleString('en-IN')} ({parseFloat(discountPercent).toFixed(2)}%)</span>
        </div>
        <div className="deal-price-divider" />
        <div className="deal-price-row final-row">
          <span className="price-desc font-white">Final Net Price:</span>
          <span className="price-val highlight-blue">₹{parseFloat(finalAmount).toLocaleString('en-IN')}</span>
        </div>
      </div>

      <div className="deal-policy-ver">
        <ShieldCheck className="ver-icon" />
        <span>Policy validation verified</span>
      </div>

      <button 
        onClick={handlePayment} 
        disabled={decision !== 'APPROVED'} 
        className="btn btn-primary btn-glow deal-checkout-btn"
      >
        <CreditCard className="btn-icon" />
        <span>Proceed to Secure Payment</span>
      </button>
    </div>
  );
}
