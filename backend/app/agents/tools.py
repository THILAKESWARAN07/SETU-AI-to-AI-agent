import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple, Callable
from sqlalchemy.orm import Session

from backend.app.models import Product, MerchantPolicy, PurchaseRequest, PolicyDecision
from backend.app.policy import PolicyEngine
from backend.app.audit import AuditEngine

logger = logging.getLogger("setu.agents.tools")

# --- CUSTOM SECURITY EXCEPTION ---

class SecurityError(Exception):
    pass


# --- TOOL REGISTRY ---

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Tuple[Callable, Dict[str, Any]]] = {}

    def register_tool(self, name: str, func: Callable, schema: Dict[str, Any]):
        """
        Registers a tool function with its JSON schema description.
        """
        # Critical security check: prevent registering any payment-related keywords
        payment_keywords = ["payment", "razorpay", "capture", "refund", "credit", "card", "bank"]
        for keyword in payment_keywords:
            if keyword in name.lower() or keyword in schema.get("description", "").lower():
                raise SecurityError(f"Security Block: Tool registration rejected due to unsafe keyword '{keyword}' in tool '{name}'")
        
        self.tools[name] = (func, schema)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [schema for _, schema in self.tools.values()]

    def execute_tool(self, name: str, db: Session, **kwargs) -> Any:
        if name not in self.tools:
            raise ValueError(f"Tool {name} not found in registry.")
        func, _ = self.tools[name]
        return func(db, **kwargs)


# --- CONCRETE AGENT TOOLS ---

def search_catalog_tool(db: Session, query: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search catalog items matching category or query keywords.
    """
    db_query = db.query(Product).filter(Product.active == True)
    if category:
        db_query = db_query.filter(Product.category.ilike(category))
    products = db_query.all()
    
    if query:
        query_lower = query.lower()
        products = [p for p in products if query_lower in p.name.lower() or query_lower in (p.description or "").lower()]
        
    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "price": str(p.price),
            "inventory": p.inventory,
            "description": p.description
        }
        for p in products
    ]

search_catalog_schema = {
    "name": "search_catalog",
    "description": "Searches for products in the merchant catalog, optionally filtered by category or search query string.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword or text query"},
            "category": {"type": "string", "description": "Product category filter (e.g. Electronics, Accessories)"}
        }
    }
}


def view_product_tool(db: Session, product_id: int) -> Dict[str, Any]:
    """
    Retrieve details for a single product.
    """
    p = db.query(Product).filter(Product.id == product_id, Product.active == True).first()
    if not p:
        return {"error": f"Product with ID {product_id} not found or deactivated."}
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "description": p.description,
        "price": str(p.price),
        "inventory": p.inventory,
        "attributes": p.attributes,
        "related_product_ids": p.related_product_ids
    }

view_product_schema = {
    "name": "view_product",
    "description": "Retrieves detailed information about a specific product in the catalog by its ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The unique ID of the product"}
        },
        "required": ["product_id"]
    }
}


def compare_products_tool(db: Session, product_ids: List[int]) -> List[Dict[str, Any]]:
    """
    Compare multiple products side by side.
    """
    products = db.query(Product).filter(Product.id.in_(product_ids), Product.active == True).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "price": str(p.price),
            "inventory": p.inventory,
            "description": p.description,
            "attributes": p.attributes
        }
        for p in products
    ]

compare_products_schema = {
    "name": "compare_products",
    "description": "Compares features, pricing, and inventory of multiple products side by side.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of product IDs to compare"
            }
        },
        "required": ["product_ids"]
    }
}


def identify_related_product_tool(db: Session, product_id: int) -> Dict[str, Any]:
    """
    Identify product accessories or related products.
    """
    p = db.query(Product).filter(Product.id == product_id, Product.active == True).first()
    if not p:
        return {"error": f"Product with ID {product_id} not found."}
    
    related_ids = p.related_product_ids or []
    related_products = db.query(Product).filter(Product.id.in_(related_ids), Product.active == True).all()
    
    return {
        "product_id": product_id,
        "related_products": [
            {
                "id": rp.id,
                "name": rp.name,
                "category": rp.category,
                "price": str(rp.price)
            }
            for rp in related_products
        ]
    }

identify_related_product_schema = {
    "name": "identify_related_product",
    "description": "Identifies cross-sell opportunities or accessories related to a product.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The ID of the reference product"}
        },
        "required": ["product_id"]
    }
}


def propose_cross_sell_tool(db: Session, product_id: int) -> Dict[str, Any]:
    """
    Recommend a related product as a cross-sell.
    """
    related_res = identify_related_product_tool(db, product_id)
    if "error" in related_res:
        return related_res
        
    related = related_res["related_products"]
    if not related:
        return {"message": "No specific cross-sell recommendation available for this product."}
        
    # Suggest the first related product
    suggested = related[0]
    return {
        "original_product_id": product_id,
        "cross_sell_product": suggested,
        "reason": f"Customer buying product {product_id} might be interested in related product {suggested['name']} (ID {suggested['id']})"
    }

propose_cross_sell_schema = {
    "name": "propose_cross_sell",
    "description": "Formulates a cross-sell recommendation for a given product based on relations.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The product ID for which to propose a cross-sell"}
        },
        "required": ["product_id"]
    }
}


def create_bundle_offer_tool(db: Session, product_ids: List[int], discount_percent: Optional[str] = "5.0") -> Dict[str, Any]:
    """
    Create a proposed bundle offer of multiple products with an optional discount.
    """
    products = db.query(Product).filter(Product.id.in_(product_ids), Product.active == True).all()
    if not products:
        return {"error": "No valid products found for bundle."}
        
    discount = Decimal(discount_percent)
    original_total = sum(p.price for p in products)
    discount_amount = original_total * (discount / Decimal("100"))
    offered_price = (original_total - discount_amount).quantize(Decimal("0.01"))
    
    return {
        "product_ids": [p.id for p in products],
        "original_amount": str(original_total),
        "offered_amount": str(offered_price),
        "discount_percent": str(discount),
        "reason": f"Combined bundle of {[p.name for p in products]} at {discount_percent}% discount."
    }

create_bundle_offer_schema = {
    "name": "create_bundle_offer",
    "description": "Creates a discount bundle proposal containing multiple products.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of product IDs to bundle together"
            },
            "discount_percent": {
                "type": "string",
                "description": "Proposed percentage discount for bundle as decimal string (default: 5.0)"
            }
        },
        "required": ["product_ids"]
    }
}


def request_purchase_tool(
    db: Session,
    buyer_id: str,
    product_id: int,
    quantity: int,
    proposed_price: str,
    reason: str
) -> Dict[str, Any]:
    """
    Submits a purchase request to the database and evaluates it via the backend policy engine.
    """
    proposed_final_amount = Decimal(proposed_price)
    
    # 1. Fetch Product
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return {"status": "error", "message": "Product not found"}

    # 2. Fetch Active Policy
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    if not policy:
        return {"status": "error", "message": "Merchant policy not configured"}

    # 3. Create Snapshots
    unit_price = product.price
    original_amount = unit_price * Decimal(quantity)
    
    if original_amount > Decimal("0"):
        discount_amount = original_amount - proposed_final_amount
        discount_percent = (discount_amount / original_amount) * Decimal("100")
    else:
        discount_percent = Decimal("0")

    # Create purchase request in database in PENDING status
    req = PurchaseRequest(
        buyer_id=buyer_id,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
        original_amount=original_amount,
        final_amount=proposed_final_amount,
        discount_percent=discount_percent,
        currency="INR",
        reason=reason,
        status="PENDING"
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # 4. Evaluate Policy
    decision_dict = PolicyEngine.evaluate(product, policy, quantity, proposed_final_amount)
    decision_status = decision_dict["decision"]  # APPROVED, BLOCKED, REQUIRES_APPROVAL

    # Update request status to match canonical policy decision status
    req.status = decision_status
    db.commit()

    # 5. Create associated PolicyDecision record with full snapshot parameters
    decision = PolicyDecision(
        purchase_request_id=req.id,
        decision=decision_status,
        reasons=decision_dict["reasons"],
        policy_version=decision_dict["policy_version"],
        calculated_margin_percent=decision_dict["calculated_margin_percent"],
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
        original_amount=original_amount,
        final_amount=proposed_final_amount,
        discount_percent=discount_percent,
        currency="INR"
    )
    db.add(decision)
    db.commit()

    # 6. Log to Audit Engine
    AuditEngine.log_event(
        db=db,
        actor="SYSTEM",
        action="EVALUATE_POLICY",
        result=decision_status,
        reason=", ".join(decision_dict["reasons"]) or "Passed all checks",
        entity_type="PurchaseRequest",
        entity_id=req.id,
        policy_version=policy.policy_version,
        metadata={
            "quantity": quantity,
            "unit_price": str(unit_price),
            "original_amount": str(original_amount),
            "final_amount": str(proposed_final_amount),
            "discount_percent": str(discount_percent),
            "margin_percent": str(decision_dict["calculated_margin_percent"])
        }
    )

    return {
        "purchase_request_id": req.id,
        "decision": decision_status,
        "reasons": decision_dict["reasons"],
        "discount_percent": str(discount_percent),
        "margin_percent": str(decision_dict["calculated_margin_percent"])
    }

request_purchase_schema = {
    "name": "request_purchase",
    "description": "Submits a purchase offer for evaluation by the backend policy engine. This does NOT finalize the transaction.",
    "parameters": {
        "type": "object",
        "properties": {
            "buyer_id": {"type": "string", "description": "The unique identifier of the buying agent"},
            "product_id": {"type": "integer", "description": "The product being purchased"},
            "quantity": {"type": "integer", "description": "The number of units requested"},
            "proposed_price": {"type": "string", "description": "The proposed final total price formatted as a string decimal"},
            "reason": {"type": "string", "description": "The reason or justification for the price offer"}
        },
        "required": ["buyer_id", "product_id", "quantity", "proposed_price", "reason"]
    }
}


def get_policy_constraints_tool(db: Session) -> Dict[str, Any]:
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    if not policy:
        return {"error": "No active policy configuration found."}
    return {
        "max_discount_percent": str(policy.max_discount_percent),
        "max_auto_order_amount": str(policy.max_auto_order_amount),
        "require_approval_above": str(policy.require_approval_above),
        "policy_version": policy.policy_version
    }

get_policy_constraints_schema = {
    "name": "get_policy_constraints",
    "description": "Retrieves active merchant policy thresholds (discount caps and approval ceilings) governing orders.",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}

get_product_details_schema = {
    "name": "get_product_details",
    "description": "Retrieves detailed information about a specific product in the catalog by its ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The unique product key"}
        },
        "required": ["product_id"]
    }
}


def evaluate_budget_tool(db: Session, proposed_price: Optional[str] = None, budget: Optional[str] = None) -> Dict[str, Any]:
    if not proposed_price or not budget:
        return {"error": "Missing required arguments: both 'proposed_price' and 'budget' must be provided."}
    try:
        p_price = Decimal(proposed_price)
        p_budget = Decimal(budget)
    except Exception as e:
        return {"error": f"Invalid format for proposed_price or budget: {e}"}
    allowed = p_price <= p_budget
    return {
        "proposed_price": str(p_price),
        "budget": str(p_budget),
        "within_budget": allowed,
        "amount_over_budget": str(p_price - p_budget) if not allowed else "0.00"
    }

evaluate_budget_schema = {
    "name": "evaluate_budget",
    "description": "Compares proposed price quote against maximum procurement budget boundary.",
    "parameters": {
        "type": "object",
        "properties": {
            "proposed_price": {"type": "string", "description": "Decimal string representing the offered deal amount"},
            "budget": {"type": "string", "description": "Decimal string representing the maximum allowed budget limit"}
        },
        "required": ["proposed_price", "budget"]
    }
}


def get_inventory_tool(db: Session, product_id: int) -> Dict[str, Any]:
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        return {"error": f"Product with ID {product_id} not found."}
    return {
        "product_id": product_id,
        "name": p.name,
        "inventory": p.inventory,
        "in_stock": p.inventory > 0
    }

get_inventory_schema = {
    "name": "get_inventory",
    "description": "Checks available warehouse stock quantity for a single catalog item.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The unique product key"}
        },
        "required": ["product_id"]
    }
}


def get_product_price_tool(db: Session, product_id: int) -> Dict[str, Any]:
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        return {"error": f"Product with ID {product_id} not found."}
    return {
        "product_id": product_id,
        "name": p.name,
        "price": str(p.price)
    }

get_product_price_schema = {
    "name": "get_product_price",
    "description": "Retrieves base price quote for a single catalog item.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The unique product key"}
        },
        "required": ["product_id"]
    }
}


def get_merchant_constraints_tool(db: Session) -> Dict[str, Any]:
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    if not policy:
        return {"error": "No active policy configuration found."}
    return {
        "min_margin_percent": str(policy.min_margin_percent),
        "max_discount_percent": str(policy.max_discount_percent),
        "policy_version": policy.policy_version
    }

get_merchant_constraints_schema = {
    "name": "get_merchant_constraints",
    "description": "Retrieves vendor guidelines (minimum profit margin and discount bounds) required for deal approval.",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}


def evaluate_margin_tool(db: Session, product_id: Optional[int] = None, quantity: Optional[int] = None, proposed_price: Optional[str] = None) -> Dict[str, Any]:
    if product_id is None or quantity is None or not proposed_price:
        return {"error": "Missing required arguments: 'product_id', 'quantity', and 'proposed_price' must all be provided."}
    try:
        pid = int(product_id)
        qty = int(quantity)
        final_price = Decimal(proposed_price)
    except Exception as e:
        return {"error": f"Invalid format for product_id, quantity, or proposed_price: {e}"}

    p = db.query(Product).filter(Product.id == pid).first()
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    if not p or not policy:
        return {"error": "Product or active policy config missing."}
    
    cost = p.cost * Decimal(qty)
    margin_amount = final_price - cost
    
    if final_price > Decimal("0"):
        margin_percent = (margin_amount / final_price) * Decimal("100")
    else:
        margin_percent = Decimal("-100.00")
        
    allowed = margin_percent >= policy.min_margin_percent
    return {
        "product_id": product_id,
        "quantity": quantity,
        "cost_total": str(cost),
        "proposed_price": str(final_price),
        "calculated_margin_percent": str(margin_percent.quantize(Decimal("0.01"))),
        "minimum_margin_percent": str(policy.min_margin_percent),
        "margin_passed": allowed
    }

evaluate_margin_schema = {
    "name": "evaluate_margin",
    "description": "Verifies if the proposed transaction price complies with the merchant's required minimum profit margin guidelines.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "Product ID being sold"},
            "quantity": {"type": "integer", "description": "Units count"},
            "proposed_price": {"type": "string", "description": "Offered deal total amount decimal string"}
        },
        "required": ["product_id", "quantity", "proposed_price"]
    }
}
