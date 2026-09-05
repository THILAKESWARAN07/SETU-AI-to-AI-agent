import os
import sys
from decimal import Decimal

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.app.database import SessionLocal
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import get_provider_for_agent

def main():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("SETU LIVE DEMO VERIFICATION — MERCHANT FINANCIAL SUMMARY")
        print("=" * 60)

        buyer = BuyerAgent(get_provider_for_agent("buyer"))
        merchant = MerchantAgent(get_provider_for_agent("merchant"))
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        # 1. Approved Scenario
        print("\n>>> Scenario 1: APPROVED Deal (Wireless Earbuds)")
        res1 = orchestrator.run_negotiation_loop(
            buyer_id="demo-buyer-001",
            intent="I want to buy wireless earbuds under 2000",
            budget=Decimal("2000.00"),
            max_rounds=4
        )

        print(f"Status / Decision: {res1.get('decision')}")
        print(f"Final Negotiated Amount: ₹{res1.get('final_amount')}")
        print(f"Provider Summary: Real LLM={res1.get('provider_summary', {}).get('real_llm_calls')}, Mock={res1.get('provider_summary', {}).get('mock_calls')}")
        
        mf1 = res1.get("merchant_financials", {})
        print("\n┌──────────────────────────────────────────────────┐")
        print("│ 🔒 MERCHANT ONLY                                 │")
        print("│ Visible only to the merchant                     │")
        print("├──────────────────────────────────────────────────┤")
        print(f"│ Original Price:       ₹{Decimal(mf1.get('original_price', '0')):>10.2f}               │")
        print(f"│ Merchant Cost:        ₹{Decimal(mf1.get('merchant_cost', '0')):>10.2f}               │")
        print(f"│ Final Price:          ₹{Decimal(mf1.get('final_price', '0')):>10.2f}               │")
        print(f"│ Merchant Profit:      ₹{Decimal(mf1.get('merchant_profit', '0')):>10.2f}               │")
        print(f"│ Merchant Margin:       {Decimal(mf1.get('merchant_margin_percent', '0')):>9.2f}%               │")
        print(f"│ Customer Savings:     ₹{Decimal(mf1.get('customer_savings', '0')):>10.2f}               │")
        print(f"│ Customer Discount:     {Decimal(mf1.get('customer_discount_percent', '0')):>9.2f}%               │")
        print(f"│ Policy Check:         {'✓ Within margin policy' if mf1.get('is_within_margin_policy') else '✗ Policy issue'}     │")
        print("└──────────────────────────────────────────────────┘")

        # 2. Blocked Scenario
        print("\n>>> Scenario 2: BLOCKED Deal (Predatory price lowball)")
        buyer2 = BuyerAgent(get_provider_for_agent("buyer"))
        merchant2 = MerchantAgent(get_provider_for_agent("merchant"))
        orchestrator2 = NegotiationOrchestrator(db, buyer2, merchant2)
        try:
            res2 = orchestrator2.run_negotiation_loop(
                buyer_id="demo-buyer-002",
                intent="I want premium earbuds for 200 rs only",
                budget=Decimal("200.00"),
                max_rounds=2
            )
        except NegotiationError as e:
            res2 = e.result_data

        print(f"Status / Decision: {res2.get('decision')}")
        print(f"Final Negotiated Amount: {res2.get('final_amount') if res2.get('final_amount') is not None else 'N/A'}")
        
        mf2 = res2.get("merchant_financials", {})
        print("\n┌──────────────────────────────────────────────────┐")
        print("│ 🔒 MERCHANT ONLY                                 │")
        print("│ Visible only to the merchant                     │")
        print("├──────────────────────────────────────────────────┤")
        print(f"│ Original Price:       {('₹' + str(mf2.get('original_price'))) if mf2.get('original_price') else 'N/A':>10}               │")
        print(f"│ Merchant Cost:        {('₹' + str(mf2.get('merchant_cost'))) if mf2.get('merchant_cost') else 'N/A':>10}               │")
        print(f"│ Final Price:          {str(mf2.get('final_price') or 'N/A'):>10}               │")
        print(f"│ Merchant Profit:      {str(mf2.get('merchant_profit') or 'N/A'):>10}               │")
        print(f"│ Merchant Margin:      {str(mf2.get('merchant_margin_percent') or 'N/A'):>10}               │")
        print(f"│ Block Reason:         {str(mf2.get('block_reason') or res2.get('reasons', [''])[0])[:25]:<25}  │")
        print("└──────────────────────────────────────────────────┘")

    finally:
        db.close()

if __name__ == "__main__":
    main()
