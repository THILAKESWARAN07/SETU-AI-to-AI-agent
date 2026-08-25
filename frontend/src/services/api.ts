import type {
  Product,
  PolicyDecision,
  Transaction,
  AuditEvent,
  DemoCommerceRequest,
  DemoCommerceResponse,
  AttackTestRequest,
  AttackTestResponse,
  IntentResponse,
  OfferResponse,
  NegotiationResponse,
  PolicyEvaluationResult
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export class ApiError extends Error {
  status?: number;
  statusText?: string;
  detail?: string;

  constructor(message: string, status?: number, statusText?: string, detail?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.statusText = statusText;
    this.detail = detail;
  }
}

async function fetchJson<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  let response: Response;
  
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
    });
  } catch (error: any) {
    throw new ApiError(
      'Network connection failed. Please ensure the backend server is running and accessible.',
      0,
      'Network Error',
      error.message
    );
  }

  if (!response.ok) {
    let detail = '';
    try {
      const errorBody = await response.json();
      detail = errorBody?.detail || '';
    } catch {
      // Response is not JSON
    }

    if (response.status >= 500) {
      throw new ApiError(
        'An internal server error occurred on the trust layer. Please try again later.',
        response.status,
        response.statusText,
        detail
      );
    } else if (response.status === 404) {
      throw new ApiError(
        'The requested API endpoint was not found.',
        response.status,
        response.statusText,
        detail
      );
    } else {
      // 400, 403, 422, etc.
      throw new ApiError(
        detail || `Request failed with status code ${response.status}.`,
        response.status,
        response.statusText,
        detail
      );
    }
  }

  try {
    return await response.json() as T;
  } catch (error: any) {
    throw new ApiError(
      'Invalid JSON response received from the backend.',
      response.status,
      response.statusText,
      error.message
    );
  }
}

export const apiService = {
  // --- CATALOG ENDPOINTS ---
  async getCatalog(category?: string): Promise<Product[]> {
    const query = category ? `?category=${encodeURIComponent(category)}` : '';
    return fetchJson<Product[]>(`/api/catalog${query}`);
  },

  async getProduct(productId: number): Promise<Product> {
    return fetchJson<Product>(`/api/catalog/${productId}`);
  },

  // --- AGENT & NEGOTIATION ENDPOINTS ---
  async routeBuyerIntent(buyerId: string, intent: string): Promise<IntentResponse> {
    return fetchJson<IntentResponse>('/api/buyer/intent', {
      method: 'POST',
      body: JSON.stringify({ buyer_id: buyerId, intent }),
    });
  },

  async evaluateMerchantOffer(productId: number, quantity: number, proposedPrice: number): Promise<OfferResponse> {
    return fetchJson<OfferResponse>('/api/merchant/offer', {
      method: 'POST',
      body: JSON.stringify({
        product_id: productId,
        quantity,
        proposed_price: proposedPrice
      }),
    });
  },

  async runNegotiationTurn(buyerId: string, productId: number, quantity: number, message: string): Promise<NegotiationResponse> {
    return fetchJson<NegotiationResponse>('/api/negotiation', {
      method: 'POST',
      body: JSON.stringify({
        buyer_id: buyerId,
        product_id: productId,
        quantity,
        message
      }),
    });
  },

  // --- PURCHASE REQUEST ENDPOINTS ---
  async createPurchaseRequest(data: {
    buyer_id: string;
    product_id: number;
    quantity: number;
    unit_price: string;
    original_amount: string;
    final_amount: string;
    discount_percent: string;
    currency: string;
    reason: string;
  }): Promise<PolicyDecision> {
    return fetchJson<PolicyDecision>('/api/purchase/request', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async evaluatePolicy(productId: number, quantity: number, proposedPrice: number, buyerBudget?: number): Promise<PolicyEvaluationResult> {
    const budgetParam = buyerBudget !== undefined ? `&buyer_budget=${buyerBudget}` : '';
    return fetchJson<PolicyEvaluationResult>(`/api/policy/evaluate?product_id=${productId}&quantity=${quantity}&proposed_price=${proposedPrice}${budgetParam}`, {
      method: 'POST',
    });
  },

  // --- ADMIN OVERRIDE ---
  async adminApproveRequest(purchaseRequestId: number): Promise<PolicyDecision> {
    return fetchJson<PolicyDecision>(`/api/admin/approve/${purchaseRequestId}`, {
      method: 'POST',
    });
  },

  // --- PAYMENT ENDPOINTS ---
  async createPayment(purchaseRequestId: number): Promise<Transaction> {
    return fetchJson<Transaction>(`/api/payment/create?purchase_request_id=${purchaseRequestId}`, {
      method: 'POST',
    });
  },

  // --- AUDIT & UTILITY ENDPOINTS ---
  async getAuditTrail(): Promise<AuditEvent[]> {
    return fetchJson<AuditEvent[]>('/api/audit');
  },

  async getTransactions(): Promise<Transaction[]> {
    return fetchJson<Transaction[]>('/api/transactions');
  },

  // --- E2E DEMO ORCHESTRATION ---
  async runDemoCommerceFlow(request: DemoCommerceRequest): Promise<DemoCommerceResponse> {
    return fetchJson<DemoCommerceResponse>('/api/demo/commerce', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  // --- ATTACK TEST SIMULATOR ---
  async simulateAttack(request: AttackTestRequest): Promise<AttackTestResponse> {
    return fetchJson<AttackTestResponse>('/api/attack-test', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }
};
