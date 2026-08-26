import type { OrderItem } from '../../types';
import './OrderItems.css';

interface OrderItemsProps {
  items: OrderItem[];
  currency: string;
}

export default function OrderItems({ items, currency }: OrderItemsProps) {
  const formatAmount = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currency,
      maximumFractionDigits: 2
    }).format(val);
  };

  return (
    <div className="order-items-container">
      <h3 className="section-title font-mono">PURCHASED PRODUCTS</h3>
      <div className="table-wrapper font-mono">
        <table className="order-items-table">
          <thead>
            <tr>
              <th className="th-product">PRODUCT</th>
              <th className="th-merchant">MERCHANT</th>
              <th className="th-qty">QTY</th>
              <th className="th-price text-right">CATALOG PRICE</th>
              <th className="th-total text-right">NEGOTIATED TOTAL</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => {
              const hasDiscount = item.originalAmount > item.finalAmount;
              return (
                <tr key={idx} className="item-row">
                  <td className="td-product">
                    <span className="product-name text-white font-bold">{item.name}</span>
                    <span className="product-id text-dimmed text-xs block">ID: #{item.productId}</span>
                  </td>
                  <td className="td-merchant text-muted">{item.merchantName}</td>
                  <td className="td-qty text-white">{item.quantity}</td>
                  <td className="td-price text-right text-muted">
                    {formatAmount(item.unitPrice)}
                  </td>
                  <td className="td-total text-right">
                    <span className="final-total text-green font-bold">{formatAmount(item.finalAmount)}</span>
                    {hasDiscount && (
                      <span className="orig-total text-dimmed text-xs block line-through">
                        {formatAmount(item.originalAmount)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
