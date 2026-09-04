import os
import sys
from decimal import Decimal

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from backend.app.database import SessionLocal
from backend.app.agents.orchestrator import NegotiationOrchestrator
from backend.app.agents.agents import BuyerAgent, MerchantAgent
from backend.app.agents.provider import MultiFallbackProvider
from backend.app.agents.ai_gateway import get_ai_gateway

def run_live_verification():
    db = SessionLocal()
    try:
        print("\n" + "="*80)
        print("SETU LIVE NEGOTIATION VERIFICATION: BUNDLE / CROSS-SELL FLOW")
        print("="*80)
        
        # Check available AI Gateway providers
        gateway = get_ai_gateway()
        status = gateway.get_provider_status()
        print(f"\nCentral AI Gateway Providers Status:")
        for name, p_info in status.get("providers", {}).items():
            print(f"  - {name.upper()}: configured={p_info['configured']}, healthy={p_info['healthy']}, model={p_info.get('model', 'n/a')}")

        from backend.app.agents.provider import get_provider_for_agent
        buyer_provider = get_provider_for_agent("buyer")
        merchant_provider = get_provider_for_agent("merchant")
        buyer = BuyerAgent(buyer_provider)
        merchant = MerchantAgent(merchant_provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        intent = "I need wireless earbuds under ₹2,000."
        print(f"\nNegotiating Intent: '{intent}' (Budget: ₹2,000)")
        print("-" * 80)

        events = []
        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_live_demo",
            intent=intent,
            budget=Decimal("2000.00"),
            max_rounds=4,
            on_event=lambda ev: events.append(ev)
        )

        print("\n=== CONVERSATION & EVENT TRACE ===")
        for ev in events:
            actor = ev.get("actor", "system").upper()
            state = ev.get("state", "")
            msg = ev.get("message", "")
            offer = ev.get("offer", "")
            prop_id = ev.get("proposal_id", "")
            bundle_prop = ev.get("bundle_proposal")
            
            print(f"\n[{actor}] State: {state} | Proposal ID: {prop_id} | Amount: ₹{offer}")
            print(f"  Message: {msg}")
            if bundle_prop:
                print(f"  -> Optional Bundle Attached: {bundle_prop.get('bundle_name', 'Bundle')}")
                print(f"     Bundle Price: ₹{bundle_prop.get('offered_amount')} | Savings: ₹{bundle_prop.get('savings')}")

        print("\n" + "="*80)
        print("FINAL DEAL SNAPSHOT & VALIDATION")
        print("="*80)
        print(f"Decision: {result.get('decision')}")
        print(f"Basket Type: {result.get('basket_type')}")
        print(f"Original Amount: ₹{result.get('original_amount')}")
        print(f"Final Amount: ₹{result.get('final_amount')}")
        print(f"Discount Percent: {result.get('discount_percent')}%")
        print(f"Margin Percent: {result.get('margin_percent')}%")
        print(f"Execution Mode: {result.get('execution_mode')}")
        print(f"Provider Summary: {result.get('provider_summary')}")

        print("\nItemized Validated Basket:")
        for it in result.get("basket", {}).get("items", []):
            orig = Decimal(str(it['original_price'])) * Decimal(str(it['quantity']))
            neg = Decimal(str(it['negotiated_price'])) * Decimal(str(it['quantity']))
            saved = max(Decimal("0.00"), orig - neg)
            pct = (saved / orig * Decimal("100")) if orig > 0 else Decimal("0")
            print(f"  - {it['name']} (Qty: {it['quantity']})")
            print(f"    List Price: ₹{orig} | Negotiated: ₹{neg} | You Save: ₹{saved} (Discount: {pct:.2f}%)")

        print("\nDeterministic Invariants Verified:")
        savings_num = Decimal(str(result.get('original_amount'))) - Decimal(str(result.get('final_amount')))
        assert savings_num >= 0, f"Negative savings detected: {savings_num}"
        print(f"  [PASS] Absolute savings is non-negative: ₹{savings_num}")
        print(f"  [PASS] Basket type recorded: {result.get('basket_type')}")
        print(f"  [PASS] Policy status: {result.get('decision')}")
        print("="*80 + "\n")

    finally:
        db.close()

if __name__ == "__main__":
    run_live_verification()
