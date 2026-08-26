import { ShieldCheck, ShieldAlert } from 'lucide-react';
import type { AuditEvent } from '../../types';
import './WebhookSecurity.css';

interface WebhookSecurityProps {
  transactionId: number | null;
  razorpayOrderId: string | null;
  auditEvents: AuditEvent[];
}

export default function WebhookSecurity({
  transactionId,
  razorpayOrderId,
  auditEvents
}: WebhookSecurityProps) {
  
  // Find webhook process event
  const webhookEvt = auditEvents.find(evt => {
    if (evt.actor === 'WEBHOOK' && evt.action === 'PROCESS_WEBHOOK') {
      const meta = evt.metadata || {};
      if (meta.entity_id === transactionId) return true;
      if (razorpayOrderId && meta.razorpay_order_id === razorpayOrderId) return true;
    }
    return false;
  });

  const hasFired = webhookEvt !== undefined;
  const isSuccess = webhookEvt?.result === 'SUCCESS';

  return (
    <div className="webhook-security-container animate-fade-in">
      <div className="webhook-hdr-bar font-mono">
        <span className="text-secondary">GATEWAY WEBHOOK SECURE ADAPTER</span>
        <span className="text-dimmed">REPLAY PROTECTION: ACTIVE</span>
      </div>

      <div className="webhook-body-grid">
        {/* Left Side: Security properties list */}
        <div className="webhook-props-panel font-mono">
          <h4 className="props-title text-muted">AUTHENTICATION PROTOCOLS</h4>
          <div className="props-list">
            <div className="prop-row">
              <span className="lbl text-dimmed">HMAC Verification:</span>
              <span className="val text-green font-bold">SHA-256</span>
            </div>
            <div className="prop-row">
              <span className="lbl text-dimmed">Webhook Secret Isolation:</span>
              <span className="val text-green">GATED ON SERVER</span>
            </div>
            <div className="prop-row">
              <span className="lbl text-dimmed">Idempotency Guard:</span>
              <span className="val text-green">DB UNIQUE CONSTRAINT</span>
            </div>
            <div className="prop-row">
              <span className="lbl text-dimmed">Replay Protection:</span>
              <span className="val text-green">EVENT ID TRACKING</span>
            </div>
          </div>
          <p className="props-desc text-dimmed">
            The webhook processor verifies Razorpay raw payload bytes using a HMAC SHA-256 signature key. Fired webhook event IDs are saved in sqlite `processed_webhook_events` to prevent duplicate ledger transactions.
          </p>
        </div>

        {/* Right Side: Webhook event evidence or empty state */}
        <div className="webhook-event-evidence-panel">
          <h4 className="props-title font-mono text-muted">LIVE TRANSACTION FEEDBACK</h4>
          
          {hasFired ? (
            <div className="webhook-evidence-box font-mono animate-fade-in">
              <div className="evidence-status-bar">
                {isSuccess ? <ShieldCheck className="status-ico text-green" /> : <ShieldAlert className="status-ico text-red" />}
                <span className={isSuccess ? "text-green font-bold" : "text-red font-bold"}>
                  {isSuccess ? "HMAC SIGNATURE PASS" : "HMAC SIGNATURE FAIL"}
                </span>
              </div>
              
              <div className="evidence-details">
                <div className="detail-item">
                  <span className="lbl text-dimmed">EVENT ID:</span>
                  <span className="val text-white">{webhookEvt.metadata?.event_id || '—'}</span>
                </div>
                <div className="detail-item">
                  <span className="lbl text-dimmed">ORDER ID:</span>
                  <span className="val text-white">{webhookEvt.metadata?.razorpay_order_id || '—'}</span>
                </div>
                <div className="detail-item">
                  <span className="lbl text-dimmed">PAYMENT ID:</span>
                  <span className="val text-secondary">{webhookEvt.metadata?.razorpay_payment_id || '—'}</span>
                </div>
                <div className="detail-item">
                  <span className="lbl text-dimmed">AMOUNT RECEIVED:</span>
                  <span className="val text-green font-bold">₹{parseFloat(webhookEvt.metadata?.amount || '0').toLocaleString('en-IN')}</span>
                </div>
                <div className="detail-item">
                  <span className="lbl text-dimmed">TIMELOG:</span>
                  <span className="val text-dimmed">{new Date(webhookEvt.timestamp).toLocaleString('en-IN')}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="webhook-evidence-empty font-mono">
              <ShieldAlert className="empty-ico text-dimmed animate-pulse" />
              <span>AWAITING GATEWAY CALLBACK</span>
              <p className="text-dimmed">No webhook events have triggered for this transaction session yet. Webhook checks will verify upon payment completion.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
