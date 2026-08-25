import { Brain, Search, Cpu, Check, Loader2 } from 'lucide-react';
import './AgentProcessing.css';

interface AgentProcessingProps {
  currentStep: number; // 1: Buyer Agent, 2: Catalog Search, 3: Merchant Agent
}

export default function AgentProcessing({ currentStep }: AgentProcessingProps) {
  const steps = [
    {
      id: 1,
      label: 'BUYER AGENT',
      desc: 'Analyzing buying intent and setting constraints...',
      icon: <Brain className="step-process-icon" />
    },
    {
      id: 2,
      label: 'CATALOG SEARCH',
      desc: 'Searching matching products and checking inventory...',
      icon: <Search className="step-process-icon" />
    },
    {
      id: 3,
      label: 'MERCHANT AGENT',
      desc: 'Evaluating compatible cross-sells and bundle policies...',
      icon: <Cpu className="step-process-icon" />
    }
  ];

  return (
    <div className="processing-container animate-fade-in">
      <div className="processing-header">
        <Loader2 className="processing-spinner" />
        <div>
          <h3>Orchestrating Autonomous AI Agents</h3>
          <p>Processing request through the secure SETU Trust Layer...</p>
        </div>
      </div>

      <div className="processing-steps-list">
        {steps.map((step) => {
          const isCompleted = currentStep > step.id;
          const isActive = currentStep === step.id;
          const isPending = currentStep < step.id;

          let stepClass = 'process-step-row';
          if (isCompleted) stepClass += ' process-completed';
          if (isActive) stepClass += ' process-active';
          if (isPending) stepClass += ' process-pending';

          return (
            <div key={step.id} className={stepClass}>
              <div className="process-status-col">
                {isCompleted ? (
                  <div className="status-indicator completed">
                    <Check className="check-icon" />
                  </div>
                ) : isActive ? (
                  <div className="status-indicator active">
                    <Loader2 className="spinner-icon-small" />
                  </div>
                ) : (
                  <div className="status-indicator pending">
                    <span className="dot-icon" />
                  </div>
                )}
                {step.id < steps.length && <div className="step-connector-line" />}
              </div>

              <div className="process-details-col">
                <div className="process-icon-wrapper">{step.icon}</div>
                <div className="process-text-content">
                  <h4>{step.label}</h4>
                  <p>{step.desc}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
