const BASE_URL = import.meta.env.VITE_API_URL || '/v1';

export function getSessionToken() {
  return localStorage.getItem('aipod_token');
}

export function clearSessionToken() {
  localStorage.removeItem('aipod_token');
}

export function getStoredKeys() {
  return {
    publicKey: localStorage.getItem('aipod_pk'),
    privateKey: localStorage.getItem('aipod_sk'),
  };
}

export function clearAllTokens() {
  localStorage.removeItem('aipod_token');
  localStorage.removeItem('aipod_pk');
  localStorage.removeItem('aipod_sk');
}

function getToken() {
  return getSessionToken();
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };
  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, message: data.detail || 'Request failed' };
  return data;
}

// Auth
export const signup = (body) => request('/accounts/signup', { method: 'POST', body: JSON.stringify(body) });
export const login  = (body) => request('/accounts/login',  { method: 'POST', body: JSON.stringify(body) });
export const loginMfa = (body) => request('/accounts/login/mfa', { method: 'POST', body: JSON.stringify(body) });
export const verifyEmail = ({ email, code }) =>
  request('/accounts/verify-email', { method: 'POST', body: JSON.stringify({ email, code }) });
export const resendVerification = ({ email }) =>
  request('/accounts/resend-verification', { method: 'POST', body: JSON.stringify({ email }) });
export const getMe = (explicitToken) => {
  const token = explicitToken || getToken();
  return request('/accounts/me', token ? { headers: { Authorization: `Bearer ${token}` } } : {});
};
export const regenerateKeys = () => request('/accounts/keys/regenerate', { method: 'POST' });

// MFA
export const mfaSetup   = () => request('/accounts/mfa/setup',   { method: 'POST' });
export const mfaEnable  = (body) => request('/accounts/mfa/enable',  { method: 'POST', body: JSON.stringify(body) });
export const mfaDisable = (body) => request('/accounts/mfa/disable', { method: 'POST', body: JSON.stringify(body) });

// Onboarding
export const onboardUpload = (formData) =>
  fetch(`${BASE_URL}/onboard/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: formData,
  }).then(r => r.json());

export const onboardValidate = (body) => request('/onboard/validate', { method: 'POST', body: JSON.stringify(body) });
export const onboardConfirm  = (body) => request('/onboard/confirm',  { method: 'POST', body: JSON.stringify(body) });
export const onboardTrain    = ()     => request('/onboard/train',    { method: 'POST' });
export const onboardStatus   = ()     => request('/onboard/status');

// Recommendations
export const getSampleCustomers = (limit = 10, pk = null) =>
  request(`/recommendations/sample-customers?limit=${limit}`, {
    headers: { 'X-API-Key': pk || localStorage.getItem('aipod_pk') || '' },
  });

export const getRecommendations = (customerId, topN = 5, pk = null) =>
  request(`/recommendations/${customerId}?top_n=${topN}`, {
    headers: { 'X-API-Key': pk || localStorage.getItem('aipod_pk') || '' },
  });

