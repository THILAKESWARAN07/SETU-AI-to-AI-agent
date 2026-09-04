import { ShieldCheck, CreditCard } from 'lucide-react';
import './FinalDealCard.css';

interface FinalDealCardProps {
  originalAmount: string;
  finalAmount: string;
  discountPercent: string;
  decision: string;
  onCheckout: () => void;
  basket?: any;
}

export default function FinalDealCard({
  originalAmount,
  finalAmount,
  discountPercent,
  decision,
  onCheckout,
  basket
}: FinalDealCardProps) {
  const discountVal = parseFloat(originalAmount) - parseFloat(finalAmount);

  const handlePayment = () => {
    if (decision !== 'APPROVED') return;
    onCheckout();
  };

  const primaryItem = basket?.items?.find((i: any) => i.is_primary);
  const dealTitle = primaryItem 
    ? (basket.items.length > 1 ? `${primaryItem.name} + Accessories Bundle` : primaryItem.name)
    : "Negotiated Deal Package";

  return (
    <div className="final-deal-card animate-fade-in">
      <span className="deal-badge">APPROVED OFFER</span>
      <h3 className="deal-title">{dealTitle}</h3>
      
      {basket && basket.items && (
        <div className="negotiated-basket-container" style={{ marginTop: '12px', marginBottom: '15px', border: '1px solid rgba(255,255,255,0.08)', padding: '12px', borderRadius: '6px', background: 'rgba(0,0,0,0.3)' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'monospace', letterSpacing: '1px', marginBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '4px', fontWeight: 'bold' }}>NEGOTIATED BASKET</div>
          {basket.items.map((item: any, idx: number) => {
            const itemOrig = parseFloat(item.original_price) * item.quantity;
            const itemNeg = parseFloat(item.negotiated_price) * item.quantity;
            const itemDisc = itemOrig - itemNeg;
            return (
              <div key={idx} style={{ display: 'flex', flexDirection: 'column', padding: '6px 0', borderBottom: idx < basket.items.length - 1 ? '1px dashed rgba(255,255,255,0.08)' : 'none' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-primary)' }}>
                    {item.name} {item.quantity > 1 ? `x${item.quantity}` : ''}
                    {item.is_primary && <span style={{ fontSize: '9px', marginLeft: '6px', padding: '1px 4px', borderRadius: '3px', background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.25)' }}>PRIMARY</span>}
                  </span>
                  <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontFamily: 'monospace', fontWeight: 'bold' }}>
                    ₹{itemNeg.toLocaleString('en-IN')}
                  </span>
                </div>
                {itemDisc > 0 && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-success)', marginTop: '2px' }}>
                    <span>List Price: ₹{itemOrig.toLocaleString('en-IN')}</span>
                    <span>You Save: ₹{itemDisc.toLocaleString('en-IN')} ({((itemDisc / itemOrig) * 100).toFixed(2)}%)</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="deal-pricing-breakdown">
        <div className="deal-price-row">
          <span className="price-desc">Original Amount:</span>
          <span className="price-val original-crossed">₹{parseFloat(originalAmount).toLocaleString('en-IN')}</span>
        </div>
        <div className="deal-price-row">
          <span className="price-desc font-green">AI Negotiated Discount:</span>
          <span className="price-val font-green">₹{Math.abs(discountVal).toLocaleString('en-IN')} ({parseFloat(discountPercent).toFixed(2)}%)</span>
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
