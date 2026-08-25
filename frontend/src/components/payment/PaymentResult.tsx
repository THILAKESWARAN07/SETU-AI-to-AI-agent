import { AlertTriangle, RefreshCw, HelpCircle, ShieldAlert } from 'lucide-react';
import './PaymentResult.css';

interface PaymentResultProps {
  errorMsg: string | null;
  onRetry: () => void;
  onGoToShopping: () => void;
}

export default function PaymentResult({
  errorMsg,
  onRetry,
  onGoToShopping
}: PaymentResultProps) {
  // Construct a safe user-facing message avoiding stack traces or internal implementation leaks
  const safeMessage = errorMsg && !errorMsg.includes('traceback') && !errorMsg.includes('Exception')
    ? errorMsg
    : 'The payment transaction could not be processed. This occurs when there is a network connection interruption or the security validation rejects parameters that mismatch the approved policy snapshot.';

  return (
    <div className="payment-result-container animate-fade-in">
      <div className="failure-card">
        <div className="failure-icon-wrapper">
          <AlertTriangle className="failure-card-icon" />
        </div>

        <span className="failure-tag font-mono text-red">SECURITY GATE DETECTED</span>
        <h2 className="failure-title">PAYMENT TRANSACTION FAILED</h2>
        
        <p className="failure-desc">
          {safeMessage}
        </p>

        <div className="security-alert-box">
          <ShieldAlert className="alert-icon" />
          <div className="alert-text font-mono">
            <strong>NOTICE:</strong> SETU enforces a strict database-level amount lock. Modifying pricing on client checkouts or attempting replay headers will automatically flag and terminate active payment sessions.
          </div>
        </div>

        <div className="failure-faq">
          <div className="faq-item">
            <HelpCircle className="faq-icon" />
            <div>
              <h4>Did you modify the checkout session?</h4>
              <p className="text-dimmed">The payment system will reject any pricing values that do not match the approved policy snapshots stored in the DB.</p>
            </div>
          </div>
          <div className="faq-item">
            <HelpCircle className="faq-icon" />
            <div>
              <h4>Is your checkout session locked?</h4>
              <p className="text-dimmed">Once a transaction enters PENDING state, its details are strictly locked. You can safely release it by retrying validation or starting a new procurement.</p>
            </div>
          </div>
        </div>

        <div className="failure-divider" />

        <div className="failure-actions">
          <button onClick={onGoToShopping} className="btn btn-secondary action-btn">
            <span>Back to Shopping</span>
          </button>
          <button onClick={onRetry} className="btn btn-primary btn-glow action-btn">
            <RefreshCw className="btn-icon" />
            <span>Retry Validation</span>
          </button>
        </div>
      </div>
    </div>
  );
}
