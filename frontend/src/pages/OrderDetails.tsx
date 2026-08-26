import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  Loader2, 
  AlertTriangle, 
  Info, 
  CreditCard, 
  ShieldAlert, 
  CheckCircle
} from 'lucide-react';
import { apiService, ApiError } from '../services/api';
import type { AuditEvent, Product, Order, OrderStatus } from '../types';
import OrderSummary from '../components/orders/OrderSummary';
import OrderItems from '../components/orders/OrderItems';
import OrderTimeline from '../components/orders/OrderTimeline';
import './OrderDetails.css';

export default function OrderDetails() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [order, setOrder] = useState<Order | null>(null);
  const [sessionEvents, setSessionEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;

    setLoading(true);
    setError(null);

    const orderId = parseInt(id, 10);
    if (isNaN(orderId)) {
      setError('Invalid order identifier requested.');
      setLoading(false);
      return;
    }

    Promise.all([
      apiService.getTransactions(),
      apiService.getAuditTrail(),
      apiService.getCatalog()
    ])
      .then(([txs, logs, catalog]) => {
        const tx = txs.find(t => t.id === orderId);
        if (!tx) {
          setError(`Order Record ORD-${id.padStart(6, '0')} was not found in the transaction registry database.`);
          setLoading(false);
          return;
        }

        // 1. Get session events
        const directEvents = logs.filter(evt => {
          if (evt.entity_type === 'PurchaseRequest' && evt.entity_id === tx.purchase_request_id) return true;
          if (evt.entity_type === 'Transaction' && evt.entity_id === tx.id) return true;
          const meta = evt.metadata || {};
          if (meta.purchase_request_id === tx.purchase_request_id) return true;
          if (meta.entity_id === tx.purchase_request_id) return true;
          if (tx.razorpay_order_id && meta.razorpay_order_id === tx.razorpay_order_id) return true;
          return false;
        });

        // Find evaluate policy time
        const policyEvt = directEvents.find(e => e.action === 'EVALUATE_POLICY');
        const policyTime = policyEvt ? new Date(policyEvt.timestamp).getTime() : 0;

        // Preceding boundaries
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

        const allSessionEvents = [...preCheckoutEvents, ...directEvents];

        // 2. Resolve Product
        let resolvedProduct: Product | undefined;

        // Try negotiation history
        const negEvent = allSessionEvents.find(e => e.action === 'NEGOTIATION');
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
          const selEvent = allSessionEvents.find(e => e.action === 'PRODUCT_SELECTED');
          if (selEvent && selEvent.metadata?.product) {
            const prodId = selEvent.metadata.product.id;
            if (prodId) {
              resolvedProduct = catalog.find(p => p.id === prodId);
            }
          }
        }

        // Price fallback
        if (!resolvedProduct) {
          resolvedProduct = catalog
            .filter(p => p.price >= tx.amount)
            .sort((a, b) => (a.price - tx.amount) - (b.price - tx.amount))[0];
        }

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

        const qty = policyEvt?.metadata?.quantity || 1;
        const unitPrice = parseFloat(policyEvt?.metadata?.unit_price || product.price.toString());
        const originalAmount = parseFloat(policyEvt?.metadata?.original_amount || (unitPrice * qty).toString());

        const orderData: Order = {
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
          timeline: [] // Fed directly to OrderTimeline component
        };

        setOrder(orderData);
        setSessionEvents(allSessionEvents);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'Failed to retrieve order details.');
        setLoading(false);
      });
  }, [id]);

  const handleBack = () => {
    navigate('/orders');
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="order-details-loading container font-mono">
        <Loader2 className="loading-spinner animate-spin" />
        <h3>RECONSTRUCTING FULFILLMENT REGISTRY FOR ORD-{id?.padStart(6, '0')}...</h3>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="order-details-error-container container animate-fade-in font-mono">
        <div className="order-details-error-panel">
          <AlertTriangle className="error-icon" />
          <h3>REGISTRY QUERY ERROR</h3>
          <p className="error-msg">{error}</p>
          <button onClick={handleBack} className="btn btn-secondary">
            <ArrowLeft className="btn-icon" />
            <span>Back to Console</span>
          </button>
        </div>
      </div>
    );
  }

  // Define steps for visual fulfillment lifecycle
  // 1: ORDER CREATED (always done)
  // 2: PAYMENT CONFIRMED (done if order status is PAID)
  // 3-6: ORDER ACCEPTED, PROCESSING, SHIPPED, DELIVERED (always unavailable in backend)
  const steps = [
    { key: 'CREATED', label: 'ORDER CREATED', completed: true },
    { key: 'PAID', label: 'PAYMENT CONFIRMED', completed: order.status === 'PAID' },
    { key: 'ACCEPTED', label: 'ORDER ACCEPTED', completed: false, unavailable: true },
    { key: 'PROCESSING', label: 'PROCESSING', completed: false, unavailable: true },
    { key: 'SHIPPED', label: 'SHIPPED', completed: false, unavailable: true },
    { key: 'DELIVERED', label: 'DELIVERED', completed: false, unavailable: true }
  ];

  const startEvent = sessionEvents.find(e => e.action === 'AGENT_SESSION_CREATED');
  const buyerId = startEvent?.metadata?.buyer_id || 'demo-buyer-001';
  const sessionId = startEvent?.metadata?.session_id || 'session_demo';

  return (
    <div className="order-details-page container animate-fade-in">
      {/* Header Bar */}
      <div className="order-details-header">
        <button onClick={handleBack} className="back-btn font-mono">
          <ArrowLeft className="back-icon" />
          <span>Back to Console</span>
        </button>

        <div className="order-details-header-title">
          <h2>ORDER COMPLIANCE & TRACKING</h2>
          <p className="font-mono text-dimmed">ORD-{order.id.toString().padStart(6, '0')}</p>
        </div>

        <div className="order-details-header-status font-mono">
          <span className={`status-dot ${order.status.toLowerCase()}`} />
          <span>{order.status}</span>
        </div>
      </div>

      {/* Visual Fulfillment Lifecycle Tracker */}
      <div className="lifecycle-tracker-card font-mono">
        <h3 className="section-title">FULFILLMENT LIFECYCLE</h3>
        <div className="lifecycle-steps">
          {steps.map((step) => {
            const isCompleted = step.completed;
            const isUnavailable = step.unavailable;
            let stepClass = 'lifecycle-step';
            if (isCompleted) stepClass += ' completed';
            else if (isUnavailable) stepClass += ' unavailable';
            else stepClass += ' pending';

            return (
              <div key={step.key} className={stepClass}>
                <div className="step-connector" />
                <div className="step-indicator">
                  {isCompleted ? (
                    <CheckCircle className="step-icon text-green" />
                  ) : isUnavailable ? (
                    <ShieldAlert className="step-icon text-dimmed" />
                  ) : (
                    <Loader2 className="step-icon animate-spin text-orange" />
                  )}
                </div>
                <div className="step-info">
                  <span className="step-label">{step.label}</span>
                  {isUnavailable && <span className="step-unavailable-lbl">Unavailable</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="order-details-grid">
        {/* Left Column: Summary & Items */}
        <div className="order-details-main-col">
          {/* Order Identity Card */}
          <div className="details-identity-card font-mono">
            <div className="card-header">
              <Info className="card-icon text-secondary" />
              <span>ORDER REGISTRY IDENTITIES</span>
            </div>
            <div className="card-body">
              <div className="info-row">
                <span className="info-lbl">Order Identifier:</span>
                <span className="info-val text-white">ORD-{order.id.toString().padStart(6, '0')}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Ledger Transaction ID:</span>
                <span className="info-val text-white">TXN-{order.transactionId.toString().padStart(6, '0')}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Purchase Request Reference:</span>
                <span className="info-val text-white">PR-{order.purchaseRequestId}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Buyer Agent Proxy:</span>
                <span className="info-val text-white">{buyerId}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Audit/Trust Session ID:</span>
                <span className="info-val text-white">{sessionId}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Timestamp of Creation:</span>
                <span className="info-val text-muted">{formatDate(order.createdAt)}</span>
              </div>
            </div>
          </div>

          {/* Payment Card */}
          <div className="details-identity-card font-mono">
            <div className="card-header">
              <CreditCard className="card-icon text-secondary" />
              <span>PAYMENT SECURE SNAPSHOT</span>
            </div>
            <div className="card-body">
              <div className="info-row">
                <span className="info-lbl">Razorpay Order Reference:</span>
                <span className="info-val text-white">{order.razorpayOrderId || '—'}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Razorpay Payment Reference:</span>
                <span className="info-val text-white">{order.razorpayPaymentId || '—'}</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Amount Lock Status:</span>
                <span className="info-val text-green font-bold">LOCKED ({order.paymentStatus})</span>
              </div>
              <div className="info-row">
                <span className="info-lbl">Final Net Paid Amount:</span>
                <span className="info-val text-green font-bold">
                  {new Intl.NumberFormat('en-IN', { style: 'currency', currency: order.currency }).format(order.amount)}
                </span>
              </div>
            </div>
          </div>

          {/* Product Items Details Table */}
          <OrderItems items={order.items} currency={order.currency} />
        </div>

        {/* Right Column: Financial Summary & Timeline */}
        <div className="order-details-sidebar-col">
          {/* Order Summary card */}
          <OrderSummary order={order} />

          {/* Cryptographic timeline */}
          <OrderTimeline sessionEvents={sessionEvents} />
        </div>
      </div>
    </div>
  );
}
