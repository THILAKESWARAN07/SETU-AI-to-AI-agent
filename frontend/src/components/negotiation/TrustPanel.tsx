import { ShieldCheck, Lock, CheckSquare, Fingerprint, Key } from 'lucide-react';
import './TrustPanel.css';

export default function TrustPanel() {
  const securityGates = [
    {
      title: 'Merchant boundaries verified',
      desc: 'Negotiation ranges strictly capped inside merchant policy limits.',
      icon: <ShieldCheck className="gate-icon success" />
    },
    {
      title: 'Offer snapshot recorded',
      desc: 'Sealed contract parameters saved into SQLite databases before checkout.',
      icon: <Fingerprint className="gate-icon info" />
    },
    {
      title: 'Payment amount locked',
      desc: 'Gateway checks database reference snapshots; tampered amounts are blocked.',
      icon: <Lock className="gate-icon alert" />
    },
    {
      title: 'Policy checks stamped',
      desc: 'Policy Engine signatures audit-logged for validation.',
      icon: <CheckSquare className="gate-icon success" />
    },
    {
      title: 'Agent tools restricted',
      desc: 'Isolated LLM runtimes; payment routines locked from tool registries.',
      icon: <Key className="gate-icon info" />
    }
  ];

  return (
    <div className="trust-panel-card animate-fade-in">
      <h3 className="trust-panel-title">Transaction Security Gates</h3>
      
      <div className="gates-list">
        {securityGates.map((gate, idx) => (
          <div key={idx} className="gate-row-item">
            <div className="gate-icon-wrapper">
              {gate.icon}
            </div>
            <div className="gate-text-content">
              <h4>{gate.title}</h4>
              <p>{gate.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
