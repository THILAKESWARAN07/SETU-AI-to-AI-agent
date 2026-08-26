import type { Order } from '../../types';
import OrderStatusComponent from './OrderStatus';
import './OrderSummary.css';

interface OrderSummaryProps {
  order: Order;
}

export default function OrderSummary({ order }: OrderSummaryProps) {
  const formatAmount = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: order.currency,
      maximumFractionDigits: 2
    }).format(val);
  };

  const totalOriginalAmount = order.items.reduce((acc, item) => acc + item.originalAmount, 0);
  const totalDiscount = totalOriginalAmount - order.amount;
  const discountPercent = totalOriginalAmount > 0 ? (totalDiscount / totalOriginalAmount) * 100 : 0;

  return (
    <div className="order-summary-card">
      <div className="summary-card-header font-mono">
        <span>ORDER FINANCIAL COMPLIANCE SUMMARY</span>
      </div>
      <div className="summary-card-body font-mono">
        <div className="summary-row">
          <span className="summary-lbl">Order Status:</span>
          <span className="summary-val">
            <OrderStatusComponent status={order.status} />
          </span>
        </div>
        <div className="summary-row">
          <span className="summary-lbl">Payment Status:</span>
          <span className={`summary-val status-text-${order.paymentStatus.toLowerCase()}`}>
            {order.paymentStatus}
          </span>
        </div>
        <div className="summary-row">
          <span className="summary-lbl">Merchant Brand:</span>
          <span className="summary-val text-white">{order.merchantName}</span>
        </div>
        <div className="summary-divider" />
        <div className="summary-row">
          <span className="summary-lbl">Original Catalog Amount:</span>
          <span className="summary-val text-muted">{formatAmount(totalOriginalAmount)}</span>
        </div>
        {totalDiscount > 0 && (
          <div className="summary-row">
            <span className="summary-lbl">Negotiated Discount:</span>
            <span className="summary-val text-green font-bold">
              - {formatAmount(totalDiscount)} ({discountPercent.toFixed(2)}%)
            </span>
          </div>
        )}
        <div className="summary-row">
          <span className="summary-lbl">Final Settled Paid Amount:</span>
          <span className="summary-val text-green font-bold text-lg">{formatAmount(order.amount)}</span>
        </div>
      </div>
    </div>
  );
}
