import { ShieldCheck, Percent, DollarSign, ListFilter } from 'lucide-react';
import './PolicyEnginePanel.css';

interface PolicyEnginePanelProps {
  originalAmount: string;
  finalAmount: string;
  discountPercent: string;
  marginPercent: string;
  policyVersion: string;
}

export default function PolicyEnginePanel({
  originalAmount,
  finalAmount,
  discountPercent,
  marginPercent,
  policyVersion
}: PolicyEnginePanelProps) {
  const discountVal = parseFloat(originalAmount) - parseFloat(finalAmount);

  return (
    <div className="policy-engine-panel animate-fade-in">
      <div className="policy-panel-header">
        <ShieldCheck className="policy-header-icon" />
        <div>
          <h3>SETU POLICY ENGINE</h3>
          <p className="policy-subtitle">Deterministic Compliance Validation ({policyVersion})</p>
        </div>
      </div>

      <div className="policy-metrics-grid">
        <div className="policy-metric-box">
          <div className="metric-box-title">
            <DollarSign className="box-icon" />
            <span>ORIGINAL AMOUNT</span>
          </div>
          <p className="metric-box-value">₹{parseFloat(originalAmount).toLocaleString('en-IN')}</p>
        </div>

        <div className="policy-metric-box">
          <div className="metric-box-title">
            <DollarSign className="box-icon" />
            <span>FINAL NEGOTIATED</span>
          </div>
          <p className="metric-box-value highlight-blue">₹{parseFloat(finalAmount).toLocaleString('en-IN')}</p>
        </div>

        <div className="policy-metric-box">
          <div className="metric-box-title">
            <Percent className="box-icon" />
            <span>NEGOTIATED DISCOUNT</span>
          </div>
          <p className="metric-box-value highlight-green">
            {parseFloat(discountPercent).toFixed(2)}%
            <span className="discount-amount-sub"> (-₹{discountVal.toLocaleString('en-IN')})</span>
          </p>
        </div>

        <div className="policy-metric-box">
          <div className="metric-box-title">
            <Percent className="box-icon" />
            <span>MERCHANT MARGIN</span>
          </div>
          <p className="metric-box-value highlight-green">{parseFloat(marginPercent).toFixed(2)}%</p>
        </div>
      </div>

      <div className="policy-rules-footer">
        <div className="footer-title">
          <ListFilter className="footer-icon" />
          <span>Active Rules Validations:</span>
        </div>
        <div className="rules-grid">
          <div className="rule-item-status passed">
            <span className="rule-dot green" />
            <span>Discount Cap Check: APPROVED (Boundary: &lt; 10%)</span>
          </div>
          <div className="rule-item-status passed">
            <span className="rule-dot green" />
            <span>Profit Margin Check: APPROVED (Boundary: &gt; 20%)</span>
          </div>
          <div className="rule-item-status passed">
            <span className="rule-dot green" />
            <span>Order Limit Check: APPROVED (Boundary: &lt; ₹2,000)</span>
          </div>
        </div>
      </div>
    </div>
  );
}
