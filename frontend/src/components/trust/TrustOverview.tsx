import { Shield, ShieldAlert, Cpu } from 'lucide-react';
import type { Transaction } from '../../types';
import './TrustOverview.css';

interface TrustOverviewProps {
  transactions: Transaction[];
  selectedTxId: number | null;
  onSelectTx: (id: number | null) => void;
}

export default function TrustOverview({
  transactions,
  selectedTxId,
  onSelectTx
}: TrustOverviewProps) {
  
  const activeTx = transactions.find(t => t.id === selectedTxId);

  return (
    <div className="trust-overview-card animate-fade-in">
      <div className="overview-header-row">
        <div className="shield-logo-group">
          <div className="shield-glow-wrapper">
            <Shield className="overview-shield animate-pulse" />
          </div>
          <div className="overview-title-group">
            <span className="overview-subline font-mono text-secondary">SETU TRUST RUNTIME</span>
            <h2 className="overview-headline">SYSTEM STATE: SECURED</h2>
          </div>
        </div>

        <div className="system-indicator-badge">
          <span className="indicator-dot blinking" />
          <span className="font-mono text-green">ACTIVE ISOLATION</span>
        </div>
      </div>

      <div className="overview-desc-block">
        <p className="text-muted">
          SETU runs an isolated **fixed-point mathematical policy compiler** separating generative LLM negotiations from transactional database updates. Inspect the live security status of past transactions by choosing an active ledger sequence ID below:
        </p>
      </div>

      <div className="transaction-selector-wrapper">
        <div className="selector-label-group">
          <Cpu className="selector-icon text-secondary" />
          <span className="font-mono text-dimmed">INSPECT SPECIFIC TRANSACTION:</span>
        </div>
        
        <select
          value={selectedTxId || ''}
          onChange={(e) => {
            const val = e.target.value;
            onSelectTx(val ? parseInt(val, 10) : null);
          }}
          className="txn-selector font-mono"
        >
          <option value="">GLOBAL VIEW (SYSTEM SECURITY DEFAULTS)</option>
          {transactions.map((tx) => (
            <option key={tx.id} value={tx.id}>
              TXN-{tx.id.toString().padStart(6, '0')} (Amount: ₹{parseFloat(tx.amount.toString()).toLocaleString('en-IN')}, Status: {tx.status})
            </option>
          ))}
        </select>
      </div>

      {activeTx && (
        <div className="active-inspection-banner font-mono animate-fade-in">
          <ShieldAlert className="banner-alert-icon text-green" />
          <span>
            Currently inspecting: <strong>TXN-{activeTx.id.toString().padStart(6, '0')}</strong>. Security gate evidence is derived dynamically from sqlite audit logs.
          </span>
        </div>
      )}
    </div>
  );
}
