import { 
  UserCheck, 
  Store, 
  MessageSquare, 
  ShieldAlert, 
  CreditCard, 
  CheckCircle,
  Database,
  ArrowRight
} from 'lucide-react';
import type { AuditEvent } from '../../types';
import './TransactionAuditTrail.css';

interface TransactionAuditTrailProps {
  purchaseRequestId: number;
  transactionId: number;
  razorpayOrderId: string | null;
  auditEvents: AuditEvent[];
}

export default function TransactionAuditTrail({
  purchaseRequestId,
  transactionId,
  razorpayOrderId,
  auditEvents
}: TransactionAuditTrailProps) {
  
  // 1. Filter events related to this transaction or purchase request
  const filteredEvents = auditEvents
    .filter(evt => {
      // Direct entity matches
      if (evt.entity_type === 'PurchaseRequest' && evt.entity_id === purchaseRequestId) return true;
      if (evt.entity_type === 'Transaction' && evt.entity_id === transactionId) return true;
      
      // Match inside metadata
      const meta = evt.metadata || {};
      if (meta.purchase_request_id === purchaseRequestId) return true;
      if (meta.entity_id === purchaseRequestId) return true;
      if (razorpayOrderId && meta.razorpay_order_id === razorpayOrderId) return true;

      return false;
    })
    // Sort in chronological order (oldest to newest)
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  // Helper to map actor/action to icons
  const getEventIcon = (actor: string, action: string) => {
    const actorUpper = actor.toUpperCase();
    const actionUpper = action.toUpperCase();

    if (actorUpper === 'BUYER_AGENT') {
      if (actionUpper === 'BUYER_INTENT') return <UserCheck className="timeline-icon text-secondary" />;
      return <UserCheck className="timeline-icon text-muted" />;
    }
    if (actorUpper === 'MERCHANT_AGENT') {
      return <Store className="timeline-icon text-secondary" />;
    }
    if (actionUpper === 'NEGOTIATION') {
      return <MessageSquare className="timeline-icon text-primary" />;
    }
    if (actionUpper === 'EVALUATE_POLICY') {
      return <ShieldAlert className="timeline-icon text-orange" />;
    }
    if (actionUpper === 'CREATE_PAYMENT') {
      return <CreditCard className="timeline-icon text-orange" />;
    }
    if (actorUpper === 'WEBHOOK' || actionUpper === 'PROCESS_WEBHOOK') {
      return <CheckCircle className="timeline-icon text-green" />;
    }
    return <Database className="timeline-icon text-dimmed" />;
  };

  const formatTimestamp = (tsStr: string) => {
    const d = new Date(tsStr);
    return d.toLocaleString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    });
  };

  return (
    <div className="audit-trail-container animate-fade-in">
      <h3 className="timeline-title font-mono">CRYPTOGRAPHIC TIMELINE AUDIT</h3>
      <p className="timeline-subtitle text-dimmed">
        Authoritative transaction events signed and compiled by the SETU trust layer:
      </p>

      {filteredEvents.length === 0 ? (
        <div className="timeline-empty font-mono text-dimmed">
          No audit logs recorded for this transaction.
        </div>
      ) : (
        <div className="timeline-flow">
          {filteredEvents.map((evt, idx) => {
            const isSuccess = evt.result === 'SUCCESS' || evt.result === 'APPROVED' || evt.result === 'PAID';
            const isBlocked = evt.result === 'BLOCKED' || evt.result === 'FAIL' || evt.result === 'ERROR';

            let resultClass = 'result-lbl font-mono';
            if (isSuccess) resultClass += ' text-green';
            else if (isBlocked) resultClass += ' text-red';
            else resultClass += ' text-orange';

            return (
              <div key={evt.id} className="timeline-item animate-fade-in">
                {/* Timeline connector line */}
                {idx < filteredEvents.length - 1 && <div className="timeline-line" />}
                
                {/* Icon wrapper */}
                <div className={`timeline-icon-wrapper ${isSuccess ? 'success' : isBlocked ? 'blocked' : 'pending'}`}>
                  {getEventIcon(evt.actor, evt.action)}
                </div>

                {/* Content Box */}
                <div className="timeline-content">
                  <div className="timeline-hdr">
                    <div className="actor-action-group">
                      <span className="actor-badge font-mono">{evt.actor}</span>
                      <ArrowRight className="hdr-arrow" />
                      <span className="action-name font-mono">{evt.action}</span>
                    </div>
                    <span className="event-time font-mono text-dimmed">
                      {formatTimestamp(evt.timestamp)}
                    </span>
                  </div>

                  <div className="timeline-body font-mono">
                    <p className="event-reason text-main">{evt.reason || 'No description recorded.'}</p>
                    
                    <div className="event-metrics">
                      <div className="metric-row">
                        <span className="metric-lbl">RESULT:</span>
                        <span className={resultClass}>{evt.result}</span>
                      </div>

                      {/* Display metadata if present */}
                      {evt.metadata && Object.keys(evt.metadata).length > 0 && (
                        <div className="metadata-box">
                          <span className="metadata-hdr">EVENT METADATA:</span>
                          <pre className="metadata-json">
                            {JSON.stringify(evt.metadata, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
