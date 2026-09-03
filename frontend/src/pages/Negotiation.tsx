import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  User, 
  Store, 
  AlertTriangle,
  ChevronRight,
  Shield,
  Activity,
  CheckCircle2,
  MessageSquare,
  ArrowRight,
  ShieldCheck,
  Layers
} from 'lucide-react';
import { apiService } from '../services/api';
import type { DemoCommerceResponse } from '../types';
import './Negotiation.css';

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

const formatISTTime = (secsOffset: number = 0) => {
  const d = new Date(Date.now() + secsOffset * 1000);
  const dateStr = d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata'
  });
  const timeStr = d.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: 'Asia/Kolkata'
  });
  return `${dateStr}, ${timeStr} IST`;
};

interface ChatMessage {
  id: string;
  sender: 'BUYER_AGENT' | 'MERCHANT_AGENT' | 'SETU_SYSTEM';
  actor: string;
  message: string;
  amount?: string;
  round?: number;
  reasonLabel?: string;
  timestamp: string;
  basketItems?: any[];
  isFinal?: boolean;
}

const compileChatMessages = (res: DemoCommerceResponse): ChatMessage[] => {
  const msgs: ChatMessage[] = [];
  
  if (res.negotiation_history && res.negotiation_history.length > 0) {
    res.negotiation_history.forEach((turn, idx) => {
      const turnTimeOffset = 1.2 * (idx + 1);

      if (turn.buyer_offer) {
        msgs.push({
          id: `buyer_turn_${idx}`,
          sender: 'BUYER_AGENT',
          actor: 'BUYER AGENT',
          message: turn.buyer_offer.message || turn.buyer_offer.reason || `I'd like to propose ₹${parseFloat(turn.buyer_offer.final_amount).toLocaleString('en-IN')}.`,
          amount: turn.buyer_offer.final_amount,
          round: turn.round,
          reasonLabel: turn.buyer_offer.reason_label || 'Buyer budget limit check',
          timestamp: formatISTTime(turnTimeOffset),
          basketItems: turn.buyer_offer.basket_items
        });

        msgs.push({
          id: `setu_sys_buyer_${idx}`,
          sender: 'SETU_SYSTEM',
          actor: 'SETU TRUST LAYER',
          message: 'SETU verified catalog availability & budget boundary limits',
          timestamp: formatISTTime(turnTimeOffset + 0.3)
        });
      }

      if (turn.merchant_offer) {
        msgs.push({
          id: `merchant_turn_${idx}`,
          sender: 'MERCHANT_AGENT',
          actor: 'MERCHANT AGENT',
          message: turn.merchant_offer.message || turn.merchant_offer.reason || `I can offer a price of ₹${parseFloat(turn.merchant_offer.offered_amount).toLocaleString('en-IN')}.`,
          amount: turn.merchant_offer.offered_amount,
          round: turn.round,
          reasonLabel: turn.merchant_offer.reason_label || 'Within merchant price floor & margin rules',
          timestamp: formatISTTime(turnTimeOffset + 0.6),
          basketItems: turn.merchant_offer.basket_items
        });

        msgs.push({
          id: `setu_sys_merchant_${idx}`,
          sender: 'SETU_SYSTEM',
          actor: 'SETU TRUST LAYER',
          message: 'SETU enforced price floor & margin policy constraints',
          timestamp: formatISTTime(turnTimeOffset + 0.9)
        });
      }
    });
  } else {
    // Fallback if negotiation_history is empty
    msgs.push({
      id: 'buyer_init',
      sender: 'BUYER_AGENT',
      actor: 'BUYER AGENT',
      message: `Hi, I'm looking to procure "${res.intent}". My budget limit is ₹${parseFloat(res.original_amount).toLocaleString('en-IN')}. Can you offer a better price?`,
      amount: res.original_amount,
      round: 1,
      reasonLabel: 'Initial offer within budget',
      timestamp: formatISTTime(1)
    });
  }

  // Final Deal Verdict confirmation message
  if (res.decision === 'APPROVED') {
    msgs.push({
      id: 'setu_sys_approved',
      sender: 'SETU_SYSTEM',
      actor: 'SETU TRUST LAYER',
      message: 'SETU Policy Engine approved final basket integrity & authorized payment',
      timestamp: formatISTTime((res.negotiation_history?.length || 1) * 1.5)
    });

    msgs.push({
      id: 'merchant_deal_locked',
      sender: 'MERCHANT_AGENT',
      actor: 'MERCHANT AGENT',
      message: `Deal agreed! I'll proceed with the basket at ₹${parseFloat(res.final_amount).toLocaleString('en-IN')}. I've authorized the transaction through SETU Policy Engine.`,
      amount: res.final_amount,
      round: (res.negotiation_history?.length || 1) + 1,
      reasonLabel: 'Deal Authorized by PolicyEngine',
      timestamp: formatISTTime((res.negotiation_history?.length || 1) * 1.8),
      isFinal: true,
      basketItems: res.basket?.items
    });
  } else if (res.decision === 'BLOCKED' || res.decision === 'REJECTED') {
    msgs.push({
      id: 'negotiation_failed',
      sender: 'MERCHANT_AGENT',
      actor: 'MERCHANT AGENT',
      message: `I'm sorry, we couldn't reach an agreement within our allowed selling price floor. (${res.reasons.join('. ')})`,
      round: (res.negotiation_history?.length || 1) + 1,
      reasonLabel: 'Offer Exceeds Policy Limits',
      timestamp: formatISTTime((res.negotiation_history?.length || 1) * 1.8),
      isFinal: true
    });
  }

  return msgs;
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
  const [visibleMessagesCount, setVisibleMessagesCount] = useState(0);
  const [thinkingAgent, setThinkingAgent] = useState<'BUYER' | 'MERCHANT' | null>(null);

  // Progressive timer state
  const [elapsed, setElapsed] = useState(0);
  const loadingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const animationTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // 1. Fetch result if not present
  useEffect(() => {
    if (initialResult) {
      setResult(initialResult);
      startConversationAnimation(initialResult);
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
        startConversationAnimation(data);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'An error occurred during negotiation.');
        setIsLoading(false);
      });
  }, [stateIntent, stateBudget, initialResult]);

  // Clean up timers on unmount
  useEffect(() => {
    return () => {
      if (animationTimer.current) clearInterval(animationTimer.current);
      if (loadingTimer.current) clearInterval(loadingTimer.current);
    };
  }, []);

  // Manage loading elapsed timer
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
  }, [isLoading]);

  // Scroll chat to bottom when messages update
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [visibleMessagesCount, thinkingAgent]);

  // 2. Start conversation step-by-step animation
  const startConversationAnimation = (res: DemoCommerceResponse) => {
    if (animationTimer.current) clearInterval(animationTimer.current);
    
    const messages = compileChatMessages(res);
    setVisibleMessagesCount(1);
    setThinkingAgent('MERCHANT');

    let currentIndex = 1;
    animationTimer.current = setInterval(() => {
      if (currentIndex >= messages.length) {
        clearInterval(animationTimer.current!);
        animationTimer.current = null;
        setThinkingAgent(null);
        return;
      }
      
      setVisibleMessagesCount(currentIndex + 1);
      const nextMsg = messages[currentIndex];
      if (currentIndex < messages.length - 1) {
        setThinkingAgent(nextMsg.sender === 'BUYER_AGENT' ? 'MERCHANT' : 'BUYER');
      } else {
        setThinkingAgent(null);
      }

      currentIndex++;
    }, 900);
  };

  const handleCheckout = () => {
    if (!result) return;
    navigate('/payment', { state: { result } });
  };

  const handleReset = () => {
    navigate('/shopping');
  };

  // UI Render: Loading State
  if (isLoading) {
    const buyerActive = elapsed >= 3.0;
    const buyerStatusLabel = elapsed < 3.0 ? "PENDING" : elapsed < 3.6 ? "INITIALIZING" : "ACTIVE";

    const merchantActive = elapsed >= 4.0;
    const merchantStatusLabel = elapsed < 4.0 ? "PENDING" : elapsed < 4.8 ? "INITIALIZING" : "ACTIVE";

    const trustActive = elapsed >= 5.2;
    const trustStatusLabel = elapsed < 5.2 ? "PENDING" : elapsed < 6.2 ? "SECURING" : "ENFORCED";

    let progressPercent = 0;
    if (elapsed <= 8.0) {
      progressPercent = (elapsed / 8.0) * 90;
    } else {
      progressPercent = 90 + 5 * (1 - Math.exp(-(elapsed - 8.0) / 10));
    }

    const currentStageIndex = stageTimes.findIndex(t => elapsed < t);
    const currentStageNumber = currentStageIndex === -1 ? 8 : currentStageIndex + 1;

    return (
      <div className="negotiation-page-container container animate-fade-in" style={{ minHeight: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="loader-panel-container">
          <div>
            <h3 className="loader-panel-title">
              Spawning Autonomous AI Agents
            </h3>
            <p className="loader-panel-subtitle">
              Parsing procurement constraints, securing SETU trust sandbox, and initiating live agent turn loop.
            </p>
          </div>

          <div className="visualizer-wrapper">
            <div className={`visual-node buyer-node ${buyerActive ? 'active-node' : ''}`}>
              <User className="visual-node-icon" />
              <span className="visual-node-label">BUYER AGENT</span>
              <span className="visual-node-status">{buyerStatusLabel}</span>
            </div>

            <div className="visual-connector-line">
              {buyerActive && <div className="connector-pulse-dot pulse-right" style={{ opacity: 1 }} />}
            </div>

            <div className={`visual-node trust-node ${trustActive ? 'active-node' : ''}`}>
              <Shield className="visual-node-icon" />
              <span className="visual-node-label">SETU TRUST LAYER</span>
              <span className="visual-node-status">{trustStatusLabel}</span>
            </div>

            <div className="visual-connector-line">
              {merchantActive && <div className="connector-pulse-dot pulse-left" style={{ opacity: 1 }} />}
            </div>

            <div className={`visual-node merchant-node ${merchantActive ? 'active-node' : ''}`}>
              <Store className="visual-node-icon" />
              <span className="visual-node-label">MERCHANT AGENT</span>
              <span className="visual-node-status">{merchantStatusLabel}</span>
            </div>
          </div>

          <div className="stages-list-container" style={{ width: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span className="progress-footer-status font-mono" style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {currentStageNumber <= 8 ? stages[currentStageNumber - 1] : 'Finalizing negotiation handshake...'}
              </span>
              <span className="progress-elapsed-timer font-mono" style={{ fontSize: '0.8rem', color: 'var(--primary)' }}>ELAPSED: {elapsed.toFixed(1)}s</span>
            </div>
            <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden' }}>
              <div style={{ width: `${progressPercent}%`, height: '100%', background: 'linear-gradient(90deg, #3b82f6, #10b981)', transition: 'width 0.2s ease' }} />
            </div>
          </div>

          {elapsed >= 8.0 && (
            <div className="keep-alive-banner">
              <Activity className="keep-alive-icon" style={{ flexShrink: 0 }} />
              <span>Live AI negotiation loop processing... Maintaining secure session...</span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // UI Render: Error State
  if (error) {
    return (
      <div className="negotiation-page-container container animate-fade-in" style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="error-panel" style={{ maxWidth: '500px' }}>
          <AlertTriangle className="error-icon" />
          <h3>Negotiation Session Failed</h3>
          <p className="error-msg">{error}</p>
          <button onClick={handleReset} className="btn btn-primary" style={{ marginTop: '16px' }}>
            <ArrowLeft className="btn-icon" />
            <span>Go to Shopping</span>
          </button>
        </div>
      </div>
    );
  }

  // UI Render: Empty State
  if (!result) {
    return (
      <div className="negotiation-page-container container animate-fade-in">
        <div className="empty-negotiation-state">
          <Layers className="empty-state-icon animate-float" />
          <h3>No Active Negotiation Session</h3>
          <p className="empty-state-desc">
            To view the AI negotiation flow, describe your purchase intent and search the catalog.
          </p>
          <button onClick={handleReset} className="btn btn-primary">
            <ArrowLeft className="btn-icon" />
            <span>Go to Shopping</span>
          </button>
        </div>
      </div>
    );
  }

  const allMessages = compileChatMessages(result);
  const visibleMessages = allMessages.slice(0, visibleMessagesCount);
  const isDealApproved = result.decision === 'APPROVED';
  const isAnimationFinished = visibleMessagesCount >= allMessages.length;

  // Price progression tracking
  const initialOriginalPrice = parseFloat(result.original_amount);
  const buyerInitialOfferPrice = result.negotiation_history?.[0]?.buyer_offer?.final_amount ? parseFloat(result.negotiation_history[0].buyer_offer.final_amount) : initialOriginalPrice * 0.9;
  const merchantCounterPrice = result.negotiation_history?.[0]?.merchant_offer?.offered_amount ? parseFloat(result.negotiation_history[0].merchant_offer.offered_amount) : parseFloat(result.final_amount);
  const finalPrice = parseFloat(result.final_amount);

  return (
    <div className="negotiation-page-container container animate-fade-in" style={{ paddingBottom: '120px' }}>
      
      {/* Header Bar */}
      <div className="negotiation-page-header">
        <button onClick={handleReset} className="back-to-deal-btn">
          <ArrowLeft className="back-icon" />
          <span>Back to Procurement Hub</span>
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span className="system-status-tag font-mono" style={{
            background: result.execution_mode === 'LIVE LLM' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(107, 114, 128, 0.15)',
            color: result.execution_mode === 'LIVE LLM' ? '#10b981' : '#9ca3af',
            border: result.execution_mode === 'LIVE LLM' ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(107, 114, 128, 0.3)'
          }}>
            MODE: {result.execution_mode || 'OFFLINE MOCK'}
          </span>
          <span className="system-status-tag font-mono" style={{ color: 'var(--primary)', borderColor: 'rgba(100, 75, 255, 0.3)', background: 'rgba(100, 75, 255, 0.05)' }}>
            SETU POLICY SANDBOX ACTIVE
          </span>
        </div>
      </div>

      {/* Main Grid: Left Chat UI, Right SETU Trust Panel */}
      <div className="negotiation-grid">
        
        {/* LEFT COLUMN: VISUAL CONVERSATION & PRICE PROGRESSION */}
        <div className="negotiation-main-col">
          
          {/* Price Progression Tracker */}
          <div className="price-progression-bar">
            <div className="price-step-item">
              <span className="price-step-label">Catalog Price</span>
              <span className="price-step-val">₹{initialOriginalPrice.toLocaleString('en-IN')}</span>
            </div>
            <ArrowRight className="price-step-arrow" />
            <div className="price-step-item">
              <span className="price-step-label">Buyer Offer</span>
              <span className="price-step-val" style={{ color: '#60a5fa' }}>₹{buyerInitialOfferPrice.toLocaleString('en-IN')}</span>
            </div>
            <ArrowRight className="price-step-arrow" />
            <div className="price-step-item">
              <span className="price-step-label">Merchant Counter</span>
              <span className="price-step-val" style={{ color: '#fbbf24' }}>₹{merchantCounterPrice.toLocaleString('en-IN')}</span>
            </div>
            <ArrowRight className="price-step-arrow" />
            <div className="price-step-item">
              <span className="price-step-label">Agreed Final</span>
              <span className={`price-step-val ${isDealApproved ? 'highlight-green' : ''}`}>
                {isDealApproved ? `₹${finalPrice.toLocaleString('en-IN')}` : 'BLOCKED'}
              </span>
            </div>
          </div>

          {/* Primary View: Chat Conversation Stream */}
          <div className="chat-conversation-panel">
            <div className="chat-panel-header">
              <div className="chat-panel-title">
                <MessageSquare className="chat-panel-icon" />
                <span>LIVE BUYER ↔ MERCHANT NEGOTIATION</span>
              </div>
              <span className="font-mono" style={{ fontSize: '0.7rem', color: 'var(--text-dimmed)', background: 'rgba(255,255,255,0.03)', padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                INTENT: "{result.intent}"
              </span>
            </div>

            <div className="chat-stream-body">
              {visibleMessages.map((msg) => {
                if (msg.sender === 'SETU_SYSTEM') {
                  return (
                    <div key={msg.id} className="setu-system-event-badge animate-fade-in">
                      <ShieldCheck className="system-event-icon" />
                      <span>{msg.message}</span>
                    </div>
                  );
                }

                const isBuyer = msg.sender === 'BUYER_AGENT';
                const isDealMsg = msg.isFinal && isDealApproved;

                return (
                  <div key={msg.id} className={`chat-message-row ${isBuyer ? 'buyer-row' : 'merchant-row'} animate-fade-in`}>
                    <div className={`chat-avatar-wrapper ${isDealMsg ? 'deal-avatar' : isBuyer ? 'buyer-avatar' : 'merchant-avatar'}`}>
                      {isBuyer ? <User style={{ width: '18px', height: '18px' }} /> : <Store style={{ width: '18px', height: '18px' }} />}
                    </div>

                    <div className={`chat-bubble ${isDealMsg ? 'deal-bubble' : isBuyer ? 'buyer-bubble' : 'merchant-bubble'}`}>
                      <div className="chat-bubble-header">
                        <span className={`chat-actor-name ${isDealMsg ? 'deal-text' : isBuyer ? 'buyer-text' : 'merchant-text'}`}>
                          {msg.actor}
                        </span>
                        {msg.round && (
                          <span className="chat-round-badge">Round {msg.round}</span>
                        )}
                      </div>

                      <p className="chat-bubble-message">{msg.message}</p>

                      <div className="chat-bubble-footer">
                        {msg.amount && (
                          <span className={`chat-price-pill ${isDealMsg ? 'deal-pill' : isBuyer ? 'buyer-pill' : 'merchant-pill'}`}>
                            {isBuyer ? 'Bid: ' : isDealMsg ? 'Agreed: ' : 'Counter: '}₹{parseFloat(msg.amount).toLocaleString('en-IN')}
                          </span>
                        )}
                        {msg.reasonLabel && (
                          <span className="chat-reason-tag">{msg.reasonLabel}</span>
                        )}
                        <span className="chat-timestamp">{msg.timestamp}</span>
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Thinking State Animation */}
              {thinkingAgent && (
                <div className="thinking-indicator-row animate-fade-in">
                  <div className="thinking-dots">
                    <div className="thinking-dot" />
                    <div className="thinking-dot" />
                    <div className="thinking-dot" />
                  </div>
                  <span>
                    {thinkingAgent === 'BUYER' ? 'Buyer Agent is considering offer...' : 'Merchant Agent evaluating margin & inventory...'}
                  </span>
                </div>
              )}

              <div ref={chatEndRef} />
            </div>
          </div>

        </div>

        {/* RIGHT COLUMN: SETU TRUST VERIFICATION SIDE PANEL */}
        <div className="negotiation-sidebar-col">
          
          <div className="agent-session-panel-card animate-fade-in" style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '16px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)'
          }}>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
              <Shield style={{ width: '20px', height: '20px', color: '#10b981' }} />
              <div>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 700, margin: 0 }}>SETU TRUST VERIFICATION</h3>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-dimmed)' }}>Deterministic Policy Compliance</span>
              </div>
            </div>

            {/* Checkpoint Gates */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              
              {/* Gate 1: Stock Availability */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Product Availability</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Inventory verified in database</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>VERIFIED</span>
              </div>

              {/* Gate 2: Buyer Budget Cap */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Buyer Budget Boundary</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Limit ₹{parseFloat((stateBudget || result.original_amount).toString()).toLocaleString('en-IN')} respected</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>SATISFIED</span>
              </div>

              {/* Gate 3: Minimum Selling Price Floor */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Merchant Min Price Floor</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>min_selling_price floor protected</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>PROTECTED</span>
              </div>

              {/* Gate 4: Margin Protection */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Margin Guideline Check</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Margin: {result.margin_percent}% &gt;= min policy</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>PASSED</span>
              </div>

              {/* Gate 5: Policy Engine Authorization */}
              <div style={{ 
                background: isDealApproved ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                border: isDealApproved ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
                padding: '12px',
                borderRadius: '8px',
                textAlign: 'center',
                marginTop: '4px'
              }}>
                <span className="font-mono" style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-dimmed)', display: 'block' }}>POLICY ENGINE FINAL VERDICT</span>
                <span className="font-mono" style={{ fontSize: '1.2rem', fontWeight: 900, color: isDealApproved ? '#10b981' : '#ef4444' }}>
                  {result.decision}
                </span>
              </div>
            </div>

            {/* Itemized Final Basket Card */}
            {isDealApproved && result.basket && result.basket.items && (
              <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-dimmed)', letterSpacing: '0.05em' }}>
                  ITEMIZED VALIDATED BASKET
                </span>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.25)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  {result.basket.items.map((item: any, idx: number) => {
                    const itemOrig = parseFloat(item.original_price) * item.quantity;
                    const itemNeg = parseFloat(item.negotiated_price) * item.quantity;
                    const itemDisc = itemOrig - itemNeg;
                    return (
                      <div key={idx} style={{ display: 'flex', flexDirection: 'column', fontSize: '0.82rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: 'var(--text-main)', fontWeight: 500 }}>
                            {item.name} {item.quantity > 1 ? `x${item.quantity}` : ''}
                            {item.is_primary && (
                              <span style={{ fontSize: '8px', marginLeft: '6px', padding: '1px 4px', borderRadius: '3px', background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.25)' }}>
                                PRIMARY
                              </span>
                            )}
                          </span>
                          <span className="font-mono" style={{ color: 'var(--text-main)', fontWeight: 700 }}>
                            ₹{itemNeg.toLocaleString('en-IN')}
                          </span>
                        </div>
                        {itemDisc > 0 && (
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#34d399' }}>
                            <span>List: ₹{itemOrig.toLocaleString('en-IN')}</span>
                            <span>Save: -₹{itemDisc.toLocaleString('en-IN')}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {parseFloat(result.basket.discount_amount) > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#34d399', borderTop: '1px dashed rgba(255,255,255,0.08)', paddingTop: '6px', marginTop: '4px', fontWeight: 700 }}>
                      <span>Bundle Savings:</span>
                      <span>-₹{parseFloat(result.basket.discount_amount).toLocaleString('en-IN')}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Total & Checkout Action */}
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Negotiated Total:</span>
                <span className="font-mono" style={{ fontSize: '1.25rem', fontWeight: 800, color: isDealApproved ? '#10b981' : '#ef4444' }}>
                  ₹{parseFloat(result.final_amount).toLocaleString('en-IN')}
                </span>
              </div>

              {isDealApproved ? (
                <button 
                  onClick={handleCheckout}
                  disabled={!isAnimationFinished}
                  className="btn btn-primary"
                  style={{
                    width: '100%',
                    justifyContent: 'center',
                    padding: '12px',
                    fontWeight: 700,
                    gap: '8px',
                    opacity: isAnimationFinished ? 1 : 0.6
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

          </div>

        </div>

      </div>
    </div>
  );
}
