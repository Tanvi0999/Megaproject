// Shared API client for React components and the original pages.
// Set VITE_API_BASE_URL in .env if the backend is not at localhost:8000.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export async function apiRequest(path, { method = 'GET', body, token, headers = {} } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = data?.detail || `API request failed (${response.status})`;
    throw new Error(message);
  }
  return data;
}

// These methods correspond to routes currently present in backend/app/main.py.
export const studentApi = {
  create: (profile, token) => apiRequest('/api/students', { method: 'POST', body: profile, token }),
  list: (token) => apiRequest('/api/students', { token }),
  get: (studentId, token) => apiRequest(`/api/students/${studentId}`, { token }),
  recommendations: (studentId, token) => apiRequest(`/api/students/${studentId}/recommendations`, { token }),
  skillGap: (studentId, token) => apiRequest(`/api/students/${studentId}/skill-gap`, { token }),
};

// Expose the same API helper to legacy page scripts without changing their UI.
if (typeof window !== 'undefined') window.StudentPathAPI = { API_BASE_URL, apiRequest, studentApi };
