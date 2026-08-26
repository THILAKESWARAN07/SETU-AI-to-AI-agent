import { 
  ShieldCheck, 
  Lock, 
  Key, 
  Layers, 
  Database, 
  RefreshCw,
  HelpCircle
} from 'lucide-react';
import type { SecurityGate } from '../../types';
import './SecurityGateGrid.css';

interface SecurityGateGridProps {
  gates: SecurityGate[];
}

export default function SecurityGateGrid({ gates }: SecurityGateGridProps) {
  const getIcon = (iconName: string) => {
    switch (iconName) {
      case 'policy': return <Layers className="gate-card-icon" />;
      case 'amount': return <Lock className="gate-card-icon" />;
      case 'tool': return <Key className="gate-card-icon" />;
      case 'lock': return <Database className="gate-card-icon" />;
      case 'webhook': return <RefreshCw className="gate-card-icon" />;
      case 'audit': return <ShieldCheck className="gate-card-icon" />;
      default: return <HelpCircle className="gate-card-icon" />;
    }
  };

  return (
    <div className="security-gate-grid animate-fade-in">
      {gates.map((gate) => {
        const isPassed = gate.status === 'PASSED';
        const isConfigured = gate.status === 'CONFIGURED';
        const isFailed = gate.status === 'FAILED';

        let badgeClass = 'gate-badge font-mono';
        if (isPassed) badgeClass += ' passed';
        else if (isConfigured) badgeClass += ' configured';
        else if (isFailed) badgeClass += ' failed';

        return (
          <div key={gate.id} className={`gate-card ${gate.status.toLowerCase()}`}>
            <div className="gate-card-hdr">
              <div className="icon-badge-group">
                {getIcon(gate.iconName)}
                <h3 className="gate-name font-mono">{gate.name}</h3>
              </div>
              <span className={badgeClass}>{gate.status}</span>
            </div>

            <p className="gate-desc text-muted">{gate.description}</p>
            
            <div className="gate-divider" />

            <div className="gate-evidence-block font-mono">
              <span className="evidence-lbl text-dimmed">EVIDENCE / LOG:</span>
              <p className="evidence-val text-white">{gate.evidence}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
