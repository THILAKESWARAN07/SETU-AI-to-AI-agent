export interface Product {
  id: number;
  name: string;
  category: string;
  description: string | null;
  price: number;
  cost: number;
  inventory: number;
  attributes: Record<string, any>;
  related_product_ids: number[];
  active: boolean;
}

export interface MerchantPolicy {
  id: number;
  max_discount_percent: number;
  min_margin_percent: number;
  max_auto_order_amount: number;
  require_approval_above: number;
  policy_version: string;
  active: boolean;
}

export interface PurchaseRequest {
  id: number;
  buyer_id: string;
  product_id: number;
  quantity: number;
  unit_price: number;
  original_amount: number;
  final_amount: number;
  discount_percent: number;
  currency: string;
  reason: string;
  status: 'PENDING' | 'APPROVED' | 'BLOCKED' | 'REQUIRES_APPROVAL' | 'PAID' | 'FAILED';
  created_at: string;
}

export interface PolicyDecision {
  id: number;
  purchase_request_id: number;
  decision: 'APPROVED' | 'BLOCKED' | 'REQUIRES_APPROVAL';
  reasons: string[];
  policy_version: string;
  calculated_margin_percent: number;
  product_id: number;
  quantity: number;
  unit_price: number;
  original_amount: number;
  final_amount: number;
  discount_percent: number;
  currency: string;
  timestamp: string;
}

export interface Transaction {
  id: number;
  purchase_request_id: number;
  razorpay_order_id: string;
  razorpay_payment_id: string | null;
  razorpay_signature: string | null;
  amount: number;
  currency: string;
  status: 'PENDING' | 'SUCCESS' | 'FAILED';
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: number;
  timestamp: string;
  actor: string;
  action: string;
  result: string;
  reason: string | null;
  entity_type: string | null;
  entity_id: number | null;
  policy_version: string | null;
  metadata: Record<string, any>;
}

export interface DemoCommerceRequest {
  buyer_id: string;
  intent: string;
  budget?: number;
}

export interface DemoCommerceResponse {
  buyer_id: string;
  intent: string;
  catalog_search_results: Record<string, any>[];
  selected_product_id: number;
  cross_sell_product_id: number;
  bundle_offer: Record<string, any>;
  negotiation_history: Record<string, any>[];
  purchase_request_id: number;
  decision: string;
  reasons: string[];
  original_amount: string;
  final_amount: string;
  discount_percent: string;
  margin_percent: string;
  policy_version: string;
}

export interface AttackTestRequest {
  payload: string;
}

export interface AttackTestResponse {
  is_blocked: boolean;
  audit_event_logged: boolean;
  reason: string;
  decision: string | null;
  details: {
    agent_response: string;
    tool_executions: Record<string, any>[];
  };
}

export interface IntentResponse {
  buyer_id: string;
  intent: string;
  agent_response: string;
  suggested_products: Product[];
}

export interface OfferResponse {
  decision: string;
  reasons: string[];
  calculated_margin_percent: number;
  discount_percent: number;
  counter_offer_price: number | null;
  explanation: string;
}

export interface NegotiationOffer {
  purchase_request_id: number | null;
  decision: string;
  reasons: string[];
  discount_percent: string | null;
  margin_percent: string | null;
}

export interface NegotiationResponse {
  buyer_id: string;
  product_id: number;
  agent_response: string;
  offer: NegotiationOffer | null;
}

export interface PolicyEvaluationResult {
  decision: 'APPROVED' | 'BLOCKED' | 'REQUIRES_APPROVAL';
  reasons: string[];
  policy_version: string;
  calculated_margin_percent: string;
  discount_percent: string;
}

