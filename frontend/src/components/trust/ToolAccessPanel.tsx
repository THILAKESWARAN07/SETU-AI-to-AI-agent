import { Key, ShieldAlert, Cpu, ArrowRight, ShieldCheck } from 'lucide-react';
import './ToolAccessPanel.css';

export default function ToolAccessPanel() {
  const buyerTools = [
    { name: 'search_catalog', desc: 'Allows scanning the store catalog for items matching buyer intent.' },
    { name: 'get_product_details', desc: 'Allows reading detailed catalog specifications, stock counts, and prices.' },
    { name: 'get_policy_constraints', desc: 'Retrieves active budget constraints and policy rules for negotiation.' },
    { name: 'evaluate_budget', desc: 'Validates candidate offer amounts against user-configured budget caps.' },
    { name: 'request_purchase', desc: 'Submits a finalized negotiated deal proposal to the backend Policy Engine.' }
  ];

  const merchantTools = [
    { name: 'get_inventory', desc: 'Allows reading current inventory count of items in stock.' },
    { name: 'get_product_price', desc: 'Fetches catalog base pricing and unit cost bounds for the product.' },
    { name: 'get_merchant_constraints', desc: 'Reads merchant policy constraints, margin floors, and discount limits.' },
    { name: 'evaluate_margin', desc: 'Evaluates the buyer\'s offer to check compliance with min margin requirements.' }
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
            <span>AI Agents</span>
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
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div>
                <span className="font-mono text-primary" style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px', display: 'block', marginBottom: '8px' }}>
                  Buyer Agent Permissions
                </span>
                <div className="tools-list font-mono">
                  {buyerTools.map(tool => (
                    <div key={tool.name} className="tool-item">
                      <span className="tool-name text-white">{tool.name}</span>
                      <p className="tool-desc text-dimmed">{tool.desc}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <span className="font-mono text-orange" style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px', display: 'block', marginBottom: '8px' }}>
                  Merchant Agent Permissions
                </span>
                <div className="tools-list font-mono">
                  {merchantTools.map(tool => (
                    <div key={tool.name} className="tool-item">
                      <span className="tool-name text-white">{tool.name}</span>
                      <p className="tool-desc text-dimmed">{tool.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
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
