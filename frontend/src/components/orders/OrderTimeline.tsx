import { 
  UserCheck, 
  Store, 
  MessageSquare, 
  ShieldCheck, 
  CreditCard, 
  CheckCircle,
  Database,
  ArrowRight,
  Package,
  Truck,
  MapPin,
  AlertCircle
} from 'lucide-react';
import type { AuditEvent } from '../../types';
import './OrderTimeline.css';

interface OrderTimelineProps {
  sessionEvents: AuditEvent[];
}

export default function OrderTimeline({ sessionEvents }: OrderTimelineProps) {
  // Sort session events chronologically
  const sortedEvents = [...sessionEvents].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  const getEventIcon = (action: string) => {
    switch (action) {
      case 'BUYER_INTENT':
        return <UserCheck className="timeline-icon text-secondary" />;
      case 'CATALOG_SEARCH':
        return <Database className="timeline-icon text-dimmed" />;
      case 'PRODUCT_SELECTED':
        return <UserCheck className="timeline-icon text-secondary" />;
      case 'CROSS_SELL_PROPOSED':
        return <Store className="timeline-icon text-secondary" />;
      case 'NEGOTIATION':
        return <MessageSquare className="timeline-icon text-primary" />;
      case 'EVALUATE_POLICY':
        return <ShieldCheck className="timeline-icon text-green" />;
      case 'CREATE_PAYMENT':
        return <CreditCard className="timeline-icon text-orange" />;
      case 'PROCESS_WEBHOOK':
        return <CheckCircle className="timeline-icon text-green" />;
      default:
        return <Database className="timeline-icon text-dimmed" />;
    }
  };

  const formatTimestamp = (tsStr: string) => {
    return new Date(tsStr).toLocaleString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: 'short'
    });
  };

  // Downstream fulfillment states
  const fulfillmentStates = [
    { key: 'ORDER_ACCEPTED', label: 'ORDER ACCEPTED', icon: <Package className="fulfillment-icon" /> },
    { key: 'PROCESSING', label: 'PROCESSING', icon: <Database className="fulfillment-icon" /> },
    { key: 'SHIPPED', label: 'SHIPPED', icon: <Truck className="fulfillment-icon" /> },
    { key: 'DELIVERED', label: 'DELIVERED', icon: <MapPin className="fulfillment-icon" /> }
  ];

  return (
    <div className="order-timeline-container font-mono animate-fade-in">
      <h3 className="timeline-title">TRANSACTION & FULFILLMENT AUDIT TRAIL</h3>
      <p className="timeline-subtitle text-dimmed">
        Cryptographic ledger audit matching negotiation, policy verification, and payment stages:
      </p>

      {/* Audit Logs Section */}
      <div className="timeline-flow">
        {sortedEvents.map((evt) => {
          const isSuccess = evt.result === 'SUCCESS' || evt.result === 'APPROVED' || evt.result === 'PAID';
          const isBlocked = evt.result === 'BLOCKED' || evt.result === 'FAIL' || evt.result === 'ERROR';

          return (
            <div key={evt.id} className="timeline-item">
              <div className="timeline-line" />
              <div className={`timeline-icon-wrapper ${isSuccess ? 'success' : isBlocked ? 'blocked' : 'pending'}`}>
                {getEventIcon(evt.action)}
              </div>
              <div className="timeline-content">
                <div className="timeline-hdr">
                  <div className="actor-action-group">
                    <span className="actor-badge">{evt.actor}</span>
                    <ArrowRight className="hdr-arrow" />
                    <span className="action-name">{evt.action}</span>
                  </div>
                  <span className="event-time text-dimmed">{formatTimestamp(evt.timestamp)}</span>
                </div>
                <p className="event-reason text-main">{evt.reason || 'Event executed successfully.'}</p>
              </div>
            </div>
          );
        })}

        {/* Downstream Fulfillment Lifecycle Section */}
        <div className="fulfillment-section-divider">
          <span className="divider-text">DOWNSTREAM MERCHANT FULFILLMENT</span>
        </div>

        {fulfillmentStates.map((state) => {
          return (
            <div key={state.key} className="timeline-item fulfillment-item unavailable">
              <div className="timeline-line" />
              <div className="timeline-icon-wrapper pending">
                {state.icon}
              </div>
              <div className="timeline-content">
                <div className="timeline-hdr">
                  <span className="fulfillment-name font-bold">{state.label}</span>
                  <span className="status-label-unavailable">
                    <AlertCircle className="inline-icon" />
                    <span>Fulfillment data unavailable</span>
                  </span>
                </div>
                <p className="event-reason text-dimmed">
                  Merchant shipping APIs or fulfillment hooks are not configured for this sandbox environment.
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
