import { ArrowRight, ShieldCheck, ShieldAlert, Sparkles, Binary } from 'lucide-react';
import './PolicyStatus.css';

interface PolicyStatusProps {
  originalAmount: string;
  finalAmount: string;
  discountPercent: string;
  marginPercent: string;
  decision: string;
  policyVersion: string;
}

export default function PolicyStatus({
  originalAmount,
  finalAmount,
  discountPercent,
  marginPercent,
  decision,
  policyVersion
}: PolicyStatusProps) {
  
  const formatINR = (val: string | number) => {
    const parsed = typeof val === 'string' ? parseFloat(val) : val;
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2
    }).format(parsed);
  };

  const isApproved = decision === 'APPROVED' || decision === 'PAID' || decision === 'SUCCESS';

  return (
    <div className="policy-status-container animate-fade-in">
      <div className="policy-hdr-bar font-mono">
        <span className="text-secondary">POLICY COMPLIANCE VERIFICATION</span>
        <span className="text-dimmed">VERSION: {policyVersion}</span>
      </div>

      <div className="policy-comparison-layout">
        {/* Left Layer: AI Agent Proposal */}
        <div className="comparison-card ai-proposal-panel">
          <div className="comp-card-hdr text-dimmed font-mono">
            <Sparkles className="comp-hdr-icon text-primary" />
            <span>AI NEGOTIATOR PROPOSAL</span>
          </div>

          <div className="comp-card-metrics font-mono">
            <div className="comp-metric-item">
              <span className="lbl text-dimmed">Standard Catalog Price:</span>
              <span className="val text-white">{formatINR(originalAmount)}</span>
            </div>
            <div className="comp-metric-item">
              <span className="lbl text-dimmed">Proposed AI Discount:</span>
              <span className="val text-primary">
                {isApproved && discountPercent && parseFloat(discountPercent) > 0 ? `- ${parseFloat(discountPercent).toFixed(2)}%` : 'N/A'}
              </span>
            </div>
            <div className="comp-divider" />
            <div className="comp-metric-item total-row">
              <span className="lbl text-white">Proposed Final Price:</span>
              <span className="val text-primary font-bold">
                {isApproved && finalAmount && parseFloat(finalAmount) > 0 ? formatINR(finalAmount) : 'N/A'}
              </span>
            </div>
          </div>
          <div className="comp-card-desc">
            <p className="text-dimmed">AI agents execute stochastic search and negotiation turns to optimize pricing.</p>
          </div>
        </div>

        {/* Center Indicator */}
        <div className="comparison-separator">
          <div className="separator-line" />
          <div className="separator-arrow-circle">
            <ArrowRight className="sep-arrow" />
          </div>
        </div>

        {/* Right Layer: Deterministic policy engine */}
        <div className="comparison-card policy-engine-panel">
          <div className="comp-card-hdr text-dimmed font-mono">
            <Binary className="comp-hdr-icon text-secondary" />
            <span>DETERMINISTIC VALIDATOR</span>
          </div>

          <div className="comp-card-metrics font-mono">
            <div className="comp-metric-item">
              <span className="lbl text-dimmed">Min Profit Margin Required:</span>
              <span className="val text-white">30.00%</span>
            </div>
            <div className="comp-metric-item">
              <span className="lbl text-dimmed">Evaluated Profit Margin:</span>
              <span className="val text-green font-bold">{parseFloat(marginPercent).toFixed(2)}%</span>
            </div>
            <div className="comp-metric-item">
              <span className="lbl text-dimmed">Maximum Auto-Order Cap:</span>
              <span className="val text-white">₹5,000.00</span>
            </div>
            <div className="comp-divider" />
            <div className="comp-metric-item decision-row">
              <span className="lbl text-white">VERDICT RESULT:</span>
              <span className={`val decision-verdict font-bold ${isApproved ? 'text-green' : 'text-red'}`}>
                {isApproved ? 'APPROVED' : 'BLOCKED'}
              </span>
            </div>
          </div>

          <div className="policy-badge-wrapper font-mono">
            {isApproved ? (
              <div className="policy-gate-badge passed">
                <ShieldCheck className="badge-sh-icon" />
                <span>POLICY PASS</span>
              </div>
            ) : (
              <div className="policy-gate-badge failed">
                <ShieldAlert className="badge-sh-icon" />
                <span>POLICY BLOCKED</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
