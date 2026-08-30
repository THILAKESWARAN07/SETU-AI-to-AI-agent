import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  Layers, 
  Loader2, 
  ShieldAlert, 
  User, 
  Store, 
  Clock, 
  Lock, 
  AlertTriangle,
  ChevronRight,
  Shield,
  Activity,
  CheckCircle2
} from 'lucide-react';
import { apiService } from '../services/api';
import type { DemoCommerceResponse } from '../types';
import './Negotiation.css';

const LOG_TEMPLATES = [
  { time: 0.4, text: "Intent payload registered" },
  { time: 0.8, text: "Budget constraints extracted" },
  { time: 1.2, text: "Merchant policy loaded" },
  { time: 1.7, text: "Buyer Agent runtime initialized" },
  { time: 2.4, text: "Merchant Agent runtime initialized" },
  { time: 3.1, text: "SETU trust sandbox secured" },
  { time: 3.8, text: "Establishing negotiation channel..." },
  { time: 5.0, text: "Synchronizing agent knowledge boundaries..." },
  { time: 6.5, text: "Spawning secure turn-loop controllers..." },
  { time: 8.0, text: "Handshaking with Gemini API service..." },
  { time: 10.0, text: "Server load high. Maintaining secure agent session..." },
  { time: 12.5, text: "Retrying secure channel verification..." },
  { time: 15.0, text: "Maintaining active state..." }
];

const stages = [
  "Procurement intent received",
  "Purchase constraints parsed",
  "Catalog context loaded",
  "Initializing Buyer Agent",
  "Initializing Merchant Agent",
  "Establishing SETU policy sandbox",
  "Connecting to live LLM provider",
  "Starting negotiation runtime"
];

const stageTimes = [0.5, 1.2, 2.0, 3.0, 4.0, 5.2, 6.5, 8.0];

const formatLogTime = (secs: number) => {
  const rounded = secs.toFixed(1);
  return `[${rounded.padStart(4, '0')}s]`;
};

export default function Negotiation() {
  const navigate = useNavigate();
  const location = useLocation();
  
  const stateIntent = location.state?.intent as string | undefined;
  const stateBudget = location.state?.budget as number | undefined;
  const initialResult = location.state?.result as DemoCommerceResponse | undefined;

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DemoCommerceResponse | null>(null);
  const [visibleEventsCount, setVisibleEventsCount] = useState(0);
  
  // Track animation state parameters
  const [animatedRounds, setAnimatedRounds] = useState(1);
  const [animatedToolsCount, setAnimatedToolsCount] = useState(0);
  const [animatedState, setAnimatedState] = useState('IN_PROGRESS');
  const [animatedPolicy, setAnimatedPolicy] = useState('PENDING');
  const [animatedBuyerStatus, setAnimatedBuyerStatus] = useState('ACTIVE');
  const [animatedMerchantStatus, setAnimatedMerchantStatus] = useState('ACTIVE');
  const [animatedPrice, setAnimatedPrice] = useState('0.00');

  const animationTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Custom states and refs for interactive progressive loading
  const [elapsed, setElapsed] = useState(0);
  const loadingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  // 1. Fetch result if not present (using intent and budget from state)
  useEffect(() => {
    if (initialResult) {
      setResult(initialResult);
      startTimelineAnimation(initialResult);
      return;
    }

    if (!stateIntent) return;

    setIsLoading(true);
    setError(null);
    setResult(null);

    apiService.runDemoCommerceFlow({
      buyer_id: 'demo-buyer-001',
      intent: stateIntent,
      budget: stateBudget ? stateBudget : 2000.00
    })
      .then((data) => {
        setResult(data);
        setIsLoading(false);
        startTimelineAnimation(data);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'An error occurred during negotiation.');
        setIsLoading(false);
      });
  }, [stateIntent, stateBudget, initialResult]);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (animationTimer.current) clearInterval(animationTimer.current);
    };
  }, []);

  // Manage initialization loading timer
  useEffect(() => {
    if (isLoading) {
      setElapsed(0);
      loadingTimer.current = setInterval(() => {
        setElapsed((prev) => prev + 0.1);
      }, 100);
    } else {
      if (loadingTimer.current) {
        clearInterval(loadingTimer.current);
        loadingTimer.current = null;
      }
    }

    return () => {
      if (loadingTimer.current) {
        clearInterval(loadingTimer.current);
      }
    };
  }, [isLoading]);

  // Scroll terminal logs to bottom when log count changes
  const visibleLogsCount = LOG_TEMPLATES.filter(log => elapsed >= log.time).length;
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [visibleLogsCount]);

  // 2. Timeline items compiler function
  const compileTimelineEvents = (res: DemoCommerceResponse) => {
    const events: any[] = [];
    const baseTime = new Date();

    const getOffsetTime = (secsOffset: number) => {
      const t = new Date(baseTime.getTime() + secsOffset * 1000);
      return t.toLocaleTimeString();
    };

    // Event 1: User Intent
    events.push({
      id: 'intent',
      type: 'intent',
      actor: 'USER',
      label: 'USER INTENT REGISTERED',
      message: `Procurement request received: "${res.intent}"`,
      subtext: `Target budget boundary limit set to ₹${parseFloat(res.original_amount).toLocaleString('en-IN')}`,
      timestamp: getOffsetTime(0),
      toolsUsedCount: 0,
      round: 1,
      buyerStatus: 'ACTIVE',
      merchantStatus: 'ACTIVE',
      currentState: 'IN_PROGRESS',
      policyVerdict: 'PENDING',
      currentPrice: '0.00'
    });

    // Event 2: Buyer Agent Init
    events.push({
      id: 'buyer_init',
      type: 'agent_start',
      actor: 'BUYER_AGENT',
      label: 'BUYER AGENT INITIALIZED',
      message: `Buyer Agent configured objective: "${res.buyer_objective || 'Procure matching catalog items under budget cap.'}"`,
      subtext: `Provider Adapter: ${res.provider || 'Gemini'} | Model: ${res.model}`,
      timestamp: getOffsetTime(1),
      toolsUsedCount: 0,
      round: 1,
      buyerStatus: 'ACTIVE',
      merchantStatus: 'ACTIVE',
      currentState: 'IN_PROGRESS',
      policyVerdict: 'PENDING',
      currentPrice: '0.00'
    });

    // Event 3: Catalog Search Tool
    events.push({
      id: 'tool_search',
      type: 'tool_call',
      actor: 'BUYER_AGENT',
      label: 'CATALOG SEARCH',
      message: 'Invoked allowed tool `search_catalog` to scan inventory listings.',
      subtext: `Result: Identified product ID ${res.selected_product_id} (Wireless Earbuds) priced at ₹${parseFloat(res.original_amount).toLocaleString('en-IN')}.`,
      timestamp: getOffsetTime(2),
      toolsUsedCount: 1,
      round: 1,
      buyerStatus: 'ACTIVE',
      merchantStatus: 'ACTIVE',
      currentState: 'IN_PROGRESS',
      policyVerdict: 'PENDING',
      currentPrice: '0.00'
    });

    // Event 4: Product Specifications Checked
    events.push({
      id: 'tool_details',
      type: 'tool_call',
      actor: 'BUYER_AGENT',
      label: 'PRODUCT INSPECTION',
      message: 'Invoked allowed tool `get_product_details` on candidate item.',
      subtext: `Read specifications, stock availability (${res.catalog_search_results?.[0]?.inventory ?? 12} units), and base cost fields.`,
      timestamp: getOffsetTime(3),
      toolsUsedCount: 2,
      round: 1,
      buyerStatus: 'ACTIVE',
      merchantStatus: 'ACTIVE',
      currentState: 'IN_PROGRESS',
      policyVerdict: 'PENDING',
      currentPrice: '0.00'
    });

    // Event 5: Budget verification check
    events.push({
      id: 'tool_budget',
      type: 'tool_call',
      actor: 'BUYER_AGENT',
      label: 'BUDGET CHECK',
      message: 'Invoked allowed tool `evaluate_budget` to verify price capability.',
      subtext: 'Result: Catalog price satisfies budget limit rules. Strategic bid pricing initiated.',
      timestamp: getOffsetTime(4),
      toolsUsedCount: 3,
      round: 1,
      buyerStatus: 'ACTIVE',
      merchantStatus: 'ACTIVE',
      currentState: 'IN_PROGRESS',
      policyVerdict: 'PENDING',
      currentPrice: '0.00'
    });

    let currentToolsCount = 3;
    let roundIndex = 1;

    // Event 6: Bidding Rounds Loop
    res.negotiation_history.forEach((turn, idx) => {
      roundIndex = turn.round;
      const turnTimeOffset = 5 + idx * 2;

      if (turn.buyer_offer) {
        currentToolsCount += (turn.buyer_offer.tools_used?.length || 0);
        events.push({
          id: `buyer_bid_${idx}`,
          type: 'buyer_offer',
          actor: 'BUYER_AGENT',
          label: `ROUND ${turn.round}: BUYER BID PROPOSAL`,
          message: turn.reason || `Proposed purchasing offer.`,
          subtext: `Bid Offer: ₹${parseFloat(turn.buyer_offer.final_amount).toLocaleString('en-IN')} (Confidence: ${(turn.buyer_offer.confidence * 100).toFixed(0)}%)`,
          timestamp: getOffsetTime(turnTimeOffset),
          toolsUsedCount: currentToolsCount,
          round: turn.round,
          buyerStatus: 'ACTIVE',
          merchantStatus: 'ACTIVE',
          currentState: 'IN_PROGRESS',
          policyVerdict: 'PENDING',
          currentPrice: turn.buyer_offer.final_amount
        });

        events.push({
          id: `policy_buyer_${idx}`,
          type: 'policy_check',
          actor: 'SETU_POLICY',
          label: `ROUND ${turn.round}: POLICY VERIFICATION`,
          message: 'PolicyEngine executing budget limits compliance check.',
          subtext: `Verdict: APPROVED (Bid ₹${parseFloat(turn.buyer_offer.final_amount).toLocaleString('en-IN')} <= budget limit)`,
          timestamp: getOffsetTime(turnTimeOffset + 0.5),
          toolsUsedCount: currentToolsCount,
          round: turn.round,
          buyerStatus: 'ACTIVE',
          merchantStatus: 'ACTIVE',
          currentState: 'IN_PROGRESS',
          policyVerdict: 'APPROVED',
          currentPrice: turn.buyer_offer.final_amount
        });
      }

      if (turn.merchant_offer) {
        currentToolsCount += (turn.merchant_offer.tools_used?.length || 0);
        const isMerchantAccepted = turn.accepted;
        
        events.push({
          id: `merchant_counter_${idx}`,
          type: 'merchant_offer',
          actor: 'MERCHANT_AGENT',
          label: isMerchantAccepted ? `ROUND ${turn.round}: MERCHANT ACCEPTS` : `ROUND ${turn.round}: MERCHANT COUNTER`,
          message: turn.reason || 'Evaluated buyer proposal.',
          subtext: `${isMerchantAccepted ? 'Acceptance' : 'Counter'} Price: ₹${parseFloat(turn.merchant_offer.offered_amount).toLocaleString('en-IN')} (Confidence: ${(turn.merchant_offer.confidence * 100).toFixed(0)}%)`,
          timestamp: getOffsetTime(turnTimeOffset + 1),
          toolsUsedCount: currentToolsCount,
          round: turn.round,
          buyerStatus: isMerchantAccepted ? 'ACCEPTED' : 'ACTIVE',
          merchantStatus: isMerchantAccepted ? 'ACCEPTED' : 'ACTIVE',
          currentState: isMerchantAccepted ? 'AGREED' : 'IN_PROGRESS',
          policyVerdict: 'PENDING',
          currentPrice: turn.merchant_offer.offered_amount
        });

        events.push({
          id: `policy_merchant_${idx}`,
          type: 'policy_check',
          actor: 'SETU_POLICY',
          label: `ROUND ${turn.round}: POLICY VERIFICATION`,
          message: 'PolicyEngine executing margin boundaries check on merchant response.',
          subtext: `Verdict: APPROVED (Margin check: ${res.margin_percent}% passes min margin guidelines)`,
          timestamp: getOffsetTime(turnTimeOffset + 1.5),
          toolsUsedCount: currentToolsCount,
          round: turn.round,
          buyerStatus: isMerchantAccepted ? 'ACCEPTED' : 'ACTIVE',
          merchantStatus: isMerchantAccepted ? 'ACCEPTED' : 'ACTIVE',
          currentState: isMerchantAccepted ? 'AGREED' : 'IN_PROGRESS',
          policyVerdict: 'APPROVED',
          currentPrice: turn.merchant_offer.offered_amount
        });
      }
    });

    // Event 7: Final locked agreement / Rejection
    const isDealApproved = res.decision === 'APPROVED';
    const totalOffset = 5 + res.negotiation_history.length * 2;
    events.push({
      id: 'final_verdict',
      type: 'final_verdict',
      actor: 'SYSTEM',
      label: isDealApproved ? 'AGREEMENT LOCKED' : 'NEGOTIATION CLOSED',
      message: isDealApproved 
        ? `Policy Engine approved final agreement value of ₹${parseFloat(res.final_amount).toLocaleString('en-IN')}.`
        : `Policy Engine terminated transaction. Reasons: ${res.reasons.join(', ')}`,
      subtext: isDealApproved 
        ? `PurchaseRequest (ID ${res.purchase_request_id}) generated. Safe handoff to Payment Service verified.`
        : 'Active checkout session aborted due to policy boundary violation.',
      timestamp: getOffsetTime(totalOffset),
      toolsUsedCount: currentToolsCount,
      round: roundIndex,
      buyerStatus: isDealApproved ? 'ACCEPTED' : 'FAILED',
      merchantStatus: isDealApproved ? 'ACCEPTED' : 'FAILED',
      currentState: isDealApproved ? 'AGREED' : 'REJECTED',
      policyVerdict: isDealApproved ? 'APPROVED' : 'BLOCKED',
      currentPrice: res.final_amount,
      isError: !isDealApproved
    });

    return events;
  };

  // 3. Start timeline step-by-step animation
  const startTimelineAnimation = (res: DemoCommerceResponse) => {
    if (animationTimer.current) clearInterval(animationTimer.current);
    
    setVisibleEventsCount(1);
 
    const events = compileTimelineEvents(res);
    
    // Set initial event state values
    updateLiveMetrics(events[0]);
 
    let currentIndex = 1;
    animationTimer.current = setInterval(() => {
      if (currentIndex >= events.length) {
        clearInterval(animationTimer.current!);
        animationTimer.current = null;
        return;
      }
      
      setVisibleEventsCount(currentIndex + 1);
      updateLiveMetrics(events[currentIndex]);
      currentIndex++;
    }, 1000);
  };

  const updateLiveMetrics = (evt: any) => {
    setAnimatedRounds(evt.round);
    setAnimatedToolsCount(evt.toolsUsedCount);
    setAnimatedState(evt.currentState);
    setAnimatedPolicy(evt.policyVerdict);
    setAnimatedBuyerStatus(evt.buyerStatus);
    setAnimatedMerchantStatus(evt.merchantStatus);
    setAnimatedPrice(evt.currentPrice);
  };

  const handleCheckout = () => {
    if (!result) return;
    navigate('/payment', { state: { result } });
  };

  const handleReset = () => {
    navigate('/shopping');
  };



  // 4. UI Rendering States
  if (isLoading) {
    const buyerActive = elapsed >= 3.0;
    const buyerStatusLabel = elapsed < 3.0 ? "PENDING" : elapsed < 3.6 ? "INITIALIZING" : "ACTIVE";

    const merchantActive = elapsed >= 4.0;
    const merchantStatusLabel = elapsed < 4.0 ? "PENDING" : elapsed < 4.8 ? "INITIALIZING" : "ACTIVE";

    const trustActive = elapsed >= 5.2;
    const trustStatusLabel = elapsed < 5.2 ? "PENDING" : elapsed < 6.2 ? "SECURING" : "ENFORCED";

    const visibleLogs = LOG_TEMPLATES.filter(log => elapsed >= log.time);
    
    // Progress calculation
    let progressPercent = 0;
    if (elapsed <= 8.0) {
      progressPercent = (elapsed / 8.0) * 90;
    } else {
      progressPercent = 90 + 5 * (1 - Math.exp(-(elapsed - 8.0) / 10));
    }

    const currentStageIndex = stageTimes.findIndex(t => elapsed < t);
    const currentStageNumber = currentStageIndex === -1 ? 8 : currentStageIndex + 1;

    const totalChars = 20;
    const filledChars = Math.min(totalChars, Math.floor((progressPercent / 100) * totalChars));
    const emptyChars = totalChars - filledChars;
    const charBar = '█'.repeat(filledChars) + '░'.repeat(emptyChars);

    return (
      <div className="negotiation-page-container container animate-fade-in" style={{ minHeight: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="loader-panel-container">
          <div>
            <h3 className="loader-panel-title">
              Spawning Autonomous AI Agents
            </h3>
            <p className="loader-panel-subtitle">
              Setting up policy sandboxes, parsing purchase constraints, and initiating negotiation turn loops.
            </p>
          </div>

          {/* Central Visualization */}
          <div className="visualizer-wrapper">
            {/* Buyer Agent Node */}
            <div className={`visual-node buyer-node ${buyerActive ? 'active-node' : ''}`}>
              <User className="visual-node-icon" />
              <span className="visual-node-label">BUYER AGENT</span>
              <span className="visual-node-status">{buyerStatusLabel}</span>
            </div>

            {/* Connector Left */}
            <div className="visual-connector-line">
              {buyerActive && <div className="connector-pulse-dot pulse-right" style={{ opacity: 1 }} />}
            </div>

            {/* SETU Trust Layer Node */}
            <div className={`visual-node trust-node ${trustActive ? 'active-node' : ''}`}>
              <Shield className="visual-node-icon" />
              <span className="visual-node-label">SETU TRUST LAYER</span>
              <span className="visual-node-status">{trustStatusLabel}</span>
            </div>

            {/* Connector Right */}
            <div className="visual-connector-line">
              {merchantActive && <div className="connector-pulse-dot pulse-left" style={{ opacity: 1 }} />}
            </div>

            {/* Merchant Agent Node */}
            <div className={`visual-node merchant-node ${merchantActive ? 'active-node' : ''}`}>
              <Store className="visual-node-icon" />
              <span className="visual-node-label">MERCHANT AGENT</span>
              <span className="visual-node-status">{merchantStatusLabel}</span>
            </div>
          </div>

          {/* Main Grid: Left Stages, Right Terminal */}
          <div className="loader-grid">
            <div className="stages-list-container">
              {stages.map((stage, idx) => {
                const t = stageTimes[idx];
                let status: 'completed' | 'active' | 'pending' = 'pending';
                if (elapsed >= t) {
                  status = 'completed';
                } else {
                  const prevCompleted = idx === 0 || elapsed >= stageTimes[idx - 1];
                  if (prevCompleted) {
                    status = 'active';
                  }
                }

                return (
                  <div key={idx} className={`stage-item stage-${status}`}>
                    <div className="stage-indicator">
                      {status === 'completed' && <CheckCircle2 className="stage-indicator-check" />}
                      {status === 'active' && <Loader2 className="stage-indicator-active" style={{ width: '16px', height: '16px' }} />}
                      {status === 'pending' && <div className="stage-indicator-dot" />}
                    </div>
                    <span className="stage-label">{stage}</span>
                  </div>
                );
              })}
            </div>

            <div className="terminal-console-container">
              <div className="terminal-header">
                <div className="terminal-dots">
                  <div className="terminal-dot dot-red" />
                  <div className="terminal-dot dot-yellow" />
                  <div className="terminal-dot dot-green" />
                </div>
                <span className="terminal-title">AGENT COMPILER SHELL</span>
              </div>
              <div className="terminal-log-area">
                {visibleLogs.map((log, idx) => (
                  <div key={idx} className="terminal-log-line animate-fade-in">
                    <span className="terminal-log-time">{formatLogTime(log.time)}</span>
                    <span className="terminal-log-text">{log.text}</span>
                  </div>
                ))}
                <div ref={terminalEndRef} />
                <span className="terminal-caret" />
              </div>
            </div>
          </div>

          {/* Bottom Progress Bar Panel */}
          <div className="progress-panel-container">
            <div className="progress-header-info">
              <span className="progress-title-text">INITIALIZING AGENT RUNTIME</span>
              <span className="progress-ratio-text">STAGE {currentStageNumber}/8</span>
            </div>
            
            <div className="retro-progress-bar">
              [{charBar}]
            </div>

            <div className="progress-bar-graphic-track">
              <div className="progress-bar-graphic-fill" style={{ width: `${progressPercent}%` }} />
            </div>

            <div className="progress-footer-info">
              <span className="progress-footer-status">
                {currentStageNumber <= 8 ? stages[currentStageNumber - 1] : 'Finalizing negotiation handshake...'}
              </span>
              <span className="progress-elapsed-timer">ELAPSED: {elapsed.toFixed(1)}s</span>
            </div>
          </div>

          {/* Keep Alive Info Message for longer loading */}
          {elapsed >= 8.0 && (
            <div className="keep-alive-banner">
              <Activity className="keep-alive-icon" style={{ flexShrink: 0 }} />
              <span>Live AI runtime is still processing. Maintaining secure agent session...</span>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="negotiation-page-container container animate-fade-in" style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="error-panel" style={{ maxWidth: '500px' }}>
          <AlertTriangle className="error-icon" />
          <h3>Negotiation Session Failed</h3>
          <p className="error-msg">{error}</p>
          <p className="error-tip">
            The Gemini API key was not configured, or a network request failed. Fallback to mock settings or check credentials.
          </p>
          <button onClick={handleReset} className="btn btn-primary" style={{ marginTop: '16px' }}>
            <ArrowLeft className="btn-icon" />
            <span>Go to Shopping</span>
          </button>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="negotiation-page-container container animate-fade-in">
        <div className="empty-negotiation-state">
          <Layers className="empty-state-icon animate-float" />
          <h3>No Active Negotiation Session</h3>
          <p className="empty-state-desc">
            To view the AI negotiation flow, you must first describe a purchase intent and search the catalog.
          </p>
          <button onClick={handleReset} className="btn btn-primary">
            <ArrowLeft className="btn-icon" />
            <span>Go to Shopping</span>
          </button>
        </div>
      </div>
    );
  }

  const events = compileTimelineEvents(result);
  const visibleEvents = events.slice(0, visibleEventsCount);
  const finalVerdictEvent = visibleEvents.find(e => e.type === 'final_verdict');
  const isFinalVerdictVisible = !!finalVerdictEvent;
  const isDealApproved = result.decision === 'APPROVED';

  // Filter events per column
  const buyerEvents = visibleEvents.filter(e => e.actor === 'BUYER_AGENT' || e.type === 'intent');
  const merchantEvents = visibleEvents.filter(e => e.actor === 'MERCHANT_AGENT');

  // Verify constraints checkpoints dynamically
  const isProviderError = result.decision === 'ERROR' || result.execution_mode === 'PROVIDER ERROR';
  
  return (
    <div className="negotiation-page-container container animate-fade-in" style={{ paddingBottom: '120px' }}>
      {/* Header Back Link */}
      <div className="negotiation-page-header">
        <button onClick={handleReset} className="back-to-deal-btn">
          <ArrowLeft className="back-icon" />
          <span>Back to Procurement Hub</span>
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span className={`system-status-tag font-mono ${result.execution_mode === 'LIVE LLM' ? 'live-llm-tag' : result.execution_mode === 'PROVIDER ERROR' ? 'error-tag' : 'mock-tag'}`} style={{
            background: result.execution_mode === 'LIVE LLM' ? 'rgba(16, 185, 129, 0.15)' : result.execution_mode === 'PROVIDER ERROR' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(107, 114, 128, 0.15)',
            color: result.execution_mode === 'LIVE LLM' ? '#10b981' : result.execution_mode === 'PROVIDER ERROR' ? '#ef4444' : '#9ca3af',
            border: result.execution_mode === 'LIVE LLM' ? '1px solid rgba(16, 185, 129, 0.3)' : result.execution_mode === 'PROVIDER ERROR' ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid rgba(107, 114, 128, 0.3)'
          }}>
            MODE: {result.execution_mode || 'OFFLINE MOCK'}
          </span>
          <span className="system-status-tag font-mono" style={{ color: 'var(--primary)', borderColor: 'rgba(100, 75, 255, 0.3)', background: 'rgba(100, 75, 255, 0.05)' }}>
            ENFORCING PROPOSER-DECIDER SEGREGATION
          </span>
        </div>
      </div>

      {/* Critical Provider Error Warning Banner */}
      {isProviderError && (
        <div className="error-panel animate-scale-up" style={{
          backgroundColor: 'rgba(239, 68, 68, 0.05)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: '12px',
          padding: '20px 24px',
          marginBottom: '28px',
          display: 'flex',
          gap: '16px',
          alignItems: 'flex-start'
        }}>
          <ShieldAlert className="error-icon" style={{ color: '#ef4444', flexShrink: 0, marginTop: '2px' }} />
          <div>
            <h4 style={{ color: '#ef4444', fontSize: '1rem', fontWeight: 700, margin: 0 }}>LLM Provider Connection Interrupted</h4>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: '1.4', marginTop: '6px', marginBottom: 0 }}>
              The runtime encountered a failure while calling the live provider API.
              <code className="font-mono" style={{ display: 'block', background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '4px', marginTop: '8px', color: '#fca5a5' }}>
                Reason: {result.reasons.join(', ')}
              </code>
            </p>
          </div>
        </div>
      )}

      {/* Main Content Layout Grid */}
      <div className="negotiation-grid">
        
        {/* Left Column: Flow Timeline Split Panels */}
        <div className="negotiation-main-col" style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
          
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '20px'
          }}>
            {/* COLUMN 1: BUYER AGENT */}
            <div className="agent-column-card" style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              minHeight: '400px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#3b82f6', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <User style={{ width: '14px', height: '14px' }} />
                  BUYER AGENT
                </span>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6', borderRadius: '4px' }}>
                  {animatedBuyerStatus}
                </span>
              </div>
              
              <div style={{ fontSize: '0.78rem', background: 'rgba(255,255,255,0.02)', padding: '10px', borderRadius: '6px', borderLeft: '2px solid #3b82f6' }}>
                <span style={{ fontWeight: 700, display: 'block', color: 'var(--text-dimmed)', fontSize: '0.7rem', textTransform: 'uppercase' }}>Objective:</span>
                <span style={{ color: 'var(--text-muted)' }}>{result.buyer_objective}</span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-dimmed)' }}>TRACES RECORDED</span>
                
                {buyerEvents.length === 0 ? (
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-dimmed)', fontStyle: 'italic' }}>Initializing context...</span>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {buyerEvents.map((evt) => (
                      <div key={evt.id} style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '10px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span className="font-mono" style={{ fontSize: '0.65rem', fontWeight: 700, color: '#3b82f6' }}>{evt.label}</span>
                          <span className="font-mono" style={{ fontSize: '0.6rem', color: 'var(--text-dimmed)' }}>{evt.timestamp}</span>
                        </div>
                        <p style={{ fontSize: '0.8rem', color: 'var(--text-main)', margin: 0 }}>{evt.message}</p>
                        {evt.subtext && (
                          <div className="font-mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', background: 'rgba(0,0,0,0.1)', padding: '4px 8px', borderRadius: '4px', marginTop: '6px' }}>
                            {evt.subtext.startsWith('Bid Offer') ? 'Bid: ' + evt.subtext.split('Bid Offer: ')[1] : evt.subtext}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* COLUMN 2: MERCHANT AGENT */}
            <div className="agent-column-card" style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              minHeight: '400px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#f59e0b', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Store style={{ width: '14px', height: '14px' }} />
                  MERCHANT AGENT
                </span>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b', borderRadius: '4px' }}>
                  {animatedMerchantStatus}
                </span>
              </div>

              <div style={{ fontSize: '0.78rem', background: 'rgba(255,255,255,0.02)', padding: '10px', borderRadius: '6px', borderLeft: '2px solid #f59e0b' }}>
                <span style={{ fontWeight: 700, display: 'block', color: 'var(--text-dimmed)', fontSize: '0.7rem', textTransform: 'uppercase' }}>Objective:</span>
                <span style={{ color: 'var(--text-muted)' }}>{result.merchant_objective}</span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-dimmed)' }}>TRACES RECORDED</span>
                
                {merchantEvents.length === 0 ? (
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-dimmed)', fontStyle: 'italic' }}>Awaiting buyer proposal...</span>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {merchantEvents.map((evt) => (
                      <div key={evt.id} style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '10px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span className="font-mono" style={{ fontSize: '0.65rem', fontWeight: 700, color: '#f59e0b' }}>{evt.label}</span>
                          <span className="font-mono" style={{ fontSize: '0.6rem', color: 'var(--text-dimmed)' }}>{evt.timestamp}</span>
                        </div>
                        <p style={{ fontSize: '0.8rem', color: 'var(--text-main)', margin: 0 }}>{evt.message}</p>
                        {evt.subtext && (
                          <div className="font-mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', background: 'rgba(0,0,0,0.1)', padding: '4px 8px', borderRadius: '4px', marginTop: '6px' }}>
                            {evt.subtext.startsWith('Counter Price') ? 'Counter: ' + evt.subtext.split('Counter Price: ')[1] : evt.subtext}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* COLUMN 3: SETU POLICY ENGINE */}
            <div className="agent-column-card" style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              minHeight: '400px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#10b981', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Shield style={{ width: '14px', height: '14px' }} />
                  SETU POLICY ENGINE
                </span>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>
                  {animatedPolicy}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-dimmed)' }}>DETERMINISTIC TRUST GATES</span>

                {/* Gate 1: Budget Cap Verification */}
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px', borderRadius: '6px' }}>
                  {visibleEvents.length > 3 ? (
                    <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0, marginTop: '2px' }} />
                  ) : (
                    <Clock style={{ width: '16px', height: '16px', color: '#9ca3af', flexShrink: 0, marginTop: '2px' }} />
                  )}
                  <div>
                    <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Budget Limit Guard</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      {visibleEvents.length > 3 ? `Max cap: ₹${parseFloat(result.original_amount).toLocaleString('en-IN')} check verified` : 'Awaiting initialization'}
                    </span>
                  </div>
                </div>

                {/* Gate 2: Merchant Margin Floor */}
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px', borderRadius: '6px' }}>
                  {merchantEvents.length > 0 ? (
                    <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0, marginTop: '2px' }} />
                  ) : (
                    <Clock style={{ width: '16px', height: '16px', color: '#9ca3af', flexShrink: 0, marginTop: '2px' }} />
                  )}
                  <div>
                    <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Margin Constraint Guard</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      {merchantEvents.length > 0 ? `Calculated margin: ${result.margin_percent}% verified` : 'Awaiting counter evaluation'}
                    </span>
                  </div>
                </div>

                {/* Gate 3: Rounds Cap Boundary */}
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px', borderRadius: '6px' }}>
                  <Activity style={{ width: '16px', height: '16px', color: '#f59e0b', flexShrink: 0, marginTop: '2px' }} />
                  <div>
                    <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Rounds Safety Limit</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      Turn progress: {animatedRounds} / 4 rounds cap safety
                    </span>
                  </div>
                </div>

                {/* Gate 4: Tool Allowlist Isolation */}
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px', borderRadius: '6px' }}>
                  <Lock style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0, marginTop: '2px' }} />
                  <div>
                    <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Payment System Isolation</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      Registry tool bounds confirmed safe (Razorpay isolated)
                    </span>
                  </div>
                </div>

                {/* Gate 5: Final Policy Engine Verdict */}
                {isFinalVerdictVisible && (
                  <div style={{ 
                    marginTop: '10px',
                    background: isDealApproved ? 'rgba(16, 185, 129, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                    border: isDealApproved ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
                    padding: '12px',
                    borderRadius: '8px',
                    textAlign: 'center'
                  }}>
                    <span className="font-mono" style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-dimmed)', display: 'block' }}>POLICY ENGINE VERDICT</span>
                    <span className="font-mono" style={{ fontSize: '1.2rem', fontWeight: 900, color: isDealApproved ? '#10b981' : '#ef4444' }}>
                      {result.decision}
                    </span>
                  </div>
                )}

              </div>
            </div>
          </div>

        </div>

        {/* Right Column: Agent Session Panel & Deal checkout */}
        <div className="negotiation-sidebar-col" style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
          
          {/* Agent Session Panel */}
          <div 
            className="agent-session-panel-card animate-fade-in"
            style={{
              backgroundColor: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px'
            }}
          >
            <h3 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
              Agent Session Metrics
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Session Mode:</span>
                <span className="font-mono" style={{ 
                  fontWeight: 700, 
                  color: result.execution_mode === 'LIVE LLM' ? '#10b981' : result.execution_mode === 'PROVIDER ERROR' ? '#ef4444' : '#9ca3af' 
                }}>
                  {result.execution_mode || 'OFFLINE MOCK'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>LLM Provider:</span>
                <span style={{ fontWeight: 500, color: 'var(--text-main)' }}>
                  {result.provider || 'MockProvider'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>LLM Model:</span>
                <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>
                  {result.model || 'mock-model-v2'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Session ID:</span>
                <span className="font-mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {result.session_id || 'session_mock'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Start Time:</span>
                <span className="font-mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {result.start_time ? new Date(result.start_time).toLocaleTimeString() : '--'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>End Time:</span>
                <span className="font-mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {isFinalVerdictVisible && result.completion_time ? new Date(result.completion_time).toLocaleTimeString() : '--'}
                </span>
              </div>
              
              <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)' }} />

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Buyer Status:</span>
                <span className="font-mono" style={{ 
                  fontWeight: 700, 
                  color: animatedBuyerStatus === 'ACCEPTED' ? '#10b981' : animatedBuyerStatus === 'FAILED' ? '#ef4444' : '#3b82f6' 
                }}>
                  {animatedBuyerStatus}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Merchant Status:</span>
                <span className="font-mono" style={{ 
                  fontWeight: 700, 
                  color: animatedMerchantStatus === 'ACCEPTED' ? '#10b981' : animatedMerchantStatus === 'FAILED' ? '#ef4444' : '#f59e0b' 
                }}>
                  {animatedMerchantStatus}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Active Rounds:</span>
                <span className="font-mono" style={{ fontWeight: 700 }}>
                  {animatedRounds} / 4
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Tool Calls:</span>
                <span className="font-mono" style={{ fontWeight: 700, color: 'var(--primary)' }}>
                  {animatedToolsCount} calls
                </span>
              </div>

              <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)' }} />

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Negotiation State:</span>
                <span className="font-mono" style={{ 
                  fontWeight: 700,
                  color: animatedState === 'AGREED' ? '#10b981' : animatedState === 'REJECTED' ? '#ef4444' : 'var(--text-muted)'
                }}>
                  {animatedState}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Policy Verdict:</span>
                <span className="font-mono" style={{ 
                  fontWeight: 700, 
                  color: animatedPolicy === 'APPROVED' ? '#10b981' : animatedPolicy === 'BLOCKED' ? '#ef4444' : '#f59e0b' 
                }}>
                  {animatedPolicy}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Final Agreement:</span>
                <span className="font-mono" style={{ fontWeight: 700, color: '#10b981' }}>
                  {animatedPrice !== '0.00' ? `₹${parseFloat(animatedPrice).toLocaleString('en-IN')}` : '--'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Payment Status:</span>
                <span className="font-mono" style={{ fontWeight: 700, color: isFinalVerdictVisible && isDealApproved ? '#f59e0b' : 'var(--text-dimmed)' }}>
                  {isFinalVerdictVisible && isDealApproved ? 'PENDING' : '--'}
                </span>
              </div>
            </div>
          </div>

          {/* Checkout Card (visible at the end of the simulation) */}
          {isFinalVerdictVisible && (
            <div 
              className="checkout-deal-card animate-scale-up"
              style={{
                backgroundColor: 'var(--bg-card)',
                border: isDealApproved ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '12px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '16px',
                boxShadow: isDealApproved ? '0 8px 24px rgba(16, 185, 129, 0.05)' : '0 8px 24px rgba(239, 68, 68, 0.05)'
              }}
            >
              <h4 style={{ fontSize: '0.95rem', fontWeight: 700 }}>
                {isDealApproved ? 'Procurement Agreement Approved' : 'Transaction Boundary Blocked'}
              </h4>
              
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Negotiated Deal Value:</span>
                <span className="font-mono" style={{ fontSize: '1.2rem', fontWeight: 700, color: isDealApproved ? '#10b981' : '#ef4444' }}>
                  ₹{parseFloat(result.final_amount).toLocaleString('en-IN')}
                </span>
              </div>

              {!isDealApproved ? (
                <div style={{ 
                  backgroundColor: 'rgba(239, 68, 68, 0.04)',
                  border: '1px solid rgba(239, 68, 68, 0.2)',
                  borderRadius: '8px',
                  padding: '16px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                  fontSize: '0.8rem',
                  lineHeight: '1.4'
                }}>
                  <div>
                    <span style={{ fontWeight: 700, display: 'block', fontSize: '0.7rem', textTransform: 'uppercase', color: '#ef4444', letterSpacing: '0.05em', marginBottom: '2px' }}>What Happened</span>
                    <span style={{ color: 'var(--text-main)', fontWeight: 600 }}>REQUEST BLOCKED</span>
                  </div>
                  <div>
                    <span style={{ fontWeight: 700, display: 'block', fontSize: '0.7rem', textTransform: 'uppercase', color: '#ef4444', letterSpacing: '0.05em', marginBottom: '2px' }}>Why SETU Stopped It</span>
                    <span style={{ color: 'var(--text-muted)' }}>{result.reasons.join('. ')}</span>
                  </div>
                  <div>
                    <span style={{ fontWeight: 700, display: 'block', fontSize: '0.7rem', textTransform: 'uppercase', color: '#ef4444', letterSpacing: '0.05em', marginBottom: '2px' }}>Enforcing Authority</span>
                    <span style={{ color: 'var(--text-muted)' }}>SETU PolicyEngine</span>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-dimmed)', lineHeight: '1.4' }}>
                  The negotiated deal passes all active minimum profit margin and buyer budget checks. Proceed to secure Razorpay payment handoff.
                </div>
              )}

              {isDealApproved ? (
                <button 
                  onClick={handleCheckout}
                  className="btn btn-primary"
                  style={{
                    width: '100%',
                    justifyContent: 'center',
                    padding: '12px',
                    fontWeight: 700,
                    gap: '8px'
                  }}
                >
                  <span>Proceed to Secure Checkout</span>
                  <ChevronRight style={{ width: '16px', height: '16px' }} />
                </button>
              ) : (
                <button 
                  onClick={handleReset}
                  className="btn btn-secondary"
                  style={{
                    width: '100%',
                    justifyContent: 'center',
                    padding: '12px',
                    borderColor: 'rgba(239, 68, 68, 0.4)',
                    color: '#ef4444'
                  }}
                >
                  <span>Reset Procurement Hub</span>
                </button>
              )}
            </div>
          )}

        </div>

      </div>
    </div>
  );
}
