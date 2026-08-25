import { Check, AlertCircle, Clock } from 'lucide-react';
import './TransactionStatus.css';

interface TransactionStatusProps {
  status: 'PENDING' | 'SUCCESS' | 'FAILED';
}

export default function TransactionStatus({ status }: TransactionStatusProps) {
  const steps = [
    { label: 'PAYMENT CREATED', key: 'created' },
    { label: 'ORDER LOCKED', key: 'locked' },
    { label: 'AWAITING PAYMENT', key: 'awaiting' },
    { label: 'PAYMENT CONFIRMED', key: 'confirmed' }
  ];

  // Map status to active index
  let activeIndex = 2; // Default is AWAITING PAYMENT (2)
  if (status === 'SUCCESS') activeIndex = 3; // CONFIRMED (3)
  if (status === 'FAILED') activeIndex = 2; // AWAITING/FAILED (2)

  return (
    <div className="tx-status-container animate-fade-in">
      <div className="tx-status-header">
        {status === 'PENDING' ? (
          <Clock className="status-header-icon pending animate-pulse" />
        ) : status === 'SUCCESS' ? (
          <Check className="status-header-icon success" />
        ) : (
          <AlertCircle className="status-header-icon failed" />
        )}
        <div>
          <h3>Transaction Status: {status}</h3>
          <p className="tx-status-subtitle font-mono">
            {status === 'PENDING' && 'Order amount locked. Awaiting Razorpay checkout validation...'}
            {status === 'SUCCESS' && 'Webhook verified. Purchase contract marked as PAID.'}
            {status === 'FAILED' && 'Payment verification failed. Check security audits.'}
          </p>
        </div>
      </div>

      <div className="tx-steps-flow">
        {steps.map((step, idx) => {
          const isCompleted = idx < activeIndex;
          const isActive = idx === activeIndex && status !== 'FAILED';
          const isPending = idx > activeIndex;
          const isFailed = idx === activeIndex && status === 'FAILED';

          let stepClass = 'tx-step';
          if (isCompleted) stepClass += ' completed';
          if (isActive) stepClass += ' active';
          if (isPending) stepClass += ' pending';
          if (isFailed) stepClass += ' failed-step';

          return (
            <div key={step.key} className={stepClass}>
              <div className="tx-circle">
                {isCompleted ? (
                  <Check className="tx-check-icon" />
                ) : isFailed ? (
                  <AlertCircle className="tx-error-icon" />
                ) : (
                  <span>0{idx + 1}</span>
                )}
              </div>
              <span className="tx-label">{step.label}</span>
              {idx < steps.length - 1 && <div className="tx-line" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
