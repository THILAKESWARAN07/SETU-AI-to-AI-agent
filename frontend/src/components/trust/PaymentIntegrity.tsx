import { ShieldCheck, FileCheck, Lock, CreditCard, RefreshCw, Layers, ArrowRight } from 'lucide-react';
import './PaymentIntegrity.css';

interface PaymentIntegrityProps {
  transactionId: number | null;
  purchaseRequestId: number | null;
  razorpayOrderId: string | null;
  amount: number | null;
  status: string | null;
}

export default function PaymentIntegrity({
  transactionId,
  purchaseRequestId,
  razorpayOrderId,
  amount,
  status
}: PaymentIntegrityProps) {
  
  const hasData = transactionId !== null;
  const isSuccess = status === 'SUCCESS';

  const nodes = [
    {
      id: 'snapshot',
      title: 'Policy Snapshot',
      icon: <Layers className="node-icon" />,
      desc: hasData ? `PR-${purchaseRequestId} Snap` : 'Snapshots Locked',
      active: hasData
    },
    {
      id: 'request',
      title: 'Purchase Request',
      icon: <FileCheck className="node-icon" />,
      desc: hasData ? `PR-${purchaseRequestId}` : 'PR Created',
      active: hasData
    },
    {
      id: 'lock',
      title: 'Amount Lock',
      icon: <Lock className="node-icon animate-pulse" />,
      desc: hasData ? `₹${parseFloat(amount?.toString() || '0').toLocaleString('en-IN')}` : 'Strict DB Lock',
      active: hasData
    },
    {
      id: 'order',
      title: 'Payment Order',
      icon: <CreditCard className="node-icon" />,
      desc: hasData ? `${razorpayOrderId?.substring(0, 15)}...` : 'Gateway Order',
      active: hasData
    },
    {
      id: 'webhook',
      title: 'Webhook Verify',
      icon: <RefreshCw className="node-icon" />,
      desc: hasData && isSuccess ? 'HMAC Verified' : hasData ? 'Awaiting Callback' : 'SHA256 Match',
      active: hasData && isSuccess,
      pending: hasData && !isSuccess
    },
    {
      id: 'settled',
      title: 'Settle State',
      icon: <ShieldCheck className="node-icon" />,
      desc: hasData && isSuccess ? 'Setted (PAID)' : hasData ? 'Awaiting Settlement' : 'DB State Synced',
      active: hasData && isSuccess,
      pending: hasData && !isSuccess
    }
  ];

  return (
    <div className="payment-integrity-container animate-fade-in">
      <h3 className="integrity-title font-mono text-secondary">PAYMENT AMOUNT SIGNATURE CHAIN</h3>
      <p className="integrity-subtitle text-dimmed">
        Validates amount snapshots matching 1-to-1 database node reference mappings:
      </p>

      <div className="integrity-flowchart">
        {nodes.map((node, idx) => {
          let nodeClass = 'flowchart-node';
          if (node.active) nodeClass += ' active';
          else if (node.pending) nodeClass += ' pending';

          return (
            <div key={node.id} className="flowchart-step-wrapper">
              <div className={nodeClass}>
                <div className="node-icon-wrapper">
                  {node.icon}
                </div>
                <div className="node-text">
                  <h4 className="node-title font-mono">{node.title}</h4>
                  <p className="node-desc font-mono">{node.desc}</p>
                </div>
              </div>
              
              {idx < nodes.length - 1 && (
                <div className={`flowchart-connector ${node.active ? 'active' : ''}`}>
                  <ArrowRight className="connector-arrow-icon" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
