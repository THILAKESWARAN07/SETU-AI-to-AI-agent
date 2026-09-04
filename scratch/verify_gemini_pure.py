import os
import sys
import json
import time
from decimal import Decimal

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, ".")

# 1. Force Pure Gemini without fallback
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["LLM_MODEL"] = "gemini-3.1-flash-lite"
os.environ["LLM_FALLBACK_TO_MOCK"] = "false"
os.environ["LLM_TIMEOUT_SECONDS"] = "30.0"

from backend.app.database import SessionLocal
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.agents.provider import get_provider, GeminiProvider

print("=" * 80, flush=True)
print("STARTING GEMINI-ONLY END-TO-END VERIFICATION RUN (gemini-3.1-flash-lite)", flush=True)
print("=" * 80, flush=True)

provider = get_provider()
print(f"Provider Type: {type(provider).__name__}", flush=True)
print(f"Provider Name: {provider.provider_name}, Model: {provider.model_name}", flush=True)
assert isinstance(provider, GeminiProvider), f"Expected GeminiProvider, got {type(provider)}"

runs_to_execute = 3
results = []

for run_idx in range(1, runs_to_execute + 1):
    print(f"\n{'=' * 30} RUN {run_idx} / {runs_to_execute} {'=' * 30}", flush=True)
    db = SessionLocal()
    try:
        buyer_provider = get_provider()
        merchant_provider = get_provider()
        
        buyer = BuyerAgent(provider=buyer_provider)
        merchant = MerchantAgent(provider=merchant_provider)
        orchestrator = NegotiationOrchestrator(db=db, buyer=buyer, merchant=merchant)
        
        events_collected = []
        def event_listener(evt):
            events_collected.append(evt)
            actor = evt.get("actor", "")
            if actor in ("buyer", "merchant"):
                p_used = evt.get("provider_used")
                m_name = evt.get("model_name")
                fb_used = evt.get("fallback_used")
                lat_ms = evt.get("response_latency_ms")
                msg = (evt.get("message") or evt.get("reason") or evt.get("details") or "")
                msg_clean = msg.replace("\u20b9", "INR ")
                print(f"  [{actor.upper()} #{evt.get('sequence')}] Type: {evt.get('type') or evt.get('event_type')} | Action: {evt.get('action')} | Amount: INR {evt.get('amount')} | Provider: {p_used} | Model: {m_name} | Fallback: {fb_used} | Latency: {lat_ms}ms", flush=True)
                if msg_clean:
                    print(f"    Content: \"{msg_clean[:120]}...\"", flush=True)

        outcome = None
        try:
            outcome = orchestrator.run_negotiation_loop(
                buyer_id=f"buyer_gemini_test_{run_idx}",
                intent="I need a Samsung Galaxy A15 under 12000",
                budget=Decimal("12000.00"),
                max_rounds=4,
                on_event=event_listener
            )
        except NegotiationError as ne:
            outcome = ne.result_data or {}
            print(f"  Negotiation completed with status: {outcome.get('decision', 'REJECTED')}", flush=True)
        
        summary = outcome.get("provider_summary", {})
        print(f"\nRun {run_idx} Summary:", flush=True)
        print(f"  Decision: {outcome.get('decision')}", flush=True)
        print(f"  Final Amount: INR {outcome.get('final_amount')}", flush=True)
        print(f"  Provider Summary: {json.dumps(summary, indent=4)}", flush=True)
        
        # Strict validation
        assert summary.get("gemini_calls", 0) > 0, f"Run {run_idx} had 0 gemini calls!"
        assert summary.get("mock_calls", 0) == 0, f"Run {run_idx} had mock calls: {summary.get('mock_calls')}"
        assert summary.get("fallback_count", 0) == 0, f"Run {run_idx} had fallback count > 0"
        assert summary.get("all_agent_turns_used_gemini") is True, f"Run {run_idx} all_agent_turns_used_gemini is not True"
        
        # Verify every buyer and merchant event has valid Gemini metadata
        for evt in outcome.get("conversation_events", []):
            if evt.get("actor") in ("buyer", "merchant"):
                assert evt.get("provider_used") == "gemini", f"Event {evt.get('sequence')} provider_used is not 'gemini': {evt}"
                assert evt.get("model_name") == "gemini-3.1-flash-lite", f"Event {evt.get('sequence')} model_name mismatch: {evt}"
                assert evt.get("fallback_used") is False, f"Event {evt.get('sequence')} fallback_used is True: {evt}"
                assert evt.get("fallback_reason") is None, f"Event {evt.get('sequence')} fallback_reason is not None: {evt}"
                assert evt.get("response_latency_ms", 0) > 0, f"Event {evt.get('sequence')} latency is 0: {evt}"
                
        results.append({
            "run": run_idx,
            "decision": outcome.get("decision"),
            "final_amount": str(outcome.get("final_amount")),
            "provider_summary": summary,
            "events_count": len(outcome.get("conversation_events", []))
        })
    finally:
        db.close()
    
    if run_idx < runs_to_execute:
        print("\nWaiting 6s between negotiation runs...", flush=True)
        time.sleep(6)

print("\n" + "=" * 80, flush=True)
print("ALL 3 GEMINI-ONLY RUNS COMPLETED SUCCESSFULLY WITH 100% REAL GEMINI METADATA!", flush=True)
print(json.dumps(results, indent=2), flush=True)
print("=" * 80, flush=True)
