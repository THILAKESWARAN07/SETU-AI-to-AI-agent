import { 
  ShieldCheck, 
  Plus, 
  ArrowRight, 
  Terminal, 
  BadgeAlert
} from 'lucide-react';
import type { DemoCommerceResponse } from '../../types';
import './CommerceResult.css';

interface CommerceResultProps {
  result: DemoCommerceResponse;
  onNext: () => void;
}

export default function CommerceResult({ result, onNext }: CommerceResultProps) {
  // Find products in results or use placeholders
  const selectedProduct = result.catalog_search_results.find(p => p.id === result.selected_product_id) || {
    name: "Wireless Earbuds",
    price: 1599.00,
    description: "Premium SoundWave wireless earbuds with smart touch controls."
  };

  const crossSellProduct = result.catalog_search_results.find(p => p.id === result.cross_sell_product_id) || {
    name: "Charging Case",
    price: 399.00,
    description: "Protective carrying case with integrated lithium-ion battery backup."
  };

  const discountPercent = parseFloat(result.discount_percent);
  const discountAmount = parseFloat(result.original_amount) - parseFloat(result.final_amount);

  return (
    <div className="commerce-result-wrapper animate-fade-in">
      {/* Visual Trust Status Banner */}
      <div className={`status-banner ${result.decision === 'APPROVED' ? 'status-approved' : 'status-blocked'}`}>
        <div className="status-banner-left">
          {result.decision === 'APPROVED' ? (
            <ShieldCheck className="status-banner-icon success" />
          ) : (
            <BadgeAlert className="status-banner-icon alert" />
          )}
          <div>
            <h3>SYSTEM STATUS: {result.decision === 'APPROVED' ? 'AI NEGOTIATION READY' : 'POLICY BLOCKED'}</h3>
            <p>
              {result.decision === 'APPROVED' 
                ? `Proposal approved under active rules (Policy: ${result.policy_version}).` 
                : `Proposal blocked due to merchant boundary violations.`}
            </p>
          </div>
        </div>
        <div className="status-banner-badge">{result.decision}</div>
      </div>

      <div className="result-grid">
        {/* Selected Product Card */}
        <div className="result-card">
          <span className="card-tag">Base Request</span>
          <div className="card-header">
            <h4>{selectedProduct.name}</h4>
            <span className="product-id">ID: #{result.selected_product_id}</span>
          </div>
          <p className="card-desc">{selectedProduct.description}</p>
          <div className="card-footer">
            <span className="price-label">Original Price</span>
            <span className="price-value">₹{parseFloat(selectedProduct.price.toString()).toLocaleString('en-IN')}</span>
          </div>
        </div>

        {/* Math Plus Joiner */}
        <div className="grid-joiner">
          <Plus className="joiner-icon" />
        </div>

        {/* Cross-Sell Product Card */}
        <div className="result-card">
          <span className="card-tag recomend">Recommended Add-on</span>
          <div className="card-header">
            <h4>{crossSellProduct.name}</h4>
            <span className="product-id">ID: #{result.cross_sell_product_id}</span>
          </div>
          <p className="card-desc">{crossSellProduct.description}</p>
          <div className="card-footer">
            <span className="price-label">Original Price</span>
            <span className="price-value">₹{parseFloat(crossSellProduct.price.toString()).toLocaleString('en-IN')}</span>
          </div>
        </div>

        {/* Math Plus Joiner */}
        <div className="grid-joiner">
          <ArrowRight className="joiner-icon" />
        </div>

        {/* Bundle Offer Card */}
        <div className="result-card highlight-card">
          <span className="card-tag offer">Negotiated Bundle Deal</span>
          <div className="card-header">
            <h4>{result.bundle_offer.name || "SoundWave Bundle"}</h4>
            <span className="product-id highlight-id">PROPOSAL #{result.purchase_request_id}</span>
          </div>
          
          <div className="bundle-breakdown">
            <div className="breakdown-row">
              <span>{selectedProduct.name}</span>
              <span>₹{parseFloat(selectedProduct.price.toString()).toLocaleString('en-IN')}</span>
            </div>
            <div className="breakdown-row">
              <span>{crossSellProduct.name}</span>
              <span>+ ₹{parseFloat(crossSellProduct.price.toString()).toLocaleString('en-IN')}</span>
            </div>
            <div className="breakdown-divider" />
            <div className="breakdown-row">
              <span>Standard Price</span>
              <span>₹{parseFloat(result.original_amount).toLocaleString('en-IN')}</span>
            </div>
            <div className="breakdown-row discount-text">
              <span>Negotiated discount ({discountPercent.toFixed(2)}%)</span>
              <span>- ₹{discountAmount.toLocaleString('en-IN')}</span>
            </div>
          </div>

          <div className="card-footer highlight-footer">
            <span className="price-label highlight-label">Final Net Amount</span>
            <span className="price-value highlight-value">₹{parseFloat(result.final_amount).toLocaleString('en-IN')}</span>
          </div>
        </div>
      </div>

      {/* Structured AI-to-AI Negotiation Logs */}
      <div className="audit-logs-console">
        <div className="console-header">
          <Terminal className="console-icon" />
          <span>AI-TO-AI NEGOTIATION CONSOLE</span>
          <span className="console-status">COMMITTED</span>
        </div>
        <div className="console-body">
          <div className="console-log-row">
            <span className="log-timestamp">[ROUND 1]</span>
            <span className="log-actor buyer">[BUYER_AGENT]</span>
            <span className="log-message">Initiated request. Proposed discount boundary. Bid: ₹1,800.00</span>
          </div>
          <div className="console-log-row">
            <span className="log-timestamp">[ROUND 2]</span>
            <span className="log-actor merchant">[MERCHANT_AGENT]</span>
            <span className="log-message">Bid ₹1,800.00 rejected (exceeds policy discount bounds). Counter-proposed bundle at ₹1,899.00.</span>
          </div>
          <div className="console-log-row">
            <span className="log-timestamp">[ROUND 3]</span>
            <span className="log-actor buyer">[BUYER_AGENT]</span>
            <span className="log-message">Evaluated counter-proposal against budget caps. Accepted contract at ₹1,899.00.</span>
          </div>
          <div className="console-log-row highlight">
            <span className="log-timestamp">[SUCCESS]</span>
            <span className="log-actor system">[SYSTEM]</span>
            <span className="log-message">Contract sealed. Transmitted to Policy Engine. PurchaseRequest ID: {result.purchase_request_id}</span>
          </div>
        </div>
      </div>

      {/* Action Button */}
      <div className="result-actions">
        <button onClick={onNext} className="btn btn-primary btn-glow btn-large">
          <span>Review AI Negotiation</span>
          <ArrowRight className="btn-icon" />
        </button>
      </div>
    </div>
  );
}
