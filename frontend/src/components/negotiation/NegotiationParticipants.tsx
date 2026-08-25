import { User, Store, Shield, Target } from 'lucide-react';
import './NegotiationParticipants.css';

interface NegotiationParticipantsProps {
  finalAmount: string;
}

export default function NegotiationParticipants({ finalAmount }: NegotiationParticipantsProps) {
  return (
    <div className="participants-container">
      {/* Buyer Agent Card */}
      <div className="participant-card buyer-card animate-fade-in">
        <div className="card-top">
          <div className="avatar-wrapper buyer-avatar">
            <User className="avatar-icon" />
          </div>
          <div>
            <h3>BUYER_AGENT</h3>
            <span className="identity-tag">Procurement Proxy</span>
          </div>
        </div>

        <div className="card-metrics">
          <div className="metric-row">
            <Target className="metric-icon" />
            <div>
              <span className="metric-label">OBJECTIVE</span>
              <p className="metric-value">Optimize bundle pricing & enforce budget limits</p>
            </div>
          </div>
          <div className="metric-row">
            <Shield className="metric-icon" />
            <div>
              <span className="metric-label">BUDGET BOUNDARY</span>
              <p className="metric-value">₹2,000.00 Max Limit</p>
            </div>
          </div>
        </div>

        <div className="card-current-state">
          <span className="state-label">CURRENT NEGOTIATED BID</span>
          <p className="state-value buyer-glow">₹{parseFloat(finalAmount).toLocaleString('en-IN')}</p>
        </div>
      </div>

      {/* Merchant Agent Card */}
      <div className="participant-card merchant-card animate-fade-in">
        <div className="card-top">
          <div className="avatar-wrapper merchant-avatar">
            <Store className="avatar-icon" />
          </div>
          <div>
            <h3>MERCHANT_AGENT</h3>
            <span className="identity-tag">Inventory Sales Representative</span>
          </div>
        </div>

        <div className="card-metrics">
          <div className="metric-row">
            <Target className="metric-icon" />
            <div>
              <span className="metric-label">OBJECTIVE</span>
              <p className="metric-value">Maximize sales margins & bundle volume conversion</p>
            </div>
          </div>
          <div className="metric-row">
            <Shield className="metric-icon" />
            <div>
              <span className="metric-label">PRICING GUIDELINE</span>
              <p className="metric-value">Max Discount: 10% / Min Margin: 20%</p>
            </div>
          </div>
        </div>

        <div className="card-current-state">
          <span className="state-label">CURRENT COUNTER-OFFER</span>
          <p className="state-value merchant-glow">₹{parseFloat(finalAmount).toLocaleString('en-IN')}</p>
        </div>
      </div>
    </div>
  );
}
