import { User, Store, Target, Cpu, CheckCircle } from 'lucide-react';
import './NegotiationParticipants.css';

interface NegotiationParticipantsProps {
  finalAmount: string;
  agentMode?: string;
  buyerObjective?: string;
  buyerToolsUsed?: string[];
  buyerConfidence?: number;
  merchantObjective?: string;
  merchantToolsUsed?: string[];
  merchantConfidence?: number;
  decision?: string;
}

export default function NegotiationParticipants({
  finalAmount,
  buyerObjective,
  buyerToolsUsed,
  buyerConfidence,
  merchantObjective,
  merchantToolsUsed,
  merchantConfidence,
  decision
}: NegotiationParticipantsProps) {
  const isApproved = decision === 'APPROVED';
  const isBlocked = decision === 'BLOCKED';

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
              <p className="metric-value">{buyerObjective || "Optimize bundle pricing & enforce budget limits"}</p>
            </div>
          </div>
          <div className="metric-row">
            <Cpu className="metric-icon" />
            <div>
              <span className="metric-label">TOOLS USED</span>
              <p className="metric-value" style={{ textTransform: 'none', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                {buyerToolsUsed && buyerToolsUsed.length > 0 
                  ? buyerToolsUsed.join(', ') 
                  : 'search_catalog, get_product_details, evaluate_budget'}
              </p>
            </div>
          </div>
          <div className="metric-row">
            <CheckCircle className="metric-icon" />
            <div>
              <span className="metric-label">CONFIDENCE & DECISION</span>
              <p className="metric-value">
                {((buyerConfidence ?? 1.0) * 100).toFixed(0)}% Confidence | {isApproved ? 'AGREED' : isBlocked ? 'FAILED' : 'ACTIVE'}
              </p>
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
              <p className="metric-value">{merchantObjective || "Maximize sales margins & bundle volume conversion"}</p>
            </div>
          </div>
          <div className="metric-row">
            <Cpu className="metric-icon" />
            <div>
              <span className="metric-label">TOOLS USED</span>
              <p className="metric-value" style={{ textTransform: 'none', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                {merchantToolsUsed && merchantToolsUsed.length > 0 
                  ? merchantToolsUsed.join(', ') 
                  : 'get_inventory, get_product_price, evaluate_margin'}
              </p>
            </div>
          </div>
          <div className="metric-row">
            <CheckCircle className="metric-icon" />
            <div>
              <span className="metric-label">CONFIDENCE & DECISION</span>
              <p className="metric-value">
                {((merchantConfidence ?? 1.0) * 100).toFixed(0)}% Confidence | {isApproved ? 'AGREED' : isBlocked ? 'FAILED' : 'ACTIVE'}
              </p>
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
