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
        buyer_max_budget: Optional[Decimal] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generates a profitable bundle prescription containing complementary accessories with bundle discounts.
        """
        if not related_prods:
            return None

        # Calculate combined list price and cost
        total_list = Decimal(str(primary_prod.get("price", "0.00")))
        total_cost = Decimal(str(primary_prod.get("cost", "0.00")))
        total_min_sp = Decimal(str(primary_prod.get("min_selling_price") or primary_prod.get("cost", "0.00")))

        bundle_items = [
            {
                "product_id": primary_prod["id"],
                "name": primary_prod["name"],
                "quantity": 1,
                "original_price": Decimal(str(primary_prod["price"])),
                "negotiated_price": Decimal(str(primary_prod["price"])),
                "is_primary": True
            }
        ]

        # Add up to 3 complementary accessories
        for acc in related_prods[:3]:
            if acc.get("inventory", 0) > 0 and acc.get("active", True):
                acc_price = Decimal(str(acc["price"]))
                acc_cost = Decimal(str(acc.get("cost", "0.00")))
                acc_min_sp = Decimal(str(acc.get("min_selling_price") or acc.get("cost", "0.00")))
                
                total_list += acc_price
                total_cost += acc_cost
                total_min_sp += acc_min_sp

                # Apply a healthy 15-20% bundle discount on accessory while protecting margin
                discounted_acc_price = max(acc_min_sp, acc_price * Decimal("0.80")).quantize(Decimal("0.01"))

                bundle_items.append({
                    "product_id": acc["id"],
                    "name": acc["name"],
                    "quantity": 1,
                    "original_price": acc_price,
                    "negotiated_price": discounted_acc_price,
                    "is_primary": False
                })

        # Apply primary product bundle discount
        primary_bundle_price = max(total_min_sp - sum(item["negotiated_price"] for item in bundle_items[1:]), primary_prod["price"] * Decimal("0.92")).quantize(Decimal("0.01"))
        bundle_items[0]["negotiated_price"] = primary_bundle_price

        bundle_total = sum(item["negotiated_price"] for item in bundle_items)
        bundle_discount = total_list - bundle_total

        return {
            "bundle_items": bundle_items,
            "original_total": total_list,
            "bundle_total": bundle_total,
            "discount_amount": bundle_discount,
            "total_cost": total_cost,
            "margin_percent": (((bundle_total - total_cost) / bundle_total) * Decimal("100")).quantize(Decimal("0.01")) if bundle_total > Decimal("0") else Decimal("0.00")
        }
