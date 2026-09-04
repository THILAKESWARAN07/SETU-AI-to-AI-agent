from decimal import Decimal
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("setu.agents.pricing_strategy")

class MerchantPricingStrategy:
    """
    Deterministic Merchant Strategy Engine.
    Calculates allowed price floors, inventory-adjusted discount flexibility,
    profitable accessory bundling, and monotonic concessions per negotiation round.
    """

    @staticmethod
    def calculate_pricing_bounds(
        cost: Decimal,
        base_price: Decimal,
        min_selling_price: Optional[Decimal],
        inventory: int,
        round_idx: int,
        max_rounds: int = 4,
        min_margin_percent: Decimal = Decimal("15.00"),
        max_discount_percent: Decimal = Decimal("15.00")
    ) -> Dict[str, Decimal]:
        """
        Calculates mathematically enforced price bounds and recommended concession price for the current round.
        """
        cost = Decimal(str(cost))
        base_price = Decimal(str(base_price))
        min_margin_percent = Decimal(str(min_margin_percent))
        max_discount_percent = Decimal(str(max_discount_percent))
        if min_selling_price is not None:
            min_selling_price = Decimal(str(min_selling_price))

        # Absolute hard price floor derived from cost and min margin policy
        margin_price_floor = (cost / (Decimal("1.00") - (min_margin_percent / Decimal("100.00")))).quantize(Decimal("0.01"))
        
        # Absolute hard floor is maximum of min_selling_price, margin floor, and cost
        configured_floor = min_selling_price if min_selling_price is not None else margin_price_floor
        absolute_floor = max(configured_floor, margin_price_floor, cost).quantize(Decimal("0.01"))

        # Maximum policy discount ceiling
        policy_discount_floor = (base_price * (Decimal("1.00") - (max_discount_percent / Decimal("100.00")))).quantize(Decimal("0.01"))
        absolute_floor = max(absolute_floor, policy_discount_floor)

        # Inventory Adjustment:
        # High inventory (> 20 units) allows full discount flexibility
        # Moderate inventory (6-20 units) allows standard flexibility
        # Low inventory (<= 5 units) restricts discount flexibility
        if inventory > 20:
            inventory_flexibility = Decimal("1.00")  # 100% of allowed discount
        elif inventory >= 6:
            inventory_flexibility = Decimal("0.80")  # 80% of allowed discount
        else:
            inventory_flexibility = Decimal("0.40")  # Only 40% of allowed discount (scarcity pricing)

        max_allowed_discount = (base_price - absolute_floor) * inventory_flexibility
        merchant_best_price = (base_price - max_allowed_discount).quantize(Decimal("0.01"))

        # Monotonic Round Concession Curve:
        # Round 1: List price or small concession (25% of max discount)
        # Round 2: 50% of max discount
        # Round 3: 75% of max discount
        # Round 4 / Final: 100% of max discount (best price)
        round_fraction = Decimal(min(round_idx, max_rounds)) / Decimal(max_rounds)
        concession_amount = (max_allowed_discount * round_fraction).quantize(Decimal("0.01"))
        target_offer_price = max(base_price - concession_amount, merchant_best_price, absolute_floor)

        return {
            "base_price": base_price,
            "cost": cost,
            "absolute_floor": absolute_floor,
            "merchant_best_price": merchant_best_price,
            "target_offer_price": target_offer_price,
            "inventory_flexibility": inventory_flexibility
        }

    @staticmethod
    def generate_bundle_prescription(
        primary_prod: Dict[str, Any],
        related_prods: List[Dict[str, Any]],
        buyer_max_budget: Optional[Decimal] = None,
        min_margin_percent: Decimal = Decimal("15.00")
    ) -> Optional[Dict[str, Any]]:
        """
        Generates a profitable bundle prescription containing complementary accessories with bundle discounts.
        Ensures EVERY individual basket item satisfies its own effective price floor and minimum margin.
        """
        if not related_prods:
            return None

        min_margin_percent = Decimal(str(min_margin_percent))
        if buyer_max_budget is not None:
            buyer_max_budget = Decimal(str(buyer_max_budget))

        # Calculate combined list price and cost
        primary_price = Decimal(str(primary_prod.get("price", "0.00")))
        primary_cost = Decimal(str(primary_prod.get("cost", "0.00")))
        primary_min_sp = Decimal(str(primary_prod.get("min_selling_price") or primary_prod.get("cost", "0.00")))

        margin_factor = Decimal("1.00") - (min_margin_percent / Decimal("100.00"))
        primary_floor = max(primary_min_sp, primary_cost / margin_factor, primary_cost).quantize(Decimal("0.01"))
        
        # Primary bundle discount (up to 8% discount, but bounded strictly by primary item floor)
        primary_discounted_price = max(primary_floor, (primary_price * Decimal("0.92")).quantize(Decimal("0.01")))

        bundle_items = [
            {
                "product_id": primary_prod["id"],
                "name": primary_prod["name"],
                "quantity": 1,
                "original_price": primary_price,
                "negotiated_price": primary_discounted_price,
                "is_primary": True,
                "cost": primary_cost,
                "effective_floor": primary_floor
            }
        ]

        total_list = primary_price
        total_cost = primary_cost

        # Add up to 3 complementary accessories with valid inventory
        for acc in related_prods[:3]:
            if acc.get("inventory", 0) > 0 and acc.get("active", True):
                acc_price = Decimal(str(acc["price"]))
                acc_cost = Decimal(str(acc.get("cost", "0.00")))
                acc_min_sp = Decimal(str(acc.get("min_selling_price") or acc.get("cost", "0.00")))
                
                acc_floor = max(acc_min_sp, acc_cost / margin_factor, acc_cost).quantize(Decimal("0.01"))
                
                # Apply a healthy 15-20% bundle discount on accessory while protecting individual margin floor
                discounted_acc_price = max(acc_floor, (acc_price * Decimal("0.80")).quantize(Decimal("0.01")))

                total_list += acc_price
                total_cost += acc_cost

                bundle_items.append({
                    "product_id": acc["id"],
                    "name": acc["name"],
                    "quantity": 1,
                    "original_price": acc_price,
                    "negotiated_price": discounted_acc_price,
                    "is_primary": False,
                    "cost": acc_cost,
                    "effective_floor": acc_floor
                })

        # Calculate exact sum of all item negotiated prices
        bundle_total = sum(item["negotiated_price"] for item in bundle_items).quantize(Decimal("0.01"))
        bundle_discount = (total_list - bundle_total).quantize(Decimal("0.01"))
        margin_percent = (((bundle_total - total_cost) / bundle_total) * Decimal("100")).quantize(Decimal("0.01")) if bundle_total > Decimal("0") else Decimal("0.00")

        return {
            "bundle_items": bundle_items,
            "original_total": total_list,
            "bundle_total": bundle_total,
            "discount_amount": bundle_discount,
            "total_cost": total_cost,
            "margin_percent": margin_percent
        }

    @staticmethod
    def evaluate_sales_strategy(
        primary_prod: Dict[str, Any],
        related_prods: List[Dict[str, Any]],
        buyer_offer_price: Decimal,
        buyer_max_budget: Optional[Decimal],
        standalone_preferred: bool = False,
        round_idx: int = 1,
        max_rounds: int = 4,
        min_margin_percent: Decimal = Decimal("15.00"),
        max_discount_percent: Decimal = Decimal("15.00")
    ) -> Dict[str, Any]:
        """
        Evaluates merchant pricing strategy:
        - List price, cost price, effective floor, min margin, inventory.
        - Strategic actions: HOLD_PRICE, COUNTER_PRICE, ACCEPT, BUNDLE, VALUE_UPSELL, ALTERNATIVE.
        - Calculates standalone_profit, bundle_profit, bundle_value_to_buyer.
        - Deterministic acceptance: accept ONLY if buyer offer >= merchant target threshold or round final concession.
        """
        base_price = Decimal(str(primary_prod.get("price", "0.00")))
        cost = Decimal(str(primary_prod.get("cost", "0.00")))
        min_sp = Decimal(str(primary_prod.get("min_selling_price") or primary_prod.get("cost", "0.00")))
        inventory = int(primary_prod.get("inventory", 10))
        buyer_offer_price = Decimal(str(buyer_offer_price))
        min_margin_percent = Decimal(str(min_margin_percent))
        max_discount_percent = Decimal(str(max_discount_percent))
        if buyer_max_budget is not None:
            buyer_max_budget = Decimal(str(buyer_max_budget))

        bounds = MerchantPricingStrategy.calculate_pricing_bounds(
            cost=cost,
            base_price=base_price,
            min_selling_price=min_sp,
            inventory=inventory,
            round_idx=round_idx,
            max_rounds=max_rounds,
            min_margin_percent=min_margin_percent,
            max_discount_percent=max_discount_percent
        )

        absolute_floor = bounds["absolute_floor"]
        target_offer_price = bounds["target_offer_price"]
        merchant_best_price = bounds["merchant_best_price"]

        # Calculate potential bundle
        bundle_info = None
        if related_prods and not standalone_preferred:
            bundle_prescription = MerchantPricingStrategy.generate_bundle_prescription(
                primary_prod=primary_prod,
                related_prods=related_prods,
                buyer_max_budget=buyer_max_budget,
                min_margin_percent=min_margin_percent
            )
            if bundle_prescription:
                bundle_total = bundle_prescription["bundle_total"]
                bundle_cost = bundle_prescription["total_cost"]
                bundle_list = bundle_prescription["original_total"]
                
                bundle_profit = bundle_total - bundle_cost
                standalone_profit = buyer_offer_price - cost
                bundle_value_to_buyer = bundle_list - bundle_total
                
                within_budget = (buyer_max_budget is None) or (bundle_total <= buyer_max_budget)
                
                if within_budget and bundle_profit > standalone_profit and bundle_value_to_buyer > Decimal("0"):
                    bundle_info = {
                        "prescription": bundle_prescription,
                        "bundle_profit": bundle_profit,
                        "standalone_profit": standalone_profit,
                        "bundle_value_to_buyer": bundle_value_to_buyer
                    }

        # Strategy decision:
        # 1. If buyer offer is below absolute floor:
        if buyer_offer_price < absolute_floor:
            if buyer_offer_price < (absolute_floor * Decimal("0.70")):
                strategy = "HOLD_PRICE"
                recommended_standalone_price = base_price
                reason = f"Buyer offer of ₹{buyer_offer_price} is severely below price floor of ₹{absolute_floor}. Holding price at ₹{base_price}."
            else:
                strategy = "COUNTER_PRICE"
                recommended_standalone_price = max(target_offer_price, absolute_floor)
                reason = f"Buyer offer of ₹{buyer_offer_price} is below floor of ₹{absolute_floor}. Countering at ₹{recommended_standalone_price}."
        
        # 2. If buyer offer meets or exceeds target price:
        elif buyer_offer_price >= target_offer_price:
            strategy = "ACCEPT"
            recommended_standalone_price = buyer_offer_price
            reason = f"Buyer offer of ₹{buyer_offer_price} meets merchant target price of ₹{target_offer_price}."

        # 3. If round is final concession and buyer offer >= merchant_best_price:
        elif round_idx >= 3 and buyer_offer_price >= merchant_best_price:
            strategy = "ACCEPT"
            recommended_standalone_price = buyer_offer_price
            reason = f"In round {round_idx}, buyer offer of ₹{buyer_offer_price} meets merchant best concession price of ₹{merchant_best_price}."

        # 4. If bundle is strategically beneficial and buyer didn't disallow it:
        elif bundle_info is not None:
            strategy = "BUNDLE"
            recommended_standalone_price = target_offer_price
            reason = f"Countering standalone at ₹{target_offer_price} and proposing strategic accessory bundle for higher total value and profit."

        # 5. Otherwise, counter price
        else:
            strategy = "COUNTER_PRICE"
            # Concession price halfway between buyer offer and target price, bounded by floor
            step_price = ((target_offer_price + buyer_offer_price) / Decimal("2.00")).quantize(Decimal("0.01"))
            recommended_standalone_price = max(step_price, merchant_best_price, absolute_floor)
            reason = f"Countering with concession price of ₹{recommended_standalone_price} (bounds: ₹{absolute_floor} - ₹{base_price})."

        return {
            "strategy": strategy,
            "bounds": bounds,
            "recommended_standalone_price": recommended_standalone_price,
            "bundle_info": bundle_info,
            "reason": reason
        }
