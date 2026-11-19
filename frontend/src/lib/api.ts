export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

let refreshInFlight: Promise<boolean> | null = null;

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

function csrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const cookie = document.cookie
    .split('; ')
    .find(value => value.startsWith('knowra_csrf='));
  return cookie ? decodeURIComponent(cookie.slice('knowra_csrf='.length)) : null;
}

async function refreshAfterCheckingSession(): Promise<boolean> {
  const current = await fetch(`${API_URL}/api/v1/auth/me`, {
    credentials: 'include',
  }).catch(() => null);
  if (current?.ok) return true;
  const csrf = csrfToken();
  return fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: csrf ? { 'X-CSRF-Token': csrf } : undefined,
  })
    .then(response => response.ok)
    .catch(() => false);
}

async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    const refresh = () => refreshAfterCheckingSession();
    const operation = typeof navigator !== 'undefined' && navigator.locks
      ? navigator.locks.request('knowra-auth-refresh', refresh) as unknown as Promise<boolean>
      : refresh();
    const task = operation.finally(() => {
      refreshInFlight = null;
    });
    refreshInFlight = task;
    return task;
  }
  return refreshInFlight;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;
  const request = () => {
    const csrf = csrfToken();
    return fetch(`${API_URL}/api/v1${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        ...(init?.body && !isFormData ? { 'Content-Type': 'application/json' } : {}),
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        ...init?.headers,
      },
    });
  };
  let response = await request();
  const canRefresh = !['/auth/login', '/auth/register', '/auth/refresh'].includes(path);
  if (response.status === 401 && canRefresh && await refreshSession()) {
    response = await request();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string'
      ? body.detail
      : Array.isArray(body.detail)
        ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(', ')
        : 'Request failed';
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export interface CurrentUser {
  id: string;
  email: string;
  workspace_id: string;
  role: 'owner' | 'administrator' | 'member' | 'viewer';
}

export interface ModelProvider {
  id: string;
  name: string;
  provider_type: 'ollama' | 'lm_studio' | 'google_gemini' | 'openai_compatible';
  base_url: string;
  has_api_key: boolean;
  api_key_version: string | null;
  models: string[];
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type WorkspaceRole = 'owner' | 'administrator' | 'member' | 'viewer';

export interface WorkspaceMember {
  id: string;
  user_id: string;
  email: string;
  role: WorkspaceRole;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  details: Record<string, unknown>;
  created_at: string;
}
