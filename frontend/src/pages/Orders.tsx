import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Package, Loader2, AlertTriangle, ArrowLeft, Search, Eye, ExternalLink } from 'lucide-react';
import { apiService, ApiError } from '../services/api';
import type { Product, Order, OrderStatus } from '../types';
import OrderEmptyState from '../components/orders/OrderEmptyState';
import OrderStatusComponent from '../components/orders/OrderStatus';
import './Orders.css';

export default function Orders() {
  const navigate = useNavigate();

  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');

  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      apiService.getTransactions(),
      apiService.getAuditTrail(),
      apiService.getCatalog()
    ])
      .then(([txs, logs, catalog]) => {
        // Map transactions to Orders using audit logs and catalog
        const mappedOrders: Order[] = txs.map((tx) => {
          // 1. Get session events
          const sessionEvents = logs.filter(evt => {
            if (evt.entity_type === 'PurchaseRequest' && evt.entity_id === tx.purchase_request_id) return true;
            if (evt.entity_type === 'Transaction' && evt.entity_id === tx.id) return true;
            const meta = evt.metadata || {};
            if (meta.purchase_request_id === tx.purchase_request_id) return true;
            if (meta.entity_id === tx.purchase_request_id) return true;
            if (tx.razorpay_order_id && meta.razorpay_order_id === tx.razorpay_order_id) return true;
            return false;
          });

          // Sort session events chronologically
          const sortedSession = [...sessionEvents].sort(
            (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          );

          // Get policy evaluation time to define pre-checkout boundary
          const policyEvt = sortedSession.find(e => e.action === 'EVALUATE_POLICY');
          const policyTime = policyEvt ? new Date(policyEvt.timestamp).getTime() : 0;

          // Find preceding evaluation/intent logs for this transaction
          const prevPolicy = logs
            .filter(e => e.action === 'EVALUATE_POLICY' && new Date(e.timestamp).getTime() < policyTime)
            .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0];
          const startTime = prevPolicy ? new Date(prevPolicy.timestamp).getTime() : 0;

          const preCheckoutEvents = logs.filter(e => {
            const t = new Date(e.timestamp).getTime();
            return (
              t > startTime &&
              t <= policyTime &&
              ['BUYER_INTENT', 'CATALOG_SEARCH', 'PRODUCT_SELECTED', 'CROSS_SELL_PROPOSED', 'NEGOTIATION'].includes(e.action)
            );
          });

          const fullSessionEvents = [...preCheckoutEvents, ...sessionEvents];

          // 2. Resolve Product
          let resolvedProduct: Product | undefined;
          
          // Try negotiation history
          const negEvent = fullSessionEvents.find(e => e.action === 'NEGOTIATION');
          if (negEvent && negEvent.metadata?.history) {
            const history = negEvent.metadata.history;
            const acceptedRound = history.find((h: any) => h.accepted === true || h.buyer_offer?.product_id);
            const prodId = acceptedRound?.buyer_offer?.product_id || acceptedRound?.merchant_offer?.product_ids?.[0];
            if (prodId) {
              resolvedProduct = catalog.find(p => p.id === prodId);
            }
          }

          // Try product selected event
          if (!resolvedProduct) {
            const selEvent = fullSessionEvents.find(e => e.action === 'PRODUCT_SELECTED');
            if (selEvent && selEvent.metadata?.product) {
              const prodId = selEvent.metadata.product.id;
              if (prodId) {
                resolvedProduct = catalog.find(p => p.id === prodId);
              }
            }
          }

          // Price matching fallback
          if (!resolvedProduct) {
            resolvedProduct = catalog
              .filter(p => p.price >= tx.amount)
              .sort((a, b) => (a.price - tx.amount) - (b.price - tx.amount))[0];
          }

          // Absolute fallback
          const product = resolvedProduct || {
            id: 3,
            name: "Earbuds & Charging Case Bundle",
            price: 1998.00,
            category: "Bundles",
            description: "Discounted bundle including Wireless Earbuds and Charging Case.",
            cost: 1250.00,
            inventory: 20,
            attributes: { brand: "SoundWave" },
            related_product_ids: [],
            active: true
          };

          // 3. Resolve status
          let status: OrderStatus = 'CREATED';
          if (tx.status === 'SUCCESS') status = 'PAID';
          else if (tx.status === 'FAILED') status = 'FAILED';
          else if (tx.status === 'PENDING') status = 'PAYMENT_PENDING';

          // Extract quantity
          const qty = policyEvt?.metadata?.quantity || 1;
          const unitPrice = parseFloat(policyEvt?.metadata?.unit_price || product.price.toString());
          const originalAmount = parseFloat(policyEvt?.metadata?.original_amount || (unitPrice * qty).toString());

          return {
            id: tx.id,
            transactionId: tx.id,
            purchaseRequestId: tx.purchase_request_id,
            razorpayOrderId: tx.razorpay_order_id,
            razorpayPaymentId: tx.razorpay_payment_id,
            amount: tx.amount,
            currency: tx.currency || 'INR',
            status,
            paymentStatus: tx.status,
            createdAt: tx.created_at,
            updatedAt: tx.updated_at,
            merchantName: product.attributes?.brand || 'SoundWave',
            fulfillmentStatus: status,
            items: [
              {
                productId: product.id,
                name: product.name,
                quantity: qty,
                unitPrice,
                originalAmount,
                finalAmount: tx.amount,
                merchantName: product.attributes?.brand || 'SoundWave'
              }
            ],
            timeline: [] // Loaded on demand inside detail page
          };
        });

        setOrders(mappedOrders);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'An unexpected error occurred while loading order information.');
        setLoading(false);
      });
  }, []);

  const formatAmount = (val: number, currency: string) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currency,
      maximumFractionDigits: 2
    }).format(val);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const filteredOrders = orders.filter((order) => {
    // Status Filter
    if (statusFilter !== 'ALL') {
      if (statusFilter === 'PENDING' && order.status !== 'PAYMENT_PENDING') return false;
      if (statusFilter === 'PAID' && order.status !== 'PAID') return false;
      if (statusFilter === 'FAILED' && order.status !== 'FAILED') return false;
    }

    // Search term
    if (searchTerm.trim() !== '') {
      const term = searchTerm.toLowerCase();
      const orderRef = `ord-${order.id.toString().padStart(6, '0')}`;
      const rzpRef = order.razorpayOrderId ? order.razorpayOrderId.toLowerCase() : '';
      const productName = order.items[0]?.name.toLowerCase() || '';

      return (
        orderRef.includes(term) ||
        rzpRef.includes(term) ||
        productName.includes(term)
      );
    }

    return true;
  });

  return (
    <div className="orders-page-container container animate-fade-in">
      {/* Header Bar */}
      <div className="orders-header">
        <button onClick={() => navigate('/')} className="back-btn font-mono">
          <ArrowLeft className="back-icon" />
          <span>Back to Dashboard</span>
        </button>

        <div className="orders-header-title">
          <h2>ORDER & FULFILLMENT CONSOLE</h2>
          <p className="font-mono text-dimmed">Fulfillment Tracking for Autonomous Checkouts</p>
        </div>

        <div className="orders-header-badge font-mono">
          <Package className="badge-icon" />
          <span>ORDER SYSTEM</span>
        </div>
      </div>

      {loading ? (
        <div className="orders-loading-state font-mono">
          <Loader2 className="loading-spinner animate-spin" />
          <h3>RETRIEVING ORDER REGISTRY...</h3>
          <p className="text-dimmed">Scanning transaction records and policy snapshots...</p>
        </div>
      ) : error ? (
        <div className="orders-error-panel font-mono animate-fade-in">
          <AlertTriangle className="error-icon" />
          <h3>ORDER DATABASE ACCESS BLOCKED</h3>
          <p className="error-msg">{error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-primary font-mono">
            <span>Retry Query</span>
          </button>
        </div>
      ) : orders.length === 0 ? (
        <OrderEmptyState />
      ) : (
        <div className="orders-content-grid">
          {/* Filters Card */}
          <div className="orders-filters-card font-mono">
            <div className="filters-header">
              <span>FILTER & SEARCH PIPELINE</span>
            </div>
            <div className="filters-body">
              {/* Search input */}
              <div className="search-input-wrapper">
                <Search className="search-icon" />
                <input 
                  type="text" 
                  placeholder="Search by Order Ref, Razorpay ID, or Product Name..." 
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="search-field"
                />
              </div>

              {/* Status filter tabs */}
              <div className="filter-tabs-wrapper">
                <span className="filter-label text-dimmed">STATUS:</span>
                <div className="filter-tabs">
                  {['ALL', 'PENDING', 'PAID', 'FAILED'].map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setStatusFilter(tab)}
                      className={`filter-tab-btn ${statusFilter === tab ? 'active' : ''}`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Orders list */}
          {filteredOrders.length === 0 ? (
            <OrderEmptyState message={`No order records matched your search filters.`} />
          ) : (
            <div className="orders-list-grid">
              {filteredOrders.map((order) => {
                const item = order.items[0];
                return (
                  <div key={order.id} className="order-summary-row font-mono animate-fade-in">
                    <div className="order-row-meta">
                      <div className="meta-header">
                        <span className="order-ref-title">ORDER REF:</span>
                        <span className="order-ref-value text-white">ORD-{order.id.toString().padStart(6, '0')}</span>
                      </div>
                      <div className="meta-time text-dimmed">
                        {formatDate(order.createdAt)}
                      </div>
                    </div>

                    <div className="order-row-product">
                      <span className="product-title font-bold text-white">{item?.name}</span>
                      <div className="product-detail text-dimmed text-xs">
                        <span>Qty: {item?.quantity}</span>
                        <span className="divider-dot">•</span>
                        <span>Merchant: {order.merchantName}</span>
                      </div>
                    </div>

                    <div className="order-row-pricing">
                      <span className="price-title text-dimmed">AMOUNT PAID:</span>
                      <span className="price-value text-green font-bold">
                        {formatAmount(order.amount, order.currency)}
                      </span>
                    </div>

                    <div className="order-row-status">
                      <OrderStatusComponent status={order.status} />
                    </div>

                    <div className="order-row-actions">
                      <button 
                        onClick={() => navigate(`/orders/${order.id}`)}
                        className="btn btn-secondary action-btn-inspect"
                        title="Track Order & Reconstruct Session"
                      >
                        <Eye className="btn-icon" />
                        <span>Track</span>
                      </button>
                      <button 
                        onClick={() => navigate(`/transactions/${order.transactionId}`)}
                        className="btn btn-secondary action-btn-inspect"
                        title="View Ledger Transaction"
                      >
                        <ExternalLink className="btn-icon" />
                        <span>Ledger</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
