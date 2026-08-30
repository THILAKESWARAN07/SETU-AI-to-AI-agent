import { useNavigate } from 'react-router-dom';
import { Eye, Activity } from 'lucide-react';
import type { AuditEvent } from '../../types';
import './TrustActivity.css';

interface TrustActivityProps {
  auditEvents: AuditEvent[];
  selectedTxId: number | null;
  purchaseRequestId: number | null;
}

export default function TrustActivity({
  auditEvents,
  selectedTxId,
  purchaseRequestId
}: TrustActivityProps) {
  const navigate = useNavigate();

  // 1. Filter events based on active inspection context
  const filteredEvents = auditEvents
    .filter(evt => {
      if (selectedTxId === null) return true; // Show all globally

      // Show only related to this transaction or purchase request
      if (evt.entity_type === 'PurchaseRequest' && evt.entity_id === purchaseRequestId) return true;
      if (evt.entity_type === 'Transaction' && evt.entity_id === selectedTxId) return true;

      const meta = evt.metadata || {};
      if (meta.purchase_request_id === purchaseRequestId) return true;
      if (meta.entity_id === purchaseRequestId) return true;

      return false;
    })
    // Show most recent first
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    // Limit global view to 15 entries
    .slice(0, selectedTxId === null ? 15 : 50);

  const formatTimestamp = (tsStr: string) => {
    let formattedStr = tsStr;
    if (formattedStr && !formattedStr.includes('Z') && !formattedStr.includes('+') && !formattedStr.match(/-\d{2}:\d{2}$/)) {
      formattedStr = formattedStr + 'Z';
    }
    const d = new Date(formattedStr);
    return d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  const formatDate = (tsStr: string) => {
    let formattedStr = tsStr;
    if (formattedStr && !formattedStr.includes('Z') && !formattedStr.includes('+') && !formattedStr.match(/-\d{2}:\d{2}$/)) {
      formattedStr = formattedStr + 'Z';
    }
    const d = new Date(formattedStr);
    return d.toLocaleDateString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short'
    });
  };

  return (
    <div className="trust-activity-container animate-fade-in">
      <div className="activity-hdr-bar font-mono">
        <span className="text-secondary">SYSTEM LOG ACTIVITY FEED</span>
        <span className="text-dimmed">LIMIT: {selectedTxId === null ? '15 RECENT' : 'ALL SESSION EVENTS'}</span>
      </div>

      {filteredEvents.length === 0 ? (
        <div className="activity-empty font-mono text-dimmed">
          <Activity className="empty-act-ico animate-pulse" />
          <span>No system activity recorded in database logs.</span>
        </div>
      ) : (
        <div className="activity-table-wrapper">
          <table className="activity-table">
            <thead>
              <tr className="font-mono text-dimmed">
                <th>DATE</th>
                <th>TIME</th>
                <th>ACTOR</th>
                <th>ACTION</th>
                <th>RESULT</th>
                <th>REASON / DETAILS</th>
                <th className="act-hdr-cell">LINK</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((evt) => {
                const isSuccess = evt.result === 'SUCCESS' || evt.result === 'APPROVED' || evt.result === 'PAID';
                const isBlocked = evt.result === 'BLOCKED' || evt.result === 'FAIL' || evt.result === 'ERROR';

                let resultClass = 'status-tag font-mono';
                if (isSuccess) resultClass += ' success';
                else if (isBlocked) resultClass += ' blocked';
                else resultClass += ' pending';

                // Reconstruct related transaction ID for inspection linking
                let linkId = evt.entity_type === 'Transaction' ? evt.entity_id : null;
                if (!linkId && evt.metadata) {
                  linkId = evt.metadata.transaction_id || null;
                }

                return (
                  <tr key={evt.id} className="activity-row">
                    <td className="font-mono text-white">{formatDate(evt.timestamp)}</td>
                    <td className="font-mono text-dimmed">{formatTimestamp(evt.timestamp)}</td>
                    <td className="font-mono font-bold text-muted">{evt.actor}</td>
                    <td className="font-mono text-secondary">{evt.action}</td>
                    <td>
                      <span className={resultClass}>{evt.result}</span>
                    </td>
                    <td className="activity-detail-cell text-muted font-mono">{evt.reason}</td>
                    <td className="act-cell-btn">
                      {linkId ? (
                        <button
                          onClick={() => navigate(`/transactions/${linkId}`)}
                          className="btn btn-secondary act-btn-inspect font-mono"
                          title="Inspect Transaction"
                        >
                          <Eye className="btn-icon" />
                          <span>VIEW</span>
                        </button>
                      ) : (
                        <span className="text-dimmed font-mono">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
