// Copyright (C) 2026 David L F Gaden
// HTTP client for the loopback Studio server. Every fault becomes an ApiError
// carrying the server's structured fault (code, message, location, recovery).

export class ApiError extends Error {
  constructor(fault) {
    super(fault.message || fault.code || 'The server rejected the request.');
    this.code = fault.code || 'API_ERROR';
    this.fault = fault;
  }
}

function readToken() {
  if (typeof location === 'undefined') {
    return '';
  }
  const fromUrl = new URL(location.href).searchParams.get('token');
  if (fromUrl) {
    try {
      sessionStorage.setItem('schemaxis.token', fromUrl);
    } catch {
      // Storage may be unavailable; the URL token still works for this page.
    }
    return fromUrl;
  }
  try {
    return sessionStorage.getItem('schemaxis.token') || '';
  } catch {
    return '';
  }
}

export class Api {
  constructor(token = readToken()) {
    this.token = token;
  }

  async request(path, body, {timeout = 30000} = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = {'X-Schemaxis-Token': this.token};
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    try {
      const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        credentials: 'same-origin',
        referrerPolicy: 'no-referrer',
        signal: controller.signal,
      });
      let data;
      try {
        data = await response.json();
      } catch {
        throw new ApiError({code: 'INVALID_RESPONSE', message: `HTTP ${response.status}: expected JSON`});
      }
      if (data && data.fault) {
        throw new ApiError(data.fault);
      }
      if (!response.ok) {
        throw new ApiError({code: 'HTTP_ERROR', message: `HTTP ${response.status}`});
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') {
        throw new ApiError({
          code: 'TIMEOUT',
          message: 'The server did not respond in time. The request may still complete; refresh before retrying.',
        });
      }
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError({code: 'NETWORK_ERROR', message: 'The Studio server is not reachable. Is it still running?'});
    } finally {
      clearTimeout(timer);
    }
  }

  get(path, params) {
    const url = new URL(path, typeof location === 'undefined' ? 'http://localhost' : location.origin);
    for (const [key, value] of Object.entries(params || {})) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, value);
      }
    }
    return this.request(url.pathname + url.search);
  }

  post(path, body) {
    return this.request(path, body || {});
  }

  /** URL for binary resources (images) that cannot carry the header. */
  url(path, params) {
    const url = new URL(path, location.origin);
    url.searchParams.set('token', this.token);
    for (const [key, value] of Object.entries(params || {})) {
      url.searchParams.set(key, value);
    }
    return url.href;
  }

  /** Poll a job until it finishes. onUpdate receives each snapshot. */
  async waitForJob(job, {onUpdate, interval = 600, signal} = {}) {
    for (;;) {
      if (signal && signal.aborted) {
        throw new ApiError({code: 'CANCELLED', message: 'Stopped waiting for the job.'});
      }
      const snapshot = await this.get(`/api/jobs/${encodeURIComponent(job)}`);
      if (onUpdate) {
        onUpdate(snapshot);
      }
      if (snapshot.status !== 'running') {
        if (snapshot.status === 'failed') {
          throw new ApiError(snapshot.fault || {code: 'JOB_FAILED', message: 'The job failed.'});
        }
        return snapshot;
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }
}

export const api = new Api();
