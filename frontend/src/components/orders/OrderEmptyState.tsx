import { ShoppingBag, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import './OrderEmptyState.css';

interface OrderEmptyStateProps {
  message?: string;
}

export default function OrderEmptyState({ message }: OrderEmptyStateProps) {
  const navigate = useNavigate();
  return (
    <div className="order-empty-state font-mono animate-fade-in">
      <div className="empty-icon-glow">
        <ShoppingBag className="empty-icon text-secondary" />
      </div>
      <h3>NO ACTIVE ORDERS DETECTED</h3>
      <p className="text-dimmed">
        {message || "No orders are currently recorded in the trust transaction ledger database."}
      </p>
      <button onClick={() => navigate('/shopping')} className="btn btn-primary btn-glow">
        <span>Go to Commerce Gateway</span>
        <ArrowRight className="btn-icon" />
      </button>
    </div>
  );
}
