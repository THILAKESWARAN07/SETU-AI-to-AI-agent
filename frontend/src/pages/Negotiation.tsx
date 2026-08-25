import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Layers } from 'lucide-react';
import NegotiationHeader from '../components/negotiation/NegotiationHeader';
import NegotiationParticipants from '../components/negotiation/NegotiationParticipants';
import NegotiationTimeline from '../components/negotiation/NegotiationTimeline';
import NegotiationState from '../components/negotiation/NegotiationState';
import PolicyEnginePanel from '../components/negotiation/PolicyEnginePanel';
import TrustPanel from '../components/negotiation/TrustPanel';
import NegotiationConsole from '../components/negotiation/NegotiationConsole';
import FinalDealCard from '../components/negotiation/FinalDealCard';
import type { DemoCommerceResponse } from '../types';
import './Negotiation.css';

export default function Negotiation() {
  const navigate = useNavigate();
  const location = useLocation();
  const result = location.state?.result as DemoCommerceResponse | undefined;

  // If no result is present, render empty state
  if (!result) {
    return (
      <div className="negotiation-page-container container animate-fade-in">
        <div className="empty-negotiation-state">
          <Layers className="empty-state-icon animate-float" />
          <h3>No Active Negotiation Session Found</h3>
          <p className="empty-state-desc">
            To view the AI negotiation flow, you must first describe a purchase intent and search the catalog.
          </p>
          <button onClick={() => navigate('/shopping')} className="btn btn-primary">
            <ArrowLeft className="btn-icon" />
            <span>Go to Shopping</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="negotiation-page-container container animate-fade-in">
      {/* Header Back Link */}
      <div className="negotiation-page-header">
        <button onClick={() => navigate('/shopping')} className="back-to-deal-btn">
          <ArrowLeft className="back-icon" />
          <span>Back to Shopping</span>
        </button>
        <span className="system-status-tag font-mono">ENFORCING DECIMAL POLICY</span>
      </div>

      {/* Main Content Layout */}
      <div className="negotiation-grid">
        {/* Left Column: Flow, participants, timeline, logs */}
        <div className="negotiation-main-col">
          <NegotiationHeader 
            purchaseRequestId={result.purchase_request_id}
            policyVersion={result.policy_version}
          />

          <NegotiationState decision={result.decision} />

          <NegotiationParticipants 
            finalAmount={result.final_amount}
          />

          <NegotiationTimeline 
            history={result.negotiation_history}
            decision={result.decision}
            discountPercent={result.discount_percent}
            marginPercent={result.margin_percent}
            originalAmount={result.original_amount}
            finalAmount={result.final_amount}
          />

          <PolicyEnginePanel 
            originalAmount={result.original_amount}
            finalAmount={result.final_amount}
            discountPercent={result.discount_percent}
            marginPercent={result.margin_percent}
            policyVersion={result.policy_version}
          />

          <NegotiationConsole 
            purchaseRequestId={result.purchase_request_id}
            decision={result.decision}
          />
        </div>

        {/* Right Column: Checkout deal card, trust gates */}
        <div className="negotiation-sidebar-col">
          <FinalDealCard 
            originalAmount={result.original_amount}
            finalAmount={result.final_amount}
            discountPercent={result.discount_percent}
            decision={result.decision}
            onCheckout={() => navigate('/payment', { state: { result } })}
          />

          <TrustPanel />
        </div>
      </div>
    </div>
  );
}
