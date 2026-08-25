import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  UserCheck, 
  Store, 
  MessageSquare, 
  ShieldAlert, 
  CreditCard, 
  Play, 
  Layers, 
  CheckCircle,
  Database,
  ArrowRight
} from 'lucide-react';
import './Dashboard.css';

export default function Dashboard() {
  const [activeStep, setActiveStep] = useState<number | null>(null);

  const steps = [
    {
      id: 1,
      title: 'Buyer Agent',
      icon: <UserCheck className="step-icon" />,
      desc: 'Formulates procurement intent and enforces local budget limits.',
      badge: 'LLM Isolated'
    },
    {
      id: 2,
      title: 'Merchant Agent',
      icon: <Store className="step-icon" />,
      desc: 'Identifies listings, suggests cross-sells, and cross-references policies.',
      badge: 'LLM Isolated'
    },
    {
      id: 3,
      title: 'Negotiation Engine',
      icon: <MessageSquare className="step-icon" />,
      desc: 'Orchestrates structured turn negotiation for discounts and bundles.',
      badge: 'AI-to-AI Dialog'
    },
    {
      id: 4,
      title: 'Policy Engine',
      icon: <ShieldAlert className="step-icon" />,
      desc: 'Enforces discount caps and profit margin rules in deterministic code.',
      badge: 'Fixed-Point Math'
    },
    {
      id: 5,
      title: 'Secure Payment Gateway',
      icon: <CreditCard className="step-icon" />,
      desc: 'Creates Razorpay orders only for pre-approved policy decisions.',
      badge: 'Database Locked'
    }
  ];

  const navigate = useNavigate();

  const handleStartShopping = () => {
    navigate('/shopping');
  };

  return (
    <div className="dashboard-container animate-fade-in">
      {/* Hero Section */}
      <section className="hero-section">
        <div className="hero-badge">
          <Layers className="badge-icon" />
          <span>SETU Trust Layer v1.0.0</span>
        </div>
        <h1 className="hero-title">
          SETU
          <span className="hero-title-accent">AI-to-AI Commerce Platform</span>
        </h1>
        <p className="hero-desc">
          Autonomous commerce where AI agents discover, negotiate, verify, and securely complete purchases.
        </p>
        
        <div className="hero-actions">
          <button onClick={handleStartShopping} className="btn btn-primary btn-glow">
            <Play className="btn-icon" />
            <span>Start Shopping</span>
          </button>
        </div>
      </section>

      {/* Architecture Visualizer Section */}
      <section className="architecture-section">
        <h2 className="section-title">Platform Architecture Flow</h2>
        <p className="section-subtitle">
          Hover over each phase to inspect how SETU securely gates LLM actions from direct API access.
        </p>
        
        <div className="flow-visualizer">
          {steps.map((step, idx) => (
            <React.Fragment key={step.id}>
              <div 
                className={`flow-card ${activeStep === step.id ? 'flow-card-active' : ''}`}
                onMouseEnter={() => setActiveStep(step.id)}
                onMouseLeave={() => setActiveStep(null)}
              >
                <div className="flow-card-header">
                  <div className="flow-card-icon-wrapper">
                    {step.icon}
                  </div>
                  <span className="flow-card-badge">{step.badge}</span>
                </div>
                <h3 className="flow-card-title">
                  <span className="step-number">0{step.id}</span>
                  {step.title}
                </h3>
                <p className="flow-card-desc">{step.desc}</p>
                <div className="flow-card-glow" />
              </div>
              
              {idx < steps.length - 1 && (
                <div className="flow-connector">
                  <div className="connector-line">
                    <div className="connector-pulse" />
                  </div>
                  <ArrowRight className="connector-arrow" />
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* System Status Section */}
      <section className="system-status-section">
        <div className="status-grid">
          <div className="status-item">
            <CheckCircle className="status-icon success" />
            <div className="status-info">
              <h4>Policy Engine</h4>
              <p>Active (Decimal Math Enforced)</p>
            </div>
          </div>
          <div className="status-item">
            <Database className="status-icon success" />
            <div className="status-info">
              <h4>Security Adapter</h4>
              <p>Connected (SQLite Isolation)</p>
            </div>
          </div>
          <div className="status-item">
            <CheckCircle className="status-icon success" />
            <div className="status-info">
              <h4>Razorpay adapter</h4>
              <p>Test Mode (API Gated)</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
