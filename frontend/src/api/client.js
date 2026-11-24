const BASE_URL = import.meta.env.VITE_API_URL && !import.meta.env.PROD
  ? import.meta.env.VITE_API_URL
  : '/v1';

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

let latestCatalogVersion = null;

export function getLatestCatalogVersion() {
  return latestCatalogVersion;
}

export function setLatestCatalogVersion(version) {
  if (version) {
    latestCatalogVersion = String(version).replace(/^"(.*)"$/, '$1');
  }
}

export function getCatalogMutationHeaders() {
  const v = getLatestCatalogVersion();
  if (!v) return {};
  return {
    'If-Match': `"${v}"`,
    'X-Catalog-Version': v,
  };
}

async function request(path, options = {}) {
  const token = getToken();
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  // Update catalogue version marker if returned
  const etag = res.headers.get('ETag') || res.headers.get('etag');
  const xVersion = res.headers.get('X-Catalog-Version') || res.headers.get('x-catalog-version');
  if (etag || xVersion) {
    setLatestCatalogVersion(xVersion || etag);
  }

  if (options.responseType === 'blob') {
    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw { status: res.status, message: errText || 'Request failed', code: res.status === 409 ? 'conflict' : undefined };
    }
    return res.blob();
  }

  if (options.responseType === 'text') {
    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw { status: res.status, message: errText || 'Request failed', code: res.status === 409 ? 'conflict' : undefined };
    }
    return res.text();
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const errorObj = {
      status: res.status,
      message: data.detail || 'Request failed',
      code: res.status === 409 ? 'conflict' : undefined,
      errors: data.errors,
    };
    throw errorObj;
  }
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
export const getLastVerification = (email) =>
  request(`/accounts/last-verification?email=${encodeURIComponent(email)}`).catch(() =>
    request(`/accounts/dev/last-verification?email=${encodeURIComponent(email)}`)
  );
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

export const getRecommendations = (customerId, topN = 5, pk = null, customHeaders = {}) =>
  request(`/recommendations/${customerId}?top_n=${topN}`, {
    headers: {
      'X-API-Key': pk || localStorage.getItem('aipod_pk') || '',
      ...customHeaders,
    },
  });

export const getSimilarProducts = (productId, { topN = 4, sameCategory = true } = {}, pk = null) => {
  const resolvedPk = pk || localStorage.getItem('aipod_pk') || '';
  const params = new URLSearchParams();
  if (topN != null) params.set('top_n', String(topN));
  if (sameCategory !== undefined) params.set('same_category', String(sameCategory));
  return request(`/recommendations/similar/${encodeURIComponent(productId)}?${params.toString()}`, {
    headers: {
      'X-API-Key': resolvedPk,
      'X-AIPOD-Source': 'wizard-test',
    },
  });
};

// Dashboard
export const getDashboardOverview = () => request('/dashboard/overview');
export const getDashboardModels   = () => request('/dashboard/models');
export const getDashboardAnalytics = (days = 7) => request(`/dashboard/analytics?days=${days}`);
export const getDashboardEvents    = (limit = 20) => request(`/dashboard/events?limit=${limit}`);

// Catalogue
export const getCatalogProducts = ({ query = '', category = '', status = '', page = 1, pageSize = 25 } = {}) => {
  const params = new URLSearchParams();
  if (query && query.trim()) params.set('query', query.trim());
  if (category && category.trim()) params.set('category', category.trim());
  if (status && status.trim() && status !== 'all') params.set('status', status.trim());
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  return request(`/catalog/products?${params.toString()}`);
};

export const getCatalogSummary = () => request('/catalog/summary');

export const addCatalogProduct = (productData) =>
  request('/catalog/products', {
    method: 'POST',
    headers: getCatalogMutationHeaders(),
    body: JSON.stringify(productData),
  });

export const patchCatalogProduct = (productId, updateData) =>
  request(`/catalog/products/${encodeURIComponent(productId)}`, {
    method: 'PATCH',
    headers: getCatalogMutationHeaders(),
    body: JSON.stringify(updateData),
  });

export const archiveCatalogProduct = (productId) =>
  request(`/catalog/products/${encodeURIComponent(productId)}`, {
    method: 'DELETE',
    headers: getCatalogMutationHeaders(),
  });

export const permanentDeleteCatalogProduct = (productId) =>
  request(`/catalog/products/${encodeURIComponent(productId)}?permanent=true`, {
    method: 'DELETE',
    headers: getCatalogMutationHeaders(),
  });

export const restoreCatalogProduct = (productId) =>
  request(`/catalog/products/${encodeURIComponent(productId)}/restore`, {
    method: 'POST',
    headers: getCatalogMutationHeaders(),
  });

export const bulkCatalogAction = ({ action, product_ids }) =>
  request('/catalog/bulk', {
    method: 'POST',
    headers: getCatalogMutationHeaders(),
    body: JSON.stringify({ action, product_ids }),
  });

export const downloadCatalogTemplate = (format = 'csv') =>
  request(`/catalog/template?format=${format}`, {
    responseType: 'text',
  });

export const previewCatalogUpload = (formData) =>
  request('/catalog/upload', {
    method: 'POST',
    body: formData,
  });

export const commitCatalogUpload = (uploadId) =>
  request(`/catalog/upload/${encodeURIComponent(uploadId)}/commit`, {
    method: 'POST',
    headers: getCatalogMutationHeaders(),
  });

export const getCatalogHistory = () => request('/catalog/history');

export const undoCatalogCommit = () =>
  request('/catalog/undo', {
    method: 'POST',
    headers: getCatalogMutationHeaders(),
  });

