import { useNavigate } from 'react-router-dom';
import { Eye, ArrowRight } from 'lucide-react';
import type { Transaction } from '../../types';
import './TransactionList.css';

interface TransactionListProps {
  transactions: Transaction[];
}

export default function TransactionList({ transactions }: TransactionListProps) {
  const navigate = useNavigate();

  const formatINR = (value: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2
    }).format(value);
  };

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="transaction-list-wrapper animate-fade-in">
      {/* Desktop Table view */}
      <div className="transactions-table-container">
        <table className="transactions-table">
          <thead>
            <tr className="font-mono text-dimmed">
              <th>TXN ID</th>
              <th>ORDER ID</th>
              <th>PURCHASE REQ</th>
              <th>AMOUNT</th>
              <th>STATUS</th>
              <th>CREATED AT</th>
              <th className="action-header">ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => (
              <tr key={tx.id} className="transaction-row">
                <td className="font-mono font-white">
                  TXN-{tx.id.toString().padStart(6, '0')}
                </td>
                <td className="font-mono text-muted">
                  {tx.razorpay_order_id || '—'}
                </td>
                <td className="font-mono text-muted">
                  PR-{tx.purchase_request_id}
                </td>
                <td className="font-mono font-bold text-secondary">
                  {formatINR(tx.amount)}
                </td>
                <td>
                  <span className={`status-badge ${tx.status.toLowerCase()}`}>
                    <span className="badge-dot" />
                    <span className="font-mono">{tx.status}</span>
                  </span>
                </td>
                <td className="text-dimmed font-mono">
                  {formatDate(tx.created_at)}
                </td>
                <td className="action-cell">
                  <button
                    onClick={() => navigate(`/transactions/${tx.id}`)}
                    className="btn btn-secondary view-details-btn font-mono"
                  >
                    <Eye className="btn-icon" />
                    <span>VIEW</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile Card list view */}
      <div className="transactions-card-list">
        {transactions.map((tx) => (
          <div key={tx.id} className="transaction-card">
            <div className="card-top-row">
              <span className="card-txn-id font-mono">TXN-{tx.id.toString().padStart(6, '0')}</span>
              <span className={`status-badge ${tx.status.toLowerCase()}`}>
                <span className="badge-dot" />
                <span className="font-mono">{tx.status}</span>
              </span>
            </div>
            
            <div className="card-body-grid font-mono">
              <div className="card-body-item">
                <span className="card-lbl">ORDER ID:</span>
                <span className="card-val text-muted">{tx.razorpay_order_id || '—'}</span>
              </div>
              <div className="card-body-item">
                <span className="card-lbl">PURCHASE REQ:</span>
                <span className="card-val text-muted">PR-{tx.purchase_request_id}</span>
              </div>
              <div className="card-body-item">
                <span className="card-lbl">AMOUNT:</span>
                <span className="card-val text-secondary font-bold">{formatINR(tx.amount)}</span>
              </div>
              <div className="card-body-item">
                <span className="card-lbl">CREATED AT:</span>
                <span className="card-val text-dimmed">{formatDate(tx.created_at)}</span>
              </div>
            </div>

            <div className="card-divider" />

            <button
              onClick={() => navigate(`/transactions/${tx.id}`)}
              className="btn btn-primary card-action-btn font-mono"
            >
              <span>Inspect Security Details</span>
              <ArrowRight className="btn-icon" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
