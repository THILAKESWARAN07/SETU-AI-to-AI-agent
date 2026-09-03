from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional
from backend.app.models import Product, MerchantPolicy

class PolicyEngine:
    @staticmethod
    def evaluate(
        product: Product,
        policy: MerchantPolicy,
        quantity: int,
        final_amount: Decimal,
        buyer_budget: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """
        Deterministically evaluates a proposed purchase request against merchant policies.
        
        Args:
            product: The product database model.
            policy: The active merchant policy database model.
            quantity: The quantity requested.
            final_amount: The proposed total amount (discounted price * quantity).
            buyer_budget: Optional maximum budget of the buyer.
            
        Returns:
            Dict containing:
                "decision": "APPROVED" | "BLOCKED" | "REQUIRES_APPROVAL" (Canonical statuses)
                "reasons": List[str]
                "policy_version": str
                "calculated_margin_percent": Decimal
                "discount_percent": Decimal
        """
        reasons = []
        decision = "APPROVED"

        # 1. Quantity validation
        if quantity <= 0:
            decision = "BLOCKED"
            reasons.append("Quantity must be greater than zero.")
            return {
                "decision": decision,
                "reasons": reasons,
                "policy_version": policy.policy_version,
                "calculated_margin_percent": Decimal("0"),
                "discount_percent": Decimal("0")
            }

        # 2. Product active check
        if not product.active:
            decision = "BLOCKED"
            reasons.append(f"Product {product.name} is not active.")

        # 3. Product availability (inventory)
        if product.inventory < quantity:
            decision = "BLOCKED"
            reasons.append(
                f"Insufficient inventory. Requested: {quantity}, available: {product.inventory}."
            )

        # 4. Check negative or zero pricing
        if final_amount <= Decimal("0"):
            decision = "BLOCKED"
            reasons.append("Final amount must be greater than zero.")
            return {
                "decision": decision,
                "reasons": reasons,
                "policy_version": policy.policy_version,
                "calculated_margin_percent": Decimal("0"),
                "discount_percent": Decimal("0")
            }

        # 5. Buyer budget check
        if buyer_budget is not None and final_amount > buyer_budget:
            decision = "BLOCKED"
            reasons.append(
                f"Proposed final amount {final_amount} exceeds buyer budget of {buyer_budget}."
            )

        # Calculate original total amount
        original_amount = product.price * Decimal(quantity)
        cost_total = product.cost * Decimal(quantity)

        # 6. Calculate discount
        # discount_percent = ((original_amount - final_amount) / original_amount) * 100
        if original_amount > Decimal("0"):
            discount_amount = original_amount - final_amount
            discount_percent = (discount_amount / original_amount) * Decimal("100")
        else:
            discount_percent = Decimal("0")

        # 7. Calculate margin
        # margin_percent = ((final_amount - cost_total) / final_amount) * 100
        margin_percent = ((final_amount - cost_total) / final_amount) * Decimal("100")

        # 8. Evaluate discount limit
        if discount_percent > policy.max_discount_percent:
            decision = "BLOCKED"
            reasons.append(
                f"Proposed discount of {discount_percent:.2f}% exceeds maximum discount policy of {policy.max_discount_percent}%."
            )

        # 9. Evaluate margin limit
        if margin_percent < policy.min_margin_percent:
            decision = "BLOCKED"
            reasons.append(
                f"Proposed margin of {margin_percent:.2f}% is below minimum required margin of {policy.min_margin_percent}%."
            )

        # 10. Evaluate maximum automatic transaction value and human approval requirements
        if decision != "BLOCKED":
            # If total final amount exceeds the max auto order amount, require approval
            if final_amount > policy.max_auto_order_amount:
                decision = "REQUIRES_APPROVAL"
                reasons.append(
                    f"Proposed final amount {final_amount} exceeds maximum auto transaction limit of {policy.max_auto_order_amount}."
                )
            
            # If total final amount exceeds the require_approval_above limit, require approval
            if final_amount > policy.require_approval_above:
                if decision != "REQUIRES_APPROVAL":
                    decision = "REQUIRES_APPROVAL"
                    reasons.append(
                        f"Proposed final amount {final_amount} exceeds human approval threshold of {policy.require_approval_above}."
                    )

        return {
            "decision": decision,
            "reasons": reasons,
            "policy_version": policy.policy_version,
            "calculated_margin_percent": margin_percent,
            "discount_percent": discount_percent
        }

    @staticmethod
    def evaluate_basket(
        basket: Dict[str, Any],
        policy: MerchantPolicy,
        buyer_budget: Decimal,
        primary_product_id: int,
        db: Any
    ) -> Dict[str, Any]:
        """
        Deterministically evaluates a proposed purchase basket against policy constraints.
        """
        reasons = []
        decision = "APPROVED"

        items = basket.get("items", [])
        if not items:
            return {
                "decision": "BLOCKED",
                "reasons": ["Basket is empty."],
                "calculated_margin_percent": Decimal("0"),
                "discount_percent": Decimal("0")
            }

        # 1. Primary requested product must remain present
        primary_item = next((i for i in items if i.get("is_primary")), None)
        if not primary_item:
            decision = "BLOCKED"
            reasons.append("Primary requested product must remain present in the basket.")
        elif primary_item.get("product_id") != primary_product_id:
            decision = "BLOCKED"
            reasons.append("Primary product ID in basket does not match the requested primary product ID.")

        # Load primary product details from DB
        from backend.app.models import Product
        primary_prod = db.query(Product).filter(Product.id == primary_product_id).first()
        if not primary_prod:
            return {
                "decision": "BLOCKED",
                "reasons": ["Primary product not found in catalog."],
                "calculated_margin_percent": Decimal("0"),
                "discount_percent": Decimal("0")
            }

        # 2. Complementary products must be relevant
        # (Must be in primary product's related_product_ids)
        related_ids = primary_prod.related_product_ids or []
        for item in items:
            if not item.get("is_primary"):
                comp_id = item.get("product_id")
                if comp_id not in related_ids:
                    decision = "BLOCKED"
                    reasons.append(f"Complementary product ID {comp_id} is not relevant or compatible with primary product {primary_prod.name}.")

        # 3. Quantities, active status, availability, and prices checks
        original_total = Decimal("0.00")
        final_total = Decimal("0.00")
        cost_total = Decimal("0.00")

        for item in items:
            item_id = item.get("product_id")
            qty = int(item.get("quantity", 1))
            if qty <= 0:
                decision = "BLOCKED"
                reasons.append("Item quantity must be greater than zero.")
                continue

            prod = db.query(Product).filter(Product.id == item_id).first()
            if not prod:
                decision = "BLOCKED"
                reasons.append(f"Product ID {item_id} not found in catalog.")
                continue

            if not prod.active:
                decision = "BLOCKED"
                reasons.append(f"Product {prod.name} is deactivated.")

            if prod.inventory < qty:
                decision = "BLOCKED"
                reasons.append(f"Insufficient inventory for {prod.name}. Requested: {qty}, available: {prod.inventory}.")

            # original item price snapshot check
            orig_price = Decimal(str(item.get("original_price", str(prod.price))))
            neg_price = Decimal(str(item.get("negotiated_price", "0")))
            
            # check that original_price in basket matches database price
            if abs(orig_price - prod.price) > Decimal("0.01"):
                decision = "BLOCKED"
                reasons.append(f"Original price for {prod.name} in basket does not match catalog price.")

            # check for negative prices
            if neg_price < Decimal("0"):
                decision = "BLOCKED"
                reasons.append(f"Negotiated price for {prod.name} cannot be negative.")

            original_total += orig_price * Decimal(qty)
            final_total += neg_price * Decimal(qty)
            cost_total += prod.cost * Decimal(qty)

            # 4. Merchant minimum selling price checks for each product
            # (Negotiated price must not be below the product's minimum selling price)
            min_sp = prod.min_selling_price or prod.cost
            if neg_price < min_sp:
                decision = "BLOCKED"
                reasons.append(f"Negotiated price for {prod.name} ({neg_price}) is below the minimum allowed selling price ({min_sp}).")

        # 5. Check if total final amount in basket matches the reported final total
        reported_final_total = Decimal(str(basket.get("final_total", str(final_total))))
        if abs(reported_final_total - final_total) > Decimal("0.01"):
            decision = "BLOCKED"
            reasons.append("Basket final total does not match the sum of negotiated item prices.")

        reported_original_total = Decimal(str(basket.get("original_total", str(original_total))))
        if abs(reported_original_total - original_total) > Decimal("0.01"):
            decision = "BLOCKED"
            reasons.append("Basket original total does not match the sum of catalog item prices.")

        # 6. Bundle must respect the maximum buyer budget
        if final_total > buyer_budget:
            decision = "BLOCKED"
            reasons.append(f"Proposed basket total {final_total} exceeds buyer budget limit of {buyer_budget}.")

        # 7. Margin calculations
        if final_total > Decimal("0"):
            margin_percent = ((final_total - cost_total) / final_total) * Decimal("100")
            discount_percent = ((original_total - final_total) / original_total) * Decimal("100") if original_total > Decimal("0") else Decimal("0")
        else:
            margin_percent = Decimal("-100.00")
            discount_percent = Decimal("0")

        # Load active policy if not provided
        if policy is None and db is not None:
            from backend.app.models import MerchantPolicy
            policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()

        min_margin = policy.min_margin_percent if policy else Decimal("15.00")
        max_discount = policy.max_discount_percent if policy else Decimal("15.00")
        max_auto_amount = policy.max_auto_order_amount if policy else Decimal("2000.00")
        require_approval = policy.require_approval_above if policy else Decimal("2000.00")
        policy_version_str = policy.policy_version if policy else "policy_v1.0"

        # Evaluate margin limits on the complete basket
        if margin_percent < min_margin:
            decision = "BLOCKED"
            reasons.append(f"Proposed basket profit margin of {margin_percent:.2f}% is below minimum required margin of {min_margin}%.")

        # Evaluate discount limits on the complete basket
        if discount_percent > max_discount:
            decision = "BLOCKED"
            reasons.append(f"Proposed discount of {discount_percent:.2f}% exceeds maximum discount policy of {max_discount}%.")

        # Evaluate maximum automatic transaction value and human approval requirements
        if decision != "BLOCKED":
            if final_total > max_auto_amount:
                decision = "REQUIRES_APPROVAL"
                reasons.append(f"Proposed basket total {final_total} exceeds maximum auto transaction limit of {max_auto_amount}.")
            if final_total > require_approval:
                if decision != "REQUIRES_APPROVAL":
                    decision = "REQUIRES_APPROVAL"
                    reasons.append(f"Proposed basket total {final_total} exceeds human approval threshold of {require_approval}.")

        return {
            "decision": decision,
            "reasons": reasons,
            "policy_version": policy_version_str,
            "calculated_margin_percent": margin_percent,
            "discount_percent": discount_percent
        }
