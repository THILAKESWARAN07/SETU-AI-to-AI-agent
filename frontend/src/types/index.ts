export interface Product {
  id: number;
  name: string;
  category: string;
  description: string | null;
  price: number;
  cost: number;
  min_selling_price?: number;
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
  currency?: string;
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

export interface NegotiationHistoryItem {
  round: number;
  buyer_offer?: {
    product_id: number;
    quantity: number;
    original_amount: string;
    final_amount: string;
    currency: string;
    reason: string;
    message?: string;
    reason_label?: string;
    tools_used?: string[];
    confidence?: number;
    basket_items?: any[];
  } | null;
  merchant_offer?: {
    product_ids: number[];
    original_amount: string;
    offered_amount: string;
    discount_percent: string;
    reason: string;
    message?: string;
    reason_label?: string;
    tools_used?: string[];
    confidence?: number;
    basket_items?: any[];
  } | null;
  accepted: boolean;
  reason: string;
}

export interface ConversationEvent {
  id?: string;
  event_id?: string;
  sequence?: number;
  round: number;
  actor: 'buyer' | 'merchant' | 'setu';
  event_type?: 'message' | 'counter_offer' | 'bundle_offer' | 'acceptance' | 'trust_check' | 'rejection' | string;
  type?: 'buyer_message' | 'merchant_message' | 'system_event' | 'complete' | 'error' | string;
  state?: string;
  proposal_id?: string;
  proposal_type?: string;
  accepted_proposal_id?: string;
  message: string;
  offer?: string | number;
  standalone_counter?: string | number;
  bundle_proposal?: any;
  optional_bundle_items?: any[];
  basket_items?: any[];
  strategy?: string;
  reason_label?: string;
  timestamp?: string;
  is_final?: boolean;
}

export interface DemoCommerceResponse {
  buyer_id: string;
  intent: string;
  catalog_search_results: Record<string, any>[];
  selected_product_id: number;
  cross_sell_product_id: number;
  bundle_offer: Record<string, any>;
  negotiation_history: NegotiationHistoryItem[];
  conversation_events?: ConversationEvent[];
  purchase_request_id: number;
  decision: string;
  reasons: string[];
  original_amount: string;
  final_amount: string;
  discount_percent: string;
  margin_percent: string;
  policy_version: string;
  basket?: any;
  
  // Proposal and Offer Lifecycle
  buyer_opening_offer?: any;
  merchant_standalone_counter?: any;
  merchant_bundle_proposal?: any;
  proposals?: any[];
  accepted_proposal_id?: string;
  
  // Step 10 dynamic params
  agent_mode?: string;
  buyer_objective?: string;
  buyer_tools_used?: string[];
  buyer_confidence?: number;
  merchant_objective?: string;
  merchant_tools_used?: string[];
  merchant_confidence?: number;
  
  // Step 12 metadata
  provider?: string;
  model?: string;
  execution_mode?: string;
  session_id?: string;
  start_time?: string;
  completion_time?: string;
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

export interface SecurityGate {
  id: string;
  name: string;
  description: string;
  status: 'PASSED' | 'CONFIGURED' | 'FAILED' | 'UNAVAILABLE';
  evidence: string;
  iconName: string;
}

export type OrderStatus = 
  | 'CREATED' 
  | 'PAYMENT_PENDING' 
  | 'PAID' 
  | 'PROCESSING' 
  | 'SHIPPED' 
  | 'DELIVERED' 
  | 'FAILED' 
  | 'CANCELLED';

export interface OrderItem {
  productId: number;
  name: string;
  quantity: number;
  unitPrice: number;
  originalAmount: number;
  finalAmount: number;
  merchantName: string;
}

export interface FulfillmentEvent {
  id: string;
  status: OrderStatus;
  timestamp: string;
  description: string;
  completed: boolean;
}

export interface Order {
  id: number;
  transactionId: number;
  purchaseRequestId: number;
  razorpayOrderId: string | null;
  razorpayPaymentId: string | null;
  amount: number;
  currency: string;
  status: OrderStatus;
  paymentStatus: 'PENDING' | 'SUCCESS' | 'FAILED';
  createdAt: string;
  updatedAt: string;
  items: OrderItem[];
  merchantName: string;
  fulfillmentStatus: OrderStatus;
  timeline: FulfillmentEvent[];
}
