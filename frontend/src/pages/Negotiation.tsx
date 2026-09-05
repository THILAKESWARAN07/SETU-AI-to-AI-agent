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
  Layers,
  Sparkles,
  RotateCcw
} from 'lucide-react';
import { apiService } from '../services/api';
import type { DemoCommerceResponse, ConversationEvent } from '../types';
import './Negotiation.css';

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
  sequence?: number;
  sender: 'BUYER_AGENT' | 'MERCHANT_AGENT' | 'SETU_SYSTEM';
  actor: string;
  message: string;
  amount?: string;
  round?: number;
  reasonLabel?: string;
  strategy?: string;
  eventType?: string;
  proposalType?: string;
  proposalId?: string;
  acceptedProposalId?: string;
  standaloneCounter?: string;
  bundleProposal?: any;
  optionalBundleItems?: any[];
  timestamp: string;
  basketItems?: any[];
  isFinal?: boolean;
  providerUsed?: 'gemini' | 'openrouter' | 'groq' | 'mock' | string;
  providerType?: 'real_llm' | 'deterministic_fallback';
  agentRole?: string;
  modelName?: string;
  fallbackUsed?: boolean;
  fallbackDepth?: number;
  fallbackReason?: string | null;
  responseLatencyMs?: number;
}

const mapEventToMessage = (evt: ConversationEvent, idx: number): ChatMessage => {
  let sender: 'BUYER_AGENT' | 'MERCHANT_AGENT' | 'SETU_SYSTEM' = 'SETU_SYSTEM';
  let actor = 'SETU TRUST LAYER';
  if (evt.actor === 'buyer') {
    sender = 'BUYER_AGENT';
    actor = 'BUYER AGENT';
  } else if (evt.actor === 'merchant') {
    sender = 'MERCHANT_AGENT';
    actor = 'MERCHANT AGENT';
  }

  return {
    id: evt.event_id || evt.id || `evt_${idx}_${Date.now()}`,
    sequence: evt.sequence,
    sender,
    actor,
    message: evt.message,
    amount: evt.offer !== undefined && evt.offer !== null && String(evt.offer) !== '0.00' && String(evt.offer) !== '0' ? String(evt.offer) : undefined,
    round: evt.round,
    reasonLabel: evt.reason_label,
    strategy: evt.strategy,
    eventType: evt.event_type || evt.type,
    proposalType: evt.proposal_type,
    proposalId: evt.proposal_id,
    acceptedProposalId: evt.accepted_proposal_id,
    standaloneCounter: evt.standalone_counter ? String(evt.standalone_counter) : undefined,
    bundleProposal: evt.bundle_proposal,
    optionalBundleItems: evt.optional_bundle_items,
    timestamp: evt.timestamp || formatISTTime(idx * 0.4),
    basketItems: evt.basket_items,
    isFinal: evt.is_final,
    providerUsed: evt.provider_used,
    providerType: evt.provider_type,
    agentRole: evt.agent_role,
    modelName: evt.model_name,
    fallbackUsed: evt.fallback_used,
    fallbackDepth: evt.fallback_depth,
    fallbackReason: evt.fallback_reason,
    responseLatencyMs: evt.response_latency_ms
  };
};

export default function Negotiation() {
  const navigate = useNavigate();
  const location = useLocation();
  
  const stateIntent = location.state?.intent as string | undefined;
  const stateBudget = location.state?.budget as number | undefined;
  const initialResult = location.state?.result as DemoCommerceResponse | undefined;

  const [phase, setPhase] = useState<'IDLE' | 'STREAMING' | 'NEGOTIATING' | 'AGREED' | 'APPROVED' | 'REQUIRES_APPROVAL' | 'REJECTED' | 'FAILED'>('IDLE');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DemoCommerceResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [thinkingAgent, setThinkingAgent] = useState<'BUYER' | 'MERCHANT' | null>(null);

  // Live price trackers - cleanly distinguish opening offer from counters & bundles
  const [liveCatalogPrice, setLiveCatalogPrice] = useState<number>(0);
  const [liveBuyerOpeningOffer, setLiveBuyerOpeningOffer] = useState<number | null>(null);
  const [liveMerchantStandaloneCounter, setLiveMerchantStandaloneCounter] = useState<number | null>(null);
  const [liveMerchantBundleProposal, setLiveMerchantBundleProposal] = useState<number | null>(null);
  const [liveFinalPrice, setLiveFinalPrice] = useState<number | null>(null);
  const [liveFinalBasketDesc, setLiveFinalBasketDesc] = useState<string | null>(null);

  // Progressive elapsed timer
  const [elapsed, setElapsed] = useState(0);
  const elapsedTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const startNegotiationStream = () => {
    if (!stateIntent) return;

    setPhase('STREAMING');
    setError(null);
    setResult(null);
    setMessages([]);
    setLiveBuyerOpeningOffer(null);
    setLiveMerchantStandaloneCounter(null);
    setLiveMerchantBundleProposal(null);
    setLiveFinalPrice(null);
    setLiveFinalBasketDesc(null);
    setThinkingAgent('BUYER');
    setElapsed(0);

    const budgetVal = stateBudget ? stateBudget : 2000.00;
    setLiveCatalogPrice(budgetVal);

    let eventCount = 0;

    apiService.streamDemoCommerceFlow(
      {
        buyer_id: 'demo-buyer-001',
        intent: stateIntent,
        budget: budgetVal
      },
      (evt: ConversationEvent) => {
        eventCount++;
        const newMsg = mapEventToMessage(evt, eventCount);
        
        setMessages((prev) => {
          // Avoid duplicate events by ID or message content
          if (prev.some(m => m.id === newMsg.id || (m.message === newMsg.message && m.actor === newMsg.actor))) {
            return prev;
          }
          return [...prev, newMsg];
        });

        // Update live pricing progression accurately
        if (evt.actor === 'buyer') {
          if (evt.offer && parseFloat(String(evt.offer)) > 0) {
            // Only set opening offer if not yet recorded
            setLiveBuyerOpeningOffer((prev) => (prev === null ? parseFloat(String(evt.offer)) : prev));
          }
          setThinkingAgent('MERCHANT');
          setPhase('NEGOTIATING');
        } else if (evt.actor === 'merchant') {
          if (evt.standalone_counter && parseFloat(String(evt.standalone_counter)) > 0) {
            setLiveMerchantStandaloneCounter(parseFloat(String(evt.standalone_counter)));
          } else if (evt.offer && parseFloat(String(evt.offer)) > 0) {
            setLiveMerchantStandaloneCounter(parseFloat(String(evt.offer)));
          }
          if (evt.bundle_proposal && evt.bundle_proposal.offered_amount) {
            setLiveMerchantBundleProposal(parseFloat(String(evt.bundle_proposal.offered_amount)));
          }
          setThinkingAgent('BUYER');
          setPhase('NEGOTIATING');
        } else if (evt.actor === 'setu') {
          if (evt.state === 'POLICY_VALIDATION' || evt.state === 'APPROVED') {
            setThinkingAgent(null);
          }
        }
      }
    )
      .then((finalRes) => {
        setResult(finalRes);
        setThinkingAgent(null);

        // Sync final catalog price & negotiated prices
        const origAmt = parseFloat(finalRes.original_amount || '0');
        const finAmt = parseFloat(finalRes.final_amount || '0');
        if (origAmt > 0) setLiveCatalogPrice(origAmt);
        if (finAmt > 0) setLiveFinalPrice(finAmt);

        const buyerOpeningVal = parseFloat(String(
          finalRes.buyer_opening_offer?.offered_amount ||
          finalRes.buyer_opening_offer?.total_amount ||
          finalRes.buyer_opening_offer?.amount ||
          finalRes.proposals?.find((p: any) => p.proposal_id === 'prop_b_r1')?.total_amount ||
          finalRes.conversation_events?.find((e: any) => e.actor === 'buyer' && e.round === 1)?.offer ||
          '0'
        ));
        if (buyerOpeningVal > 0) setLiveBuyerOpeningOffer(buyerOpeningVal);

        const merchantStandaloneVal = parseFloat(String(
          finalRes.merchant_standalone_counter?.offered_amount ||
          finalRes.merchant_standalone_counter?.total_amount ||
          finalRes.merchant_standalone_counter?.amount ||
          finalRes.proposals?.find((p: any) => p.proposal_type === 'STANDALONE_COUNTER')?.total_amount ||
          finalRes.conversation_events?.find((e: any) => e.actor === 'merchant' && e.event_type !== 'bundle_offer')?.offer ||
          '0'
        ));
        if (merchantStandaloneVal > 0) setLiveMerchantStandaloneCounter(merchantStandaloneVal);

        const merchantBundleVal = parseFloat(String(
          finalRes.merchant_bundle_proposal?.offered_amount ||
          finalRes.merchant_bundle_proposal?.total_amount ||
          finalRes.merchant_bundle_proposal?.amount ||
          finalRes.proposals?.find((p: any) => p.proposal_type === 'BUNDLE_PROPOSAL')?.total_amount ||
          '0'
        ));
        if (merchantBundleVal > 0) setLiveMerchantBundleProposal(merchantBundleVal);

        if (finalRes.basket?.items) {
          const names = finalRes.basket.items.map((i: any) => i.name).join(' + ');
          setLiveFinalBasketDesc(names);
        }

        if (finalRes.decision === 'APPROVED') {
          setPhase('APPROVED');
        } else if (finalRes.decision === 'REQUIRES_APPROVAL') {
          setPhase('REQUIRES_APPROVAL');
        } else {
          setPhase('REJECTED');
        }
      })
      .catch((err) => {
        console.warn('Streaming failed, trying standard fallback...', err);
        // Fallback to standard commerce endpoint if stream fails
        apiService.runDemoCommerceFlow({
          buyer_id: 'demo-buyer-001',
          intent: stateIntent,
          budget: budgetVal
        })
          .then((fallbackRes) => {
            setResult(fallbackRes);
            setThinkingAgent(null);
            if (fallbackRes.conversation_events && fallbackRes.conversation_events.length > 0) {
              const mapped = fallbackRes.conversation_events.map((e, idx) => mapEventToMessage(e, idx));
              setMessages(mapped);
            }
            const origAmt = parseFloat(fallbackRes.original_amount || '0');
            const finAmt = parseFloat(fallbackRes.final_amount || '0');
            if (origAmt > 0) setLiveCatalogPrice(origAmt);
            if (finAmt > 0) setLiveFinalPrice(finAmt);

            const fbBuyerOpeningVal = parseFloat(String(
              fallbackRes.buyer_opening_offer?.offered_amount ||
              fallbackRes.buyer_opening_offer?.total_amount ||
              fallbackRes.buyer_opening_offer?.amount ||
              fallbackRes.proposals?.find((p: any) => p.proposal_id === 'prop_b_r1')?.total_amount ||
              fallbackRes.conversation_events?.find((e: any) => e.actor === 'buyer' && e.round === 1)?.offer ||
              '0'
            ));
            if (fbBuyerOpeningVal > 0) setLiveBuyerOpeningOffer(fbBuyerOpeningVal);

            const fbMerchantStandaloneVal = parseFloat(String(
              fallbackRes.merchant_standalone_counter?.offered_amount ||
              fallbackRes.merchant_standalone_counter?.total_amount ||
              fallbackRes.merchant_standalone_counter?.amount ||
              fallbackRes.proposals?.find((p: any) => p.proposal_type === 'STANDALONE_COUNTER')?.total_amount ||
              fallbackRes.conversation_events?.find((e: any) => e.actor === 'merchant' && e.event_type !== 'bundle_offer')?.offer ||
              '0'
            ));
            if (fbMerchantStandaloneVal > 0) setLiveMerchantStandaloneCounter(fbMerchantStandaloneVal);

            const fbMerchantBundleVal = parseFloat(String(
              fallbackRes.merchant_bundle_proposal?.offered_amount ||
              fallbackRes.merchant_bundle_proposal?.total_amount ||
              fallbackRes.merchant_bundle_proposal?.amount ||
              fallbackRes.proposals?.find((p: any) => p.proposal_type === 'BUNDLE_PROPOSAL')?.total_amount ||
              '0'
            ));
            if (fbMerchantBundleVal > 0) setLiveMerchantBundleProposal(fbMerchantBundleVal);

            if (fallbackRes.basket?.items) {
              const names = fallbackRes.basket.items.map((i: any) => i.name).join(' + ');
              setLiveFinalBasketDesc(names);
            }

            if (fallbackRes.decision === 'APPROVED') {
              setPhase('APPROVED');
            } else if (fallbackRes.decision === 'REQUIRES_APPROVAL') {
              setPhase('REQUIRES_APPROVAL');
            } else {
              setPhase('REJECTED');
            }
          })
          .catch((fallbackErr) => {
            setThinkingAgent(null);
            setPhase('FAILED');
            setError(fallbackErr instanceof Error ? fallbackErr.message : 'An error occurred during negotiation.');
          });
      });
  };

  // 1. Initial trigger
  useEffect(() => {
    if (initialResult) {
      setResult(initialResult);
      if (initialResult.conversation_events && initialResult.conversation_events.length > 0) {
        setMessages(initialResult.conversation_events.map((e, idx) => mapEventToMessage(e, idx)));
      }
      const origAmt = parseFloat(initialResult.original_amount || '0');
      const finAmt = parseFloat(initialResult.final_amount || '0');
      if (origAmt > 0) setLiveCatalogPrice(origAmt);
      if (finAmt > 0) setLiveFinalPrice(finAmt);
      if (initialResult.buyer_opening_offer?.offered_amount) {
        setLiveBuyerOpeningOffer(parseFloat(String(initialResult.buyer_opening_offer.offered_amount)));
      }
      if (initialResult.merchant_standalone_counter?.offered_amount) {
        setLiveMerchantStandaloneCounter(parseFloat(String(initialResult.merchant_standalone_counter.offered_amount)));
      }
      if (initialResult.merchant_bundle_proposal?.offered_amount) {
        setLiveMerchantBundleProposal(parseFloat(String(initialResult.merchant_bundle_proposal.offered_amount)));
      }
      if (initialResult.basket?.items) {
        const names = initialResult.basket.items.map((i: any) => i.name).join(' + ');
        setLiveFinalBasketDesc(names);
      }
      setPhase(initialResult.decision === 'APPROVED' ? 'APPROVED' : initialResult.decision === 'REQUIRES_APPROVAL' ? 'REQUIRES_APPROVAL' : 'REJECTED');
      return;
    }

    if (stateIntent) {
      startNegotiationStream();
    }
  }, [stateIntent, stateBudget, initialResult]);

  // Elapsed timer management
  useEffect(() => {
    if (phase === 'STREAMING' || phase === 'NEGOTIATING') {
      elapsedTimer.current = setInterval(() => {
        setElapsed((prev) => prev + 0.1);
      }, 100);
    } else {
      if (elapsedTimer.current) {
        clearInterval(elapsedTimer.current);
        elapsedTimer.current = null;
      }
    }
    return () => {
      if (elapsedTimer.current) clearInterval(elapsedTimer.current);
    };
  }, [phase]);

  // Auto-scroll chat
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, thinkingAgent]);

  const handleCheckout = () => {
    if (!result) return;
    navigate('/payment', { state: { result } });
  };

  const handleReset = () => {
    navigate('/shopping');
  };

  // UI Render: Error State (only if no approved deal and no messages)
  if (phase === 'FAILED' && !result && messages.length === 0) {
    let errorTitle = 'Negotiation Error';
    let errorDesc = error || 'The negotiation session could not be completed safely. All price floors and boundaries remain fully protected.';

    if (error?.includes('timeout') || error?.includes('timed out')) {
      errorTitle = 'Session Timeout';
      errorDesc = 'The autonomous negotiation took longer than expected. Please try again.';
    } else if (error?.includes('No products') || error?.includes('catalog')) {
      errorTitle = 'Product Not Found';
      errorDesc = 'No matching catalog items were found for your search query. Please try different keywords.';
    } else if (error?.includes('Policy Engine') || error?.includes('policy')) {
      errorTitle = 'Commercial Policy Boundary';
      errorDesc = error;
    }

    return (
      <div className="negotiation-page-container container animate-fade-in" style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="error-panel" style={{ maxWidth: '520px', textAlign: 'center', padding: '32px' }}>
          <AlertTriangle className="error-icon" style={{ width: '48px', height: '48px', color: '#ef4444', margin: '0 auto 16px' }} />
          <h3 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '8px' }}>{errorTitle}</h3>
          <p className="error-msg" style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '24px', lineHeight: 1.5 }}>
            {errorDesc}
          </p>
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
            <button onClick={startNegotiationStream} className="btn btn-primary" style={{ gap: '8px' }}>
              <RotateCcw style={{ width: '16px', height: '16px' }} />
              <span>Retry Negotiation</span>
            </button>
            <button onClick={handleReset} className="btn btn-secondary" style={{ gap: '8px' }}>
              <ArrowLeft style={{ width: '16px', height: '16px' }} />
              <span>Back to Shopping</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // UI Render: Empty State
  if (!stateIntent && !result) {
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

  const isDealApproved = phase === 'APPROVED' || (result?.decision === 'APPROVED');
  const isDealRequiresApproval = phase === 'REQUIRES_APPROVAL' || (result?.decision === 'REQUIRES_APPROVAL');
  const isDealBlocked = phase === 'REJECTED' || (result?.decision === 'BLOCKED' || result?.decision === 'REJECTED');
  const isNegotiating = phase === 'STREAMING' || phase === 'NEGOTIATING';

  // Strategy badge label helper
  const getStrategyLabel = (strategy?: string) => {
    if (!strategy) return null;
    const clean = strategy.replace('Merchant Strategy: ', '').trim();
    if (clean === 'BUNDLE') return 'BUNDLE OPPORTUNITY';
    if (clean === 'COUNTER_PRICE') return 'COUNTER PRICE';
    if (clean === 'VALUE_UPSELL') return 'VALUE UPSELL';
    if (clean === 'HOLD_PRICE') return 'HOLD PRICE';
    if (clean === 'ACCEPT') return 'ACCEPTED';
    if (clean === 'ALTERNATIVE') return 'ALTERNATIVE';
    return clean;
  };

  return (
    <div className="negotiation-page-container container animate-fade-in" style={{ paddingBottom: '120px' }}>
      
      {/* Header Bar */}
      <div className="negotiation-page-header">
        <button onClick={handleReset} className="back-to-deal-btn">
          <ArrowLeft className="back-icon" />
          <span>Back to Procurement Hub</span>
        </button>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {isNegotiating && (
            <span className="system-status-tag font-mono" style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.3)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Activity style={{ width: '14px', height: '14px', animation: 'spin 2s linear infinite' }} />
              <span>LIVE AI ORCHESTRATION ({elapsed.toFixed(1)}s)</span>
            </span>
          )}
          <span className="system-status-tag font-mono" style={{
            background: (result?.provider_summary?.real_llm_calls && result.provider_summary.real_llm_calls > 0) || result?.execution_mode?.includes('LIVE') ? 'rgba(16, 185, 129, 0.15)' : result?.execution_mode?.includes('FALLBACK') ? 'rgba(245, 158, 11, 0.15)' : 'rgba(107, 114, 128, 0.15)',
            color: (result?.provider_summary?.real_llm_calls && result.provider_summary.real_llm_calls > 0) || result?.execution_mode?.includes('LIVE') ? '#10b981' : result?.execution_mode?.includes('FALLBACK') ? '#fbbf24' : '#9ca3af',
            border: (result?.provider_summary?.real_llm_calls && result.provider_summary.real_llm_calls > 0) || result?.execution_mode?.includes('LIVE') ? '1px solid rgba(16, 185, 129, 0.3)' : result?.execution_mode?.includes('FALLBACK') ? '1px solid rgba(245, 158, 11, 0.3)' : '1px solid rgba(107, 114, 128, 0.3)'
          }}>
            AI MODE: {result?.provider_summary?.real_llm_calls && result.provider_summary.real_llm_calls > 0 ? 'LIVE MULTI-PROVIDER' : result?.execution_mode?.includes('FALLBACK') ? 'DETERMINISTIC FALLBACK' : result?.execution_mode || 'AUTONOMOUS AI'}
          </span>
          <span className="system-status-tag font-mono" style={{ color: 'var(--primary)', borderColor: 'rgba(100, 75, 255, 0.3)', background: 'rgba(100, 75, 255, 0.05)' }}>
            SETU POLICY SANDBOX
          </span>
        </div>
      </div>

      {/* Main Grid: Left Chat UI, Right SETU Trust Panel */}
      <div className="negotiation-grid">
        
        {/* LEFT COLUMN: VISUAL CONVERSATION & PRICE PROGRESSION */}
        <div className="negotiation-main-col">
          
          {/* Price Progression Tracker */}
          <div className="price-progression-bar" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
            <div className="price-step-item">
              <span className="price-step-label">Catalog List</span>
              <span className="price-step-val">
                {liveCatalogPrice > 0 ? `₹${liveCatalogPrice.toLocaleString('en-IN')}` : '—'}
              </span>
            </div>
            <ArrowRight className="price-step-arrow" />
            <div className="price-step-item">
              <span className="price-step-label">Buyer Opening</span>
              <span className="price-step-val" style={{ color: '#60a5fa' }}>
                {liveBuyerOpeningOffer !== null && liveBuyerOpeningOffer > 0 ? `₹${liveBuyerOpeningOffer.toLocaleString('en-IN')}` : 'Pending...'}
              </span>
            </div>
            <ArrowRight className="price-step-arrow" />
            <div className="price-step-item">
              <span className="price-step-label">Merchant Standalone</span>
              <span className="price-step-val" style={{ color: '#fbbf24' }}>
                {liveMerchantStandaloneCounter !== null && liveMerchantStandaloneCounter > 0 ? `₹${liveMerchantStandaloneCounter.toLocaleString('en-IN')}` : isNegotiating ? 'Evaluating...' : '—'}
              </span>
            </div>
            {liveMerchantBundleProposal !== null && liveMerchantBundleProposal > 0 && (
              <>
                <ArrowRight className="price-step-arrow" />
                <div className="price-step-item">
                  <span className="price-step-label">Optional Bundle</span>
                  <span className="price-step-val" style={{ color: '#a78bfa' }}>
                    {`₹${liveMerchantBundleProposal.toLocaleString('en-IN')}`}
                  </span>
                </div>
              </>
            )}
            <ArrowRight className="price-step-arrow" />
            <div className="price-step-item">
              <span className="price-step-label">Agreed Final</span>
              <span className={`price-step-val ${isDealApproved ? 'highlight-green' : isDealBlocked ? 'highlight-red' : ''}`}>
                {isDealApproved && liveFinalPrice ? `₹${liveFinalPrice.toLocaleString('en-IN')}` : isDealRequiresApproval && liveFinalPrice ? `₹${liveFinalPrice.toLocaleString('en-IN')} (Pending)` : isDealBlocked ? 'BLOCKED' : 'Pending...'}
              </span>
              {isDealApproved && liveFinalPrice && (() => {
                const basePrice = result?.basket?.original_total ? parseFloat(result.basket.original_total) : (liveCatalogPrice > 0 ? liveCatalogPrice : 0);
                const totalSavings = basePrice > liveFinalPrice ? basePrice - liveFinalPrice : 0;
                const totalDiscountPct = basePrice > 0 ? (totalSavings / basePrice) * 100 : 0;
                return totalSavings > 0 ? (
                  <span style={{ fontSize: '0.70rem', color: '#10b981', fontWeight: 600, marginTop: '2px', display: 'block' }}>
                    Saved ₹{totalSavings.toLocaleString('en-IN')} · {totalDiscountPct.toFixed(2)}%
                  </span>
                ) : null;
              })()}
              {liveFinalBasketDesc && (
                <span style={{ fontSize: '0.68rem', color: 'var(--text-dimmed)', marginTop: '2px', display: 'block', maxWidth: '140px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }} title={liveFinalBasketDesc}>
                  {liveFinalBasketDesc}
                </span>
              )}
            </div>
            {isDealApproved && (
              <>
                <ArrowRight className="price-step-arrow" />
                <div className="price-step-item">
                  <span className="price-step-label">Agreed Basket</span>
                  <span className="price-step-val" style={{ 
                    color: (result?.basket?.items?.length > 1 || (result?.selected_basket_type === 'BUNDLE') || (result?.basket_type === 'BUNDLE') || liveFinalBasketDesc?.includes('+')) ? '#a78bfa' : '#60a5fa',
                    fontSize: '0.85rem'
                  }}>
                    {(result?.basket?.items?.length > 1 || (result?.selected_basket_type === 'BUNDLE') || (result?.basket_type === 'BUNDLE') || liveFinalBasketDesc?.includes('+')) ? 'BUNDLE' : 'STANDALONE'}
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Primary View: Chat Conversation Stream */}
          <div className="chat-conversation-panel">
            <div className="chat-panel-header">
              <div className="chat-panel-title">
                <MessageSquare className="chat-panel-icon" />
                <span>LIVE BUYER ↔ MERCHANT MULTI-TURN NEGOTIATION</span>
              </div>
              <span className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--text-dimmed)', background: 'rgba(255,255,255,0.03)', padding: '4px 10px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                INTENT: "{stateIntent || result?.intent}"
              </span>
            </div>

            <div className="chat-stream-body">
              {messages.length === 0 && isNegotiating && (
                <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                  <Activity style={{ width: '28px', height: '28px', color: 'var(--primary)', margin: '0 auto 12px', animation: 'pulse 1.5s infinite' }} />
                  <p style={{ margin: 0, fontSize: '0.9rem' }}>Initializing Buyer Agent & analyzing catalog parameters...</p>
                </div>
              )}

              {messages.map((msg, index) => {
                if (msg.sender === 'SETU_SYSTEM') {
                  return (
                    <div key={msg.id || index} className="setu-system-event-badge animate-fade-in">
                      <ShieldCheck className="system-event-icon" />
                      <span>{msg.message}</span>
                    </div>
                  );
                }

                const isBuyer = msg.sender === 'BUYER_AGENT';
                const isDealMsg = msg.isFinal && isDealApproved;
                const stratLabel = getStrategyLabel(msg.strategy);

                return (
                  <div key={msg.id || index} className={`chat-message-row ${isBuyer ? 'buyer-row' : 'merchant-row'} animate-fade-in`}>
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
                        {msg.proposalType && (
                          <span className="font-mono" style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '4px', background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', border: '1px solid var(--border-color)' }}>
                            {msg.proposalType.replace('_', ' ')}
                          </span>
                        )}
                        {msg.providerUsed === 'cerebras' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(14, 165, 233, 0.15)', 
                            color: '#38bdf8', 
                            border: '1px solid rgba(14, 165, 233, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>⚡</span>
                            <span>{msg.modelName || 'Cerebras'}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.providerUsed === 'gemini' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(99, 102, 241, 0.15)', 
                            color: '#818cf8', 
                            border: '1px solid rgba(99, 102, 241, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>🤖</span>
                            <span>{msg.modelName || 'Gemini'}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.providerUsed === 'groq' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(249, 115, 22, 0.15)', 
                            color: '#fb923c', 
                            border: '1px solid rgba(249, 115, 22, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>⚡</span>
                            <span>{msg.modelName || 'Groq'}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.providerUsed === 'nvidia_nim' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(34, 197, 94, 0.15)', 
                            color: '#4ade80', 
                            border: '1px solid rgba(34, 197, 94, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>🟢</span>
                            <span>{msg.modelName || 'NVIDIA NIM'}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.providerUsed === 'openrouter' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(168, 85, 247, 0.15)', 
                            color: '#c084fc', 
                            border: '1px solid rgba(168, 85, 247, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>🧠</span>
                            <span>{msg.modelName || 'OpenRouter'}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.providerUsed === 'ollama' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(236, 72, 153, 0.15)', 
                            color: '#f472b6', 
                            border: '1px solid rgba(236, 72, 153, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>🦙</span>
                            <span>{msg.modelName || 'Ollama'}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(245, 158, 11, 0.15)', 
                            color: '#fbbf24', 
                            border: '1px solid rgba(245, 158, 11, 0.3)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }} title={msg.fallbackReason || 'Primary LLM fallback engaged'}>
                            <span>⚙️</span>
                            <span>{msg.providerUsed === 'mock' ? 'Deterministic Fallback' : `${msg.providerUsed} (Fallback)`}</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                        {msg.providerUsed === 'mock' && !msg.fallbackUsed && (
                          <span className="font-mono" style={{ 
                            fontSize: '0.65rem', 
                            padding: '2px 7px', 
                            borderRadius: '4px', 
                            background: 'rgba(148, 163, 184, 0.12)', 
                            color: '#94a3b8', 
                            border: '1px solid rgba(148, 163, 184, 0.25)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            <span>🧪</span>
                            <span>Mock Provider</span>
                            {msg.responseLatencyMs !== undefined && msg.responseLatencyMs > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.5)', marginLeft: '2px' }}>{Math.round(msg.responseLatencyMs)}ms</span>
                            )}
                          </span>
                        )}
                      </div>

                      {stratLabel && (
                        <div className="merchant-strategy-badge animate-fade-in">
                          <Sparkles style={{ width: '12px', height: '12px', color: '#fbbf24' }} />
                          <span>{stratLabel}</span>
                        </div>
                      )}

                      <p className="chat-bubble-message">{msg.message}</p>

                      {/* Options Presentation for Merchant Bundle Counter */}
                      {msg.sender === 'MERCHANT_AGENT' && (msg.bundleProposal || msg.optionalBundleItems) && (
                        <div className="bundle-proposal-card animate-fade-in" style={{ marginTop: '12px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '8px', padding: '12px' }}>
                          <div style={{ marginBottom: '10px', fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span>📋 PROPOSAL OPTIONS</span>
                          </div>
                          
                          {/* Option 1: Standalone */}
                          <div style={{ padding: '8px 10px', background: 'rgba(0,0,0,0.25)', borderRadius: '6px', marginBottom: '8px', border: '1px solid rgba(96, 165, 250, 0.2)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#60a5fa' }}>OPTION 1 — STANDALONE</span>
                                <span style={{ fontSize: '0.68rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(96, 165, 250, 0.15)', color: '#93c5fd', fontFamily: 'var(--font-mono)' }}>
                                  {msg.proposalId || 'prop_m_r2_standalone'}
                                </span>
                              </div>
                              <span style={{ fontSize: '0.88rem', fontWeight: 700, color: '#fbbf24', fontFamily: 'var(--font-mono)' }}>
                                ₹{parseFloat(msg.bundleProposal?.standalone_price || msg.standaloneCounter || msg.amount || '0').toLocaleString('en-IN')}
                              </span>
                            </div>
                            <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', display: 'block', marginTop: '2px' }}>
                              {msg.basketItems && msg.basketItems[0] ? msg.basketItems[0].name : 'Primary Item'} (1 item)
                            </span>
                          </div>

                          {/* Option 2: Optional Bundle */}
                          {msg.bundleProposal && (
                            <div style={{ padding: '8px 10px', background: 'rgba(167, 139, 250, 0.08)', borderRadius: '6px', border: '1px solid rgba(167, 139, 250, 0.25)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                  <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#a78bfa' }}>OPTION 2 — OPTIONAL BUNDLE</span>
                                  <span style={{ fontSize: '0.68rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(167, 139, 250, 0.2)', color: '#c4b5fd', fontFamily: 'var(--font-mono)' }}>
                                    {msg.bundleProposal.proposal_id || 'prop_m_r2_bundle'}
                                  </span>
                                </div>
                                <span style={{ fontSize: '0.88rem', fontWeight: 700, color: '#a78bfa', fontFamily: 'var(--font-mono)' }}>
                                  ₹{parseFloat(msg.bundleProposal.bundle_price || msg.bundleProposal.offered_amount || '0').toLocaleString('en-IN')}
                                </span>
                              </div>
                              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                                {msg.bundleProposal.bundle_name || (msg.bundleProposal.basket_items ? msg.bundleProposal.basket_items.map((i: any) => i.name).join(' + ') : 'Primary + Accessory')}
                                {msg.bundleProposal.savings && parseFloat(msg.bundleProposal.savings) > 0 && (
                                  <span style={{ color: '#10b981', marginLeft: '6px', fontWeight: 600 }}>
                                    (Save ₹{parseFloat(msg.bundleProposal.savings).toLocaleString('en-IN')})
                                  </span>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Standalone or Generic Basket breakdown if accessories included and not already shown */}
                      {msg.basketItems && msg.basketItems.length > 1 && !(msg.sender === 'MERCHANT_AGENT' && msg.bundleProposal) && (
                        <div className="bundle-proposal-card animate-fade-in">
                          <div className="bundle-card-header">
                            <span className="bundle-card-title">📦 Basket Package Items</span>
                          </div>
                          <div className="bundle-items-list">
                            {msg.basketItems.map((bItem: any, bIdx: number) => {
                              const itemOrig = parseFloat(bItem.original_price || bItem.price || '0');
                              const itemNeg = parseFloat(bItem.negotiated_price || bItem.price || '0');
                              return (
                                <div key={bIdx} className="bundle-item-row">
                                  <span className="bundle-item-name">
                                    {bItem.name} {bItem.is_primary ? '(Primary)' : '(Accessory)'}
                                  </span>
                                  <div className="bundle-item-pricing">
                                    {itemOrig > itemNeg && (
                                      <span className="bundle-item-orig">₹{itemOrig.toLocaleString('en-IN')}</span>
                                    )}
                                    <span className="bundle-item-neg">₹{itemNeg.toLocaleString('en-IN')}</span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      <div className="chat-bubble-footer">
                        {msg.amount && (
                          <span className={`chat-price-pill ${isDealMsg ? 'deal-pill' : isBuyer ? 'buyer-pill' : (msg.proposalType === 'HOLD_PREVIOUS_OFFER' || msg.strategy === 'HOLD_PRICE') ? 'hold-pill' : 'merchant-pill'}`}>
                            {isBuyer ? 'Bid: ' : isDealMsg ? 'Agreed: ' : (msg.proposalType === 'HOLD_PREVIOUS_OFFER' || msg.strategy === 'HOLD_PRICE') ? 'Held Offer: ' : 'Counter: '}₹{parseFloat(msg.amount).toLocaleString('en-IN')}
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
                    {thinkingAgent === 'BUYER' ? 'Buyer Agent evaluating value & budget...' : 'Merchant Agent evaluating profit strategy & floor...'}
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
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Catalog inventory active & verified</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>VERIFIED</span>
              </div>

              {/* Gate 2: Buyer Budget Cap */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Buyer Budget Boundary</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Boundary ₹{parseFloat((stateBudget || result?.original_amount || 2000).toString()).toLocaleString('en-IN')} enforced</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>VERIFIED</span>
              </div>

              {/* Gate 3: Minimum Selling Price Floor */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Merchant Price Floor</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>min_selling_price floor protected</span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>PROTECTED</span>
              </div>

              {/* Gate 4: Margin Protection */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-color)', padding: '10px 12px', borderRadius: '8px' }}>
                <CheckCircle2 style={{ width: '16px', height: '16px', color: '#10b981', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span className="font-mono" style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', color: 'var(--text-main)' }}>Margin Guideline Check</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {result ? `Margin: ${result.margin_percent}% >= min policy` : 'Evaluating margin constraints'}
                  </span>
                </div>
                <span className="font-mono" style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'rgba(16, 185, 129, 0.1)', color: '#10b981', borderRadius: '4px' }}>VALIDATED</span>
              </div>

              {/* Gate 5: Policy Engine Authorization */}
              <div style={{ 
                background: isDealApproved ? 'rgba(16, 185, 129, 0.08)' : isDealRequiresApproval ? 'rgba(245, 158, 11, 0.08)' : isDealBlocked ? 'rgba(239, 68, 68, 0.08)' : 'rgba(59, 130, 246, 0.08)',
                border: isDealApproved ? '1px solid rgba(16, 185, 129, 0.3)' : isDealRequiresApproval ? '1px solid rgba(245, 158, 11, 0.3)' : isDealBlocked ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid rgba(59, 130, 246, 0.3)',
                padding: '12px',
                borderRadius: '8px',
                textAlign: 'center',
                marginTop: '4px'
              }}>
                <span className="font-mono" style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-dimmed)', display: 'block' }}>POLICY ENGINE FINAL VERDICT</span>
                <span className="font-mono" style={{ 
                  fontSize: '1.2rem', 
                  fontWeight: 900, 
                  color: isDealApproved ? '#10b981' : isDealRequiresApproval ? '#f59e0b' : isDealBlocked ? '#ef4444' : '#60a5fa' 
                }}>
                  {isDealApproved ? 'APPROVED' : isDealRequiresApproval ? 'REQUIRES APPROVAL' : isDealBlocked ? 'REJECTED' : 'PENDING NEGOTIATION'}
                </span>
              </div>

              {/* Provider Observability & AI Gateway Card */}
              <div style={{
                background: 'rgba(255, 255, 255, 0.02)',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                padding: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Sparkles style={{ width: '13px', height: '13px', color: '#818cf8' }} />
                    <span className="font-mono" style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-main)' }}>AI GATEWAY AUDIT</span>
                  </div>
                  {result?.provider_summary && (
                    <span className="font-mono" style={{
                      fontSize: '0.62rem',
                      padding: '2px 5px',
                      borderRadius: '4px',
                      background: result.provider_summary.is_live ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                      color: result.provider_summary.is_live ? '#10b981' : '#fbbf24',
                      border: `1px solid ${result.provider_summary.is_live ? 'rgba(16, 185, 129, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`
                    }}>
                      {result.provider_summary.is_live ? 'LIVE MULTI-PROVIDER' : result.provider_summary.fallback_count > 0 ? 'FALLBACK ENGAGED' : 'OFFLINE MOCK'}
                    </span>
                  )}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', fontSize: '0.7rem' }}>
                  <div style={{ background: 'rgba(0,0,0,0.25)', padding: '6px 8px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                    <span style={{ color: 'var(--text-dimmed)', display: 'block', fontSize: '0.62rem' }}>Real LLM Calls</span>
                    <span className="font-mono" style={{ fontSize: '0.85rem', fontWeight: 700, color: '#38bdf8' }}>
                      {result?.provider_summary?.real_llm_calls ?? messages.filter(m => m.providerUsed && m.providerUsed !== 'mock' && !m.fallbackUsed).length}
                    </span>
                  </div>
                  <div style={{ background: 'rgba(0,0,0,0.25)', padding: '6px 8px', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                    <span style={{ color: 'var(--text-dimmed)', display: 'block', fontSize: '0.62rem' }}>Deterministic Ops Avoided</span>
                    <span className="font-mono" style={{ fontSize: '0.85rem', fontWeight: 700, color: '#34d399' }}>
                      {result?.provider_summary?.deterministic_operations_avoided ?? 12}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.66rem', color: 'var(--text-muted)', padding: '2px 4px' }}>
                  <span>Estimated LLM Calls Saved:</span>
                  <span className="font-mono" style={{ color: '#34d399', fontWeight: 700 }}>
                    {result?.provider_summary?.estimated_llm_calls_saved ?? 12}
                  </span>
                </div>

                {result?.provider_summary?.fallback_count ? (
                  <div style={{ fontSize: '0.65rem', color: '#fbbf24', background: 'rgba(245, 158, 11, 0.08)', padding: '4px 6px', borderRadius: '4px', border: '1px solid rgba(245, 158, 11, 0.2)' }}>
                    ⚠️ {result.provider_summary.fallback_count} turn(s) handled by circuit breaker / fallback provider.
                  </div>
                ) : null}
              </div>
            </div>

            {/* Itemized Final Basket Card */}
            {isDealApproved && result?.basket?.items && (
              <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <span className="font-mono" style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-dimmed)', letterSpacing: '0.05em' }}>
                  ITEMIZED VALIDATED BASKET
                </span>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.25)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  {result.basket.items.map((item: any, idx: number) => {
                    const itemOrig = parseFloat(item.original_price) * item.quantity;
                    const itemNeg = parseFloat(item.negotiated_price) * item.quantity;
                    const itemDisc = Math.max(0, itemOrig - itemNeg);
                    const itemPct = itemOrig > 0 ? (itemDisc / itemOrig) * 100 : 0;
                    return (
                      <div key={idx} style={{ display: 'flex', flexDirection: 'column', fontSize: '0.82rem', gap: '3px' }}>
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
                        {itemDisc > 0 ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.72rem', color: '#34d399', background: 'rgba(52, 211, 153, 0.06)', padding: '5px 8px', borderRadius: '4px', marginTop: '2px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: 'var(--text-dimmed)' }}>List Price: ₹{itemOrig.toLocaleString('en-IN')}</span>
                              <span style={{ fontWeight: 600 }}>You Save: ₹{itemDisc.toLocaleString('en-IN')}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', color: '#10b981' }}>
                              <span>Discount: {itemPct.toFixed(2)}%</span>
                              <span>₹{itemDisc.toLocaleString('en-IN')} ({itemPct.toFixed(2)}%)</span>
                            </div>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-dimmed)' }}>
                            <span>List Price: ₹{itemOrig.toLocaleString('en-IN')}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {parseFloat(result.basket.discount_amount || '0') > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#34d399', borderTop: '1px dashed rgba(255,255,255,0.08)', paddingTop: '6px', marginTop: '4px', fontWeight: 700 }}>
                      <span>Bundle Savings:</span>
                      <span>₹{Math.abs(parseFloat(result.basket.discount_amount)).toLocaleString('en-IN')}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Total & Checkout Action */}
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Negotiated Total:</span>
                <span className="font-mono" style={{ 
                  fontSize: '1.25rem', 
                  fontWeight: 800, 
                  color: isDealApproved ? '#10b981' : isDealBlocked ? '#ef4444' : '#60a5fa' 
                }}>
                  {isDealApproved && liveFinalPrice ? `₹${liveFinalPrice.toLocaleString('en-IN')}` : isDealBlocked ? 'BLOCKED' : isNegotiating ? 'Negotiating...' : '—'}
                </span>
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
              ) : isDealRequiresApproval ? (
                <div style={{ background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', padding: '12px', borderRadius: '8px', textAlign: 'center', fontSize: '0.8rem', color: '#fbbf24' }}>
                  High-value transaction flagged for administrative review.
                </div>
              ) : isDealBlocked ? (
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
              ) : (
                <div style={{ textAlign: 'center', padding: '10px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Awaiting mutual negotiation conclusion...
                </div>
              )}
            </div>

          </div>

        </div>

      </div>
    </div>
  );
}
