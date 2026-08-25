import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  RefreshCw, 
  Layers, 
  AlertTriangle 
} from 'lucide-react';
import IntentInput from '../components/shopping/IntentInput';
import AgentProcessing from '../components/shopping/AgentProcessing';
import CommerceResult from '../components/shopping/CommerceResult';
import { apiService } from '../services/api';
import type { DemoCommerceResponse } from '../types';
import './Shopping.css';

export default function Shopping() {
  const navigate = useNavigate();
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStep, setCurrentStep] = useState(0); // 0: None, 1: Buyer Agent, 2: Catalog Search, 3: Merchant Agent
  const [result, setResult] = useState<DemoCommerceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleIntentSubmit = (intent: string) => {
    setIsProcessing(true);
    setCurrentStep(1);
    setError(null);
    setResult(null);

    // Call backend API
    const apiPromise = apiService.runDemoCommerceFlow({
      buyer_id: 'demo-buyer-001',
      intent
    });

    // Simulate Agent Step Sequence while API executes
    // Step 1: 900ms
    setTimeout(() => {
      setCurrentStep(2);
      // Step 2: 1000ms
      setTimeout(() => {
        setCurrentStep(3);
        // Step 3: Wait for API to resolve
        apiPromise
          .then((data) => {
            setResult(data);
            setIsProcessing(false);
            setCurrentStep(0);
          })
          .catch((err) => {
            setError(err instanceof Error ? err.message : 'An unknown error occurred.');
            setIsProcessing(false);
            setCurrentStep(0);
          });
      }, 1000);
    }, 900);
  };

  const handleReset = () => {
    setResult(null);
    setError(null);
    setIsProcessing(false);
    setCurrentStep(0);
  };

  return (
    <div className="shopping-page-container animate-fade-in">
      {/* Header Bar */}
      <div className="shopping-header">
        <button onClick={() => navigate('/')} className="back-btn">
          <ArrowLeft className="back-icon" />
          <span>Dashboard</span>
        </button>

        <div className="shopping-header-title">
          <h2>AI Commerce Gateway</h2>
          <p>Autonomous Agent Procurement Pipeline</p>
        </div>

        <div className="shopping-header-status">
          <span className="gateway-dot"></span>
          <span>GATEWAY: ACTIVE</span>
        </div>
      </div>

      {/* Main Flow Content */}
      <div className="shopping-content-area">
        {!isProcessing && !result && !error && (
          <div className="intent-prompt-section">
            <div className="prompt-icon-wrapper animate-float">
              <Layers className="prompt-logo-icon" />
            </div>
            <h3>Describe your procurement intent</h3>
            <p className="prompt-desc">
              State what you need, along with any budget boundaries or conditions. 
              The Buyer Agent will automatically evaluate catalog compatibility and initiate negotiations.
            </p>
            <IntentInput onSubmit={handleIntentSubmit} disabled={isProcessing} />
          </div>
        )}

        {isProcessing && (
          <AgentProcessing currentStep={currentStep} />
        )}

        {error && (
          <div className="error-panel animate-fade-in">
            <AlertTriangle className="error-icon" />
            <h3>Request Evaluation Failed</h3>
            <p className="error-msg">{error}</p>
            <p className="error-tip">
              The SETU secure policy boundaries or network check prevented the negotiation. 
              Please verify your parameters and try again.
            </p>
            <button onClick={handleReset} className="btn btn-primary">
              <RefreshCw className="btn-icon" />
              <span>Retry Search</span>
            </button>
          </div>
        )}

        {result && (
          <CommerceResult 
            result={result} 
            onNext={() => navigate('/negotiation', { state: { result } })} 
          />
        )}
      </div>
    </div>
  );
}
