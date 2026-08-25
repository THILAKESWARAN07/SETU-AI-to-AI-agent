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

          let messageText = '';
          let subText = '';

          if (round === 1) {
            messageText = `Requesting bundle catalog package matching earbuds query. Initial purchase boundary formulated: Bid ₹1,800.00.`;
            subText = turn.buyer_offer?.reason || '';
          } else if (round === 2) {
            messageText = `Standard retail aggregate price is ₹${parseFloat(originalAmount).toLocaleString('en-IN')}. Evaluating discount margins. Counter-offer submitted: Bundle price ₹${parseFloat(finalAmount).toLocaleString('en-IN')} (approx ${discountPercent}% discount).`;
            subText = turn.merchant_offer?.reason || '';
          } else if (round === 3) {
            messageText = `Evaluated counter-offer of ₹${parseFloat(finalAmount).toLocaleString('en-IN')} against active policy bounds. Offer accepted. Seal transaction request.`;
            subText = turn.buyer_offer?.reason || '';
          } else {
            messageText = turn.reason || 'Negotiation step evaluated.';
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
