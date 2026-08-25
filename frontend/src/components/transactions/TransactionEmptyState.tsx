import { FolderOpen, Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import './TransactionEmptyState.css';

interface TransactionEmptyStateProps {
  message?: string;
}

export default function TransactionEmptyState({ message }: TransactionEmptyStateProps) {
  const navigate = useNavigate();

  return (
    <div className="empty-state-card animate-fade-in">
      <div className="empty-icon-glow">
        <FolderOpen className="empty-icon" />
      </div>
      <h3 className="empty-title">No Transaction Records Found</h3>
      <p className="empty-desc text-dimmed">
        {message || 'There are no active transaction or payment records in the database matching your active filters.'}
      </p>
      <button onClick={() => navigate('/shopping')} className="btn btn-primary btn-glow empty-action-btn font-mono">
        <Plus className="btn-icon" />
        <span>Initiate Procurement</span>
      </button>
    </div>
  );
}
