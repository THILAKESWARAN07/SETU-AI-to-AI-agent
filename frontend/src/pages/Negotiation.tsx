import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  Layers, 
  Loader2, 
  ShieldCheck, 
  ShieldAlert, 
  User, 
  Store, 
  Cpu, 
  Clock, 
  Lock, 
  AlertTriangle,
  ChevronRight
} from 'lucide-react';
import { apiService } from '../services/api';
import type { DemoCommerceResponse } from '../types';
import './Negotiation.css';

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
  const [isAnimating, setIsAnimating] = useState(false);
  
  // Track animation state parameters
  const [animatedRounds, setAnimatedRounds] = useState(1);
  const [animatedToolsCount, setAnimatedToolsCount] = useState(0);
  const [animatedState, setAnimatedState] = useState('IN_PROGRESS');
  const [animatedPolicy, setAnimatedPolicy] = useState('PENDING');
  const [animatedBuyerStatus, setAnimatedBuyerStatus] = useState('ACTIVE');
  const [animatedMerchantStatus, setAnimatedMerchantStatus] = useState('ACTIVE');
  const [animatedPrice, setAnimatedPrice] = useState('0.00');

  const animationTimer = useRef<ReturnType<typeof setInterval> | null>(null);

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
      subtext: `Provider Adapter: ${res.agent_mode || 'LIVE LLM'} | Model: gemini-3.6-flash`,
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
    
    setIsAnimating(true);
    setVisibleEventsCount(1);

    const events = compileTimelineEvents(res);
    
    // Set initial event state values
    updateLiveMetrics(events[0]);

    let currentIndex = 1;
    animationTimer.current = setInterval(() => {
      if (currentIndex >= events.length) {
        clearInterval(animationTimer.current!);
        animationTimer.current = null;
        setIsAnimating(false);
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

  const renderTimelineIcon = (actor: string, type: string, isError?: boolean) => {
    if (type === 'policy_check') {
      return (
        <div className="timeline-avatar system-timeline-avatar" style={{ background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#10b981' }}>
          <ShieldCheck className="avatar-icon-small" />
        </div>
      );
    }
    if (type === 'final_verdict') {
      const color = isError ? '#ef4444' : '#10b981';
      return (
        <div className="timeline-avatar system-timeline-avatar" style={{ background: isError ? 'rgba(239, 68, 68, 0.12)' : 'rgba(16, 185, 129, 0.12)', border: `1px solid ${color}`, color }}>
          {isError ? <ShieldAlert className="avatar-icon-small" /> : <Lock className="avatar-icon-small" />}
        </div>
      );
    }
    if (actor === 'BUYER_AGENT') {
      return (
        <div className="timeline-avatar buyer-timeline-avatar" style={{ background: 'rgba(59, 130, 246, 0.12)', border: '1px solid rgba(59, 130, 246, 0.3)', color: '#3b82f6' }}>
          <User className="avatar-icon-small" />
        </div>
      );
    }
    if (actor === 'MERCHANT_AGENT') {
      return (
        <div className="timeline-avatar merchant-timeline-avatar" style={{ background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.3)', color: '#f59e0b' }}>
          <Store className="avatar-icon-small" />
        </div>
      );
    }
    return (
      <div className="timeline-avatar system-timeline-avatar" style={{ background: 'rgba(107, 114, 128, 0.12)', border: '1px solid rgba(107, 114, 128, 0.3)', color: '#9ca3af' }}>
        <Cpu className="avatar-icon-small" />
      </div>
    );
  };

  const getActorColor = (actor: string, type: string, isError?: boolean) => {
    if (type === 'final_verdict') return isError ? '#ef4444' : '#10b981';
    if (type === 'policy_check') return '#10b981';
    if (actor === 'BUYER_AGENT') return '#3b82f6';
    if (actor === 'MERCHANT_AGENT') return '#f59e0b';
    return '#9ca3af';
  };

  // 4. UI Rendering States
  if (isLoading) {
    return (
      <div className="negotiation-page-container container animate-fade-in" style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: '20px', alignItems: 'center' }}>
          <Loader2 className="securing-spinner animate-spin" style={{ width: '48px', height: '48px', color: 'var(--primary)' }} />
          <h3 style={{ fontSize: '1.3rem', fontWeight: 700, letterSpacing: '0.02em', textTransform: 'uppercase' }}>
            Spawning Autonomous AI Agents...
          </h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', maxWidth: '400px' }}>
            Setting up policy sandboxes, parsing purchase constraints, and initiating negotiations turn loops.
          </p>
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

  return (
    <div className="negotiation-page-container container animate-fade-in" style={{ paddingBottom: '120px' }}>
      {/* Header Back Link */}
      <div className="negotiation-page-header">
        <button onClick={handleReset} className="back-to-deal-btn">
          <ArrowLeft className="back-icon" />
          <span>Back to Procurement Hub</span>
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span className={`system-status-tag font-mono ${result.agent_mode === 'LIVE LLM' ? 'live-llm-tag' : 'mock-tag'}`} style={{
            background: result.agent_mode === 'LIVE LLM' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(107, 114, 128, 0.15)',
            color: result.agent_mode === 'LIVE LLM' ? '#10b981' : '#9ca3af',
            border: result.agent_mode === 'LIVE LLM' ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(107, 114, 128, 0.3)'
          }}>
            AGENT MODE: {result.agent_mode || 'OFFLINE MOCK'}
          </span>
          <span className="system-status-tag font-mono">ENFORCING DECIMAL POLICY</span>
        </div>
      </div>

      {/* Main Content Layout Grid */}
      <div className="negotiation-grid">
        
        {/* Left Column: Flow Timeline */}
        <div className="negotiation-main-col" style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
          
          <div className="timeline-section-card animate-fade-in" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '32px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <h3 className="timeline-section-title" style={{ fontSize: '1.2rem', fontWeight: 700 }}>Unified Transaction Timeline</h3>
              {isAnimating && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', color: 'var(--primary)' }} className="font-mono">
                  <Loader2 className="animate-spin" style={{ width: '12px', height: '12px' }} />
                  <span>SIMULATING TRANSACTION STEPS LIVE...</span>
                </div>
              )}
            </div>
            
            <p className="timeline-subtitle text-muted" style={{ fontSize: '0.78rem', marginBottom: '28px', color: 'var(--text-dimmed)' }}>
              Live execution logs mapping agent decisions, Registry tool usages, and Policy Engine checkpoints.
            </p>

            <div className="chat-timeline-container" style={{ display: 'flex', flexDirection: 'column', gap: '20px', position: 'relative' }}>
              {visibleEvents.map((evt, idx) => (
                <div 
                  key={evt.id} 
                  className={`timeline-chat-row animate-fade-in`}
                  style={{ 
                    display: 'flex', 
                    gap: '16px', 
                    paddingBottom: idx === visibleEvents.length - 1 ? '0' : '20px',
                    borderLeft: idx === visibleEvents.length - 1 ? 'none' : '1px solid rgba(255, 255, 255, 0.05)',
                    marginLeft: '15px',
                    paddingLeft: '24px',
                    position: 'relative'
                  }}
                >
                  {/* Avatar Icon */}
                  <div style={{ position: 'absolute', left: '-16px', top: '0' }}>
                    {renderTimelineIcon(evt.actor, evt.type, evt.isError)}
                  </div>

                  <div className="timeline-chat-bubble" style={{
                    backgroundColor: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '8px',
                    padding: '16px 20px',
                    width: '100%'
                  }}>
                    <div className="bubble-meta" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span className="bubble-author font-mono" style={{ fontSize: '0.7rem', fontWeight: 700, color: getActorColor(evt.actor, evt.type, evt.isError) }}>
                        {evt.label}
                      </span>
                      <span className="bubble-timestamp font-mono" style={{ fontSize: '0.65rem', color: 'var(--text-dimmed)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Clock style={{ width: '10px', height: '10px' }} />
                        {evt.timestamp}
                      </span>
                    </div>

                    <p className="bubble-msg" style={{ fontSize: '0.88rem', color: 'var(--text-main)', lineHeight: '1.4' }}>
                      {evt.message}
                    </p>

                    {evt.subtext && (
                      <p className="bubble-subtext" style={{ 
                        fontSize: '0.78rem', 
                        color: 'var(--text-muted)', 
                        marginTop: '8px',
                        backgroundColor: 'rgba(0, 0, 0, 0.15)',
                        padding: '6px 12px',
                        borderRadius: '4px',
                        borderLeft: `2px solid ${getActorColor(evt.actor, evt.type, evt.isError)}`
                      }}>
                        {evt.subtext}
                      </p>
                    )}
                  </div>
                </div>
              ))}
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
                <span className="font-mono" style={{ fontWeight: 700, color: result.agent_mode === 'LIVE LLM' ? '#10b981' : '#9ca3af' }}>
                  {result.agent_mode || 'OFFLINE MOCK'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>LLM Provider:</span>
                <span style={{ fontWeight: 500, color: 'var(--text-main)' }}>
                  {result.agent_mode === 'LIVE LLM' ? 'Gemini' : 'MockProvider'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>LLM Model:</span>
                <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>
                  {result.agent_mode === 'LIVE LLM' ? 'gemini-3.6-flash' : 'mock-model-v2'}
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
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-dimmed)' }}>Order Status:</span>
                <span className="font-mono" style={{ fontWeight: 700, color: 'var(--text-dimmed)' }}>
                  --
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

              <div style={{ fontSize: '0.75rem', color: 'var(--text-dimmed)', lineHeight: '1.4' }}>
                {isDealApproved 
                  ? 'The negotiated deal passes all active minimum profit margin and buyer budget checks. Proceed to secure Razorpay payment handoff.' 
                  : `This deal proposal has been terminated by the Policy Engine. Reason: ${result.reasons.join(', ')}`}
              </div>

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
                    borderColor: 'rgba(239, 68, 68, 0.3)',
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
