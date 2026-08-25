import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { CreditCard, Loader2, AlertTriangle, ArrowLeft } from 'lucide-react';
import { apiService, ApiError } from '../services/api';
import type { Transaction } from '../types';
import TransactionFilters from '../components/transactions/TransactionFilters';
import TransactionList from '../components/transactions/TransactionList';
import TransactionEmptyState from '../components/transactions/TransactionEmptyState';
import './Transactions.css';

export default function Transactions() {
  const navigate = useNavigate();

  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    setLoading(true);
    setError(null);
    
    apiService.getTransactions()
      .then((txs) => {
        setTransactions(txs);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'An unexpected error occurred while loading transaction logs.');
        setLoading(false);
      });
  }, []);

  // Filter logic
  const filteredTransactions = transactions.filter((tx) => {
    // Status Filter
    if (statusFilter !== 'ALL' && tx.status !== statusFilter) {
      return false;
    }

    // Search Term
    if (searchTerm.trim() !== '') {
      const term = searchTerm.toLowerCase();
      const orderId = tx.razorpay_order_id ? tx.razorpay_order_id.toLowerCase() : '';
      const prId = `pr-${tx.purchase_request_id}`;
      const txnId = `txn-${tx.id.toString().padStart(6, '0')}`;
      
      return (
        orderId.includes(term) ||
        prId.includes(term) ||
        txnId.includes(term) ||
        tx.id.toString().includes(term)
      );
    }

    return true;
  });

  return (
    <div className="transactions-page-container container animate-fade-in">
      {/* Header Bar */}
      <div className="transactions-header">
        <button onClick={() => navigate('/')} className="back-btn">
          <ArrowLeft className="back-icon" />
          <span>Back to Dashboard</span>
        </button>

        <div className="transactions-header-title">
          <h2>TRANSACTION ARCHIVE</h2>
          <p>Locked Ledger of AI Procurement Checkouts</p>
        </div>

        <div className="transactions-header-badge font-mono">
          <CreditCard className="badge-icon" />
          <span>LEDGER LOGS</span>
        </div>
      </div>

      {loading ? (
        <div className="transactions-loading-state">
          <Loader2 className="loading-spinner animate-spin" />
          <h3>LOADING TRANSACTION LEDGER...</h3>
          <p className="text-dimmed">Fetching secure snapshot logs from sqlite tables...</p>
        </div>
      ) : error ? (
        <div className="transactions-error-panel animate-fade-in">
          <AlertTriangle className="error-icon" />
          <h3>LEDGER READ BLOCKED</h3>
          <p className="error-msg">{error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-primary font-mono">
            <span>Retry Ledger Fetch</span>
          </button>
        </div>
      ) : (
        <div className="transactions-content-grid">
          {/* Filters card */}
          <TransactionFilters
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            searchTerm={searchTerm}
            setSearchTerm={setSearchTerm}
          />

          {/* List or Empty State */}
          {filteredTransactions.length === 0 ? (
            <TransactionEmptyState 
              message={
                searchTerm.trim() !== ''
                  ? `No transactions matched your search query "${searchTerm}".`
                  : `No transaction records found with status filter "${statusFilter}".`
              }
            />
          ) : (
            <TransactionList transactions={filteredTransactions} />
          )}
        </div>
      )}
    </div>
  );
}
