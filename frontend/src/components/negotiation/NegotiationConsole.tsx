import { Terminal } from 'lucide-react';
import './NegotiationConsole.css';

interface NegotiationConsoleProps {
  purchaseRequestId: number;
  decision: string;
}

export default function NegotiationConsole({ purchaseRequestId, decision }: NegotiationConsoleProps) {
  const logs = [
    { source: 'BUYER_AGENT', msg: 'Formulating buyer intent constraints. Target: Wireless Earbuds.' },
    { source: 'MERCHANT_AGENT', msg: 'Matching query to catalog products (ID 1). Related cross-sell (ID 2) proposed.' },
    { source: 'MERCHANT_AGENT', msg: 'Formulated bundle offer (Product ID 3). Price: ₹1,998.00.' },
    { source: 'BUYER_AGENT', msg: 'Round 1 Bid: Proposing ₹1,800.00 for bundle.' },
    { source: 'MERCHANT_AGENT', msg: 'Round 1 Bid rejected (Margin limit boundary check failed).' },
    { source: 'MERCHANT_AGENT', msg: 'Round 2 Counter-proposal: Proposing ₹1,899.00.' },
    { source: 'BUYER_AGENT', msg: 'Round 3 Evaluation: Counter-proposal ₹1,899.00 matches active boundaries.' },
    { source: 'BUYER_AGENT', msg: 'Round 3 Bid: Accepting ₹1,899.00 counter-offer.' },
    { source: 'POLICY_ENGINE', msg: 'Sealing proposal payload. Evaluating active rules...' },
    { source: 'POLICY_ENGINE', msg: `Rules checked. Policy decision state: ${decision}.` },
    { source: 'SYSTEM', msg: `PurchaseRequest ID ${purchaseRequestId} recorded and locked. Gateway checkout enabled.` }
  ];

  return (
    <div className="negotiation-console-panel animate-fade-in">
      <div className="console-panel-header">
        <Terminal className="console-panel-icon" />
        <span>DEVELOPER SYSTEM TRACE</span>
        <span className="console-panel-status">ACTIVE</span>
      </div>

      <div className="console-panel-body">
        {logs.map((log, idx) => {
          let sourceClass = 'source-system';
          if (log.source === 'BUYER_AGENT') sourceClass = 'source-buyer';
          if (log.source === 'MERCHANT_AGENT') sourceClass = 'source-merchant';
          if (log.source === 'POLICY_ENGINE') sourceClass = 'source-policy';

          return (
            <div key={idx} className="console-log-line">
              <span className="log-line-num">{(idx + 1).toString().padStart(2, '0')}</span>
              <span className="log-line-timestamp">[{new Date().toLocaleTimeString()}]</span>
              <span className={`log-line-source ${sourceClass}`}>[{log.source}]</span>
              <span className="log-line-msg">{log.msg}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
