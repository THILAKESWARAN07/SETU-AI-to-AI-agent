import { Activity } from 'lucide-react';
import './NegotiationHeader.css';

interface NegotiationHeaderProps {
  purchaseRequestId: number;
  policyVersion: string;
}

export default function NegotiationHeader({ purchaseRequestId, policyVersion }: NegotiationHeaderProps) {
  return (
    <div className="negotiation-header-panel">
      <div className="header-title-sec">
        <Activity className="header-status-icon animate-pulse-fast" />
        <div>
          <h2>AI NEGOTIATION PANEL</h2>
          <p className="header-subtitle">Buyer Agent ↔ Merchant Agent Coordination</p>
        </div>
      </div>

      <div className="header-meta-sec">
        <div className="meta-badge-status">
          <span className="live-pulse-dot"></span>
          <span className="live-text">NEGOTIATION ACTIVE</span>
        </div>
        <div className="meta-session-id">
          <span className="session-label">SESSION ID:</span>
          <span className="session-value">PR-{purchaseRequestId}</span>
        </div>
        <div className="meta-policy-ver">
          <span className="session-label">POLICY:</span>
          <span className="session-value">{policyVersion}</span>
        </div>
      </div>
    </div>
  );
}
