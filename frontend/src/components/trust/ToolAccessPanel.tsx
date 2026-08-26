import { Key, ShieldAlert, Cpu, ArrowRight, ShieldCheck } from 'lucide-react';
import './ToolAccessPanel.css';

export default function ToolAccessPanel() {
  const allowedTools = [
    { name: 'view_product', desc: 'Allows the agent to retrieve catalog listing descriptions and prices.' },
    { name: 'search_catalog', desc: 'Allows searching catalog indexes for relevant recommendations.' },
    { name: 'identify_related_product', desc: 'Identifies related cross-sells for recommendation slots.' },
    { name: 'create_bundle_offer', desc: 'Combines selected listings into structured discounted offers.' },
    { name: 'negotiate', desc: 'Runs AI procurement reasoning to propose Counter-Offers.' },
    { name: 'request_purchase', desc: 'Submits a finalised proposal to the backend Policy Engine.' }
  ];

  const excludedTools = [
    'create_razorpay_order',
    'capture_payment',
    'verify_webhook_signature',
    'capture_gateway_credentials'
  ];

  return (
    <div className="tool-access-container animate-fade-in">
      <div className="tool-hdr-bar font-mono">
        <span className="text-secondary">RESTRICTED AGENT TOOL REGISTRY</span>
        <span className="text-dimmed">STATUS: ACTIVE GATING</span>
      </div>

      <div className="tool-layout">
        {/* Left Side: Architectural flow */}
        <div className="tool-flow-diagram font-mono">
          <div className="flow-node agent">
            <Cpu className="node-icon text-primary" />
            <span>Buyer Agent</span>
          </div>
          <ArrowRight className="flow-arrow text-dimmed" />
          
          <div className="flow-node tools">
            <Key className="node-icon text-secondary" />
            <span>Allowed Tools</span>
          </div>
          <ArrowRight className="flow-arrow text-dimmed" />
          
          <div className="flow-node gate">
            <ShieldAlert className="node-icon text-orange" />
            <span>Trust Layer Gate</span>
          </div>
          <ArrowRight className="flow-arrow text-dimmed" />
          
          <div className="flow-node payment">
            <ShieldCheck className="node-icon text-green" />
            <span>Payment System</span>
          </div>
        </div>

        <div className="tool-lists-grid">
          {/* Allowed Tools */}
          <div className="allowed-tools-box">
            <h4 className="box-title font-mono text-green">ALLOWED REGISTERED TOOLS</h4>
            <div className="tools-list font-mono">
              {allowedTools.map(tool => (
                <div key={tool.name} className="tool-item">
                  <span className="tool-name text-white">{tool.name}</span>
                  <p className="tool-desc text-dimmed">{tool.desc}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Excluded Tools */}
          <div className="excluded-tools-box">
            <h4 className="box-title font-mono text-red">STRICTLY EXCLUDED CAPABILITIES</h4>
            <p className="excluded-warning-desc text-muted">
              The Agent Tool Registry strictly filters and blocks all direct interface capabilities containing the following keywords or actions:
            </p>
            <ul className="excluded-list font-mono">
              {excludedTools.map(tool => (
                <li key={tool} className="excluded-item">
                  <span className="bullet-dot text-red" />
                  <span className="text-muted">{tool}</span>
                </li>
              ))}
            </ul>
            <div className="gating-notice font-mono">
              <strong>SECURITY ASSURANCE:</strong> Generative models possess zero local references to Razorpay keys or checkout credentials. Gating is enforced on SQLite/PostgreSQL database layers.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
