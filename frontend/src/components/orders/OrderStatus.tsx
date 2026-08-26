import './OrderStatus.css';
import type { OrderStatus as StatusType } from '../../types';

interface OrderStatusProps {
  status: StatusType;
}

export default function OrderStatus({ status }: OrderStatusProps) {
  const getStatusConfig = (s: StatusType) => {
    switch (s) {
      case 'CREATED':
        return { label: 'ORDER CREATED', className: 'status-created' };
      case 'PAYMENT_PENDING':
        return { label: 'PAYMENT PENDING', className: 'status-pending' };
      case 'PAID':
        return { label: 'PAID & CONFIRMED', className: 'status-paid' };
      case 'PROCESSING':
        return { label: 'PROCESSING', className: 'status-processing' };
      case 'SHIPPED':
        return { label: 'SHIPPED', className: 'status-shipped' };
      case 'DELIVERED':
        return { label: 'DELIVERED', className: 'status-delivered' };
      case 'FAILED':
        return { label: 'TRANSACTION FAILED', className: 'status-failed' };
      case 'CANCELLED':
        return { label: 'CANCELLED', className: 'status-cancelled' };
      default:
        return { label: s, className: 'status-unknown' };
    }
  };

  const config = getStatusConfig(status);

  return (
    <div className={`order-status-badge font-mono ${config.className}`}>
      <span className="status-badge-dot"></span>
      <span className="status-badge-label">{config.label}</span>
    </div>
  );
}
