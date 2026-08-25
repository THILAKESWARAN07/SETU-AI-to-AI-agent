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
