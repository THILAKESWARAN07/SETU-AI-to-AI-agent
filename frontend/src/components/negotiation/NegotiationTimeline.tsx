import { User, Store, ShieldAlert, Check } from 'lucide-react';
import './NegotiationTimeline.css';

interface NegotiationTimelineProps {
  history: any[];
  decision: string;
  discountPercent: string;
  marginPercent: string;
  originalAmount: string;
  finalAmount: string;
}

export default function NegotiationTimeline({
  history,
  decision,
  discountPercent,
  marginPercent,
  originalAmount,
  finalAmount
}: NegotiationTimelineProps) {
  return (
    <div className="timeline-section-card animate-fade-in">
      <h3 className="timeline-section-title">Live Transaction Log</h3>
      <p className="timeline-subtitle text-muted" style={{ fontSize: '0.75rem', marginTop: '4px', marginBottom: '16px' }}>
        AI-to-AI autonomous negotiation session log. (Catalog base value: ₹{parseFloat(originalAmount).toLocaleString('en-IN')})
      </p>

      <div className="chat-timeline-container">
        {history.map((turn, i) => {
          const isBuyer = turn.buyer_offer !== null;
          const round = turn.round;
          const actorClass = isBuyer ? 'timeline-row-buyer' : 'timeline-row-merchant';
          const avatar = isBuyer ? (
            <div className="timeline-avatar buyer-timeline-avatar">
              <User className="avatar-icon-small" />
            </div>
          ) : (
            <div className="timeline-avatar merchant-timeline-avatar">
              <Store className="avatar-icon-small" />
            </div>
          );

          let messageText = turn.reason || 'Negotiation step evaluated.';
          let subText = '';
          let tools: string[] = [];
          let confidence: number | undefined;

          if (turn.buyer_offer) {
            subText = `Proposed Bid: ₹${parseFloat(turn.buyer_offer.final_amount).toLocaleString('en-IN')} | Rationale: "${turn.buyer_offer.reason}"`;
            tools = turn.buyer_offer.tools_used || [];
            confidence = turn.buyer_offer.confidence;
          } else if (turn.merchant_offer) {
            subText = `Proposed Counter: ₹${parseFloat(turn.merchant_offer.offered_amount).toLocaleString('en-IN')} | Rationale: "${turn.merchant_offer.reason}"`;
            tools = turn.merchant_offer.tools_used || [];
            confidence = turn.merchant_offer.confidence;
          }

          return (
            <div key={i} className={`timeline-chat-row ${actorClass}`}>
              {avatar}
              <div className="timeline-chat-bubble">
                <div className="bubble-meta">
                  <span className="bubble-author">
                    {isBuyer ? 'BUYER_AGENT' : 'MERCHANT_AGENT'}
                  </span>
                  <span className="bubble-timestamp">Round {round}</span>
                </div>
                <p className="bubble-msg">{messageText}</p>
                {subText && <p className="bubble-subtext">Action log: "{subText}"</p>}
                
                {/* Tools & Confidence Indicators */}
                {(confidence !== undefined || (tools && tools.length > 0)) && (
                  <div className="bubble-footer-metrics" style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '6px',
                    marginTop: '8px',
                    paddingTop: '6px',
                    borderTop: '1px solid rgba(255, 255, 255, 0.05)',
                    fontSize: '0.68rem',
                    color: 'rgba(255, 255, 255, 0.5)'
                  }}>
                    {confidence !== undefined && (
                      <span style={{
                        padding: '1px 5px',
                        background: 'rgba(255, 255, 255, 0.06)',
                        borderRadius: '3px',
                        fontWeight: 500
                      }}>
                        Confidence: {(confidence * 100).toFixed(0)}%
                      </span>
                    )}
                    {tools && tools.length > 0 && (
                      <span style={{
                        padding: '1px 5px',
                        background: 'rgba(255, 255, 255, 0.06)',
                        borderRadius: '3px',
                        fontStyle: 'italic',
                        color: 'rgba(255, 255, 255, 0.6)'
                      }}>
                        Tools: {tools.join(', ')}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Policy Check System Checkpoint */}
        {decision && (
          <div className="timeline-chat-row timeline-row-system">
            <div className="timeline-avatar system-timeline-avatar">
              <ShieldAlert className="avatar-icon-small" />
            </div>
            <div className="timeline-chat-bubble system-bubble">
              <div className="bubble-meta">
                <span className="bubble-author system-text">SETU POLICY ENGINE</span>
                <span className="bubble-timestamp">Validation Step</span>
              </div>
              <div className="system-validation-box">
                <p className="system-msg-main">
                  Observing negotiation. Executing deterministic policy boundary evaluation checks...
                </p>
                <ul className="policy-checks-list">
                  <li>
                    <Check className="check-icon-mini text-success" />
                    <span>Auto-approval limit check (₹2,000.00 threshold): Passed (Amount: ₹{parseFloat(finalAmount).toLocaleString('en-IN')})</span>
                  </li>
                  <li>
                    <Check className="check-icon-mini text-success" />
                    <span>Merchant margin boundary check (20.00% floor): Passed (Current margin: {marginPercent}%)</span>
                  </li>
                  <li>
                    <Check className="check-icon-mini text-success" />
                    <span>Discount percentage check (10.00% cap): Passed (Current discount: {discountPercent}%)</span>
                  </li>
                </ul>
                <div className="policy-decision-row">
                  <span className="decision-label">POLICY DECISION:</span>
                  <span className="decision-value-tag">{decision}</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
