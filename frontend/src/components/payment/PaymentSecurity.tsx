import { ShieldCheck, Database, Lock, Key, RefreshCw, Layers } from 'lucide-react';
import './PaymentSecurity.css';

export default function PaymentSecurity() {
  const securityChecks = [
    {
      title: 'Approved Policy Snapshot',
      desc: 'Sealed policy parameters matching the initial evaluation.',
      icon: <ShieldCheck className="sec-icon success" />
    },
    {
      title: 'Final Amount Integrity',
      desc: 'Checkout amount cross-references DB values exactly; client side edits block.',
      icon: <Lock className="sec-icon info" />
    },
    {
      title: 'Merchant Pricing Boundary',
      desc: 'Profit margins and discount bounds verified deterministically.',
      icon: <Layers className="sec-icon success" />
    },
    {
      title: 'Restricted Payment Tool Access',
      desc: 'Gateway handles API calls; LLMs have zero direct transaction functions.',
      icon: <Key className="sec-icon info" />
    },
    {
      title: 'Transaction Reference',
      desc: 'One-to-one UUID references established between database nodes.',
      icon: <Database className="sec-icon success" />
    },
    {
      title: 'Duplicate Protection',
      desc: 'Idempotency keys enforce single gateway orders per purchase request.',
      icon: <RefreshCw className="sec-icon alert" />
    }
  ];

  return (
    <div className="payment-security-card animate-fade-in">
      <h3 className="security-title">Security Verifications</h3>
      
      <div className="security-checks-list">
        {securityChecks.map((check, idx) => (
          <div key={idx} className="security-check-row">
            <div className="security-icon-wrapper">
              {check.icon}
            </div>
            <div className="security-text-content">
              <h4>{check.title}</h4>
              <p>{check.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="security-explanation-box">
        <p>
          <strong>TRUST ADVISORY:</strong> SETU does not allow the client to freely modify the approved transaction amount.
        </p>
      </div>
    </div>
  );
}
