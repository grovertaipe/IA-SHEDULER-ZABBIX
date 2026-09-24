/**
 * http.client.js — Reusable HTTP client for the AI Maintenance widget.
 *
 * Responsibilities (Req 22.3):
 *   - Encapsulate all fetch/XHR access to the v2 backend API.
 *   - Attach the active locale to every request (Req 21.3, ties to Req 24.3).
 *   - Provide a bounded timeout per request (AbortController).
 *   - Provide transparent retry with backoff for transient network/timeout errors.
 *
 * This module concentrates the HTTP concern only. It performs NO DOM rendering
 * and NO message formatting — those live in ui.renderer.js and message.formatter.js.
 *
 * Backward compatibility: the v2 backend API contract is preserved. Endpoints used
 * by callers remain /chat, /parse, /create_maintenance, /health,
 * /maintenance/templates, /maintenance/list, /test/routine. The optional `locale`
 * field is added to JSON bodies without altering the existing schema (Req 21.3).
 */
class AIMaintenanceHttpClient {
    /**
     * @param {Object} options
     * @param {string} options.apiUrl            Base URL of the backend (e.g. http://localhost:5005).
     * @param {string} [options.locale]          Active UI locale (e.g. "es", "en").
     * @param {number} [options.timeout=60000]   Per-request timeout in milliseconds.
     * @param {number} [options.maxRetries=2]    Max transparent retries for transient errors.
     */
    constructor(options = {}) {
        this.apiUrl = (options.apiUrl || 'http://localhost:5005').replace(/\/+$/, '');
        this.locale = options.locale || 'es';
        this.timeout = options.timeout || 60000;
        this.maxRetries = options.maxRetries != null ? options.maxRetries : 2;
    }

    setApiUrl(apiUrl) {
        if (apiUrl) {
            this.apiUrl = String(apiUrl).replace(/\/+$/, '');
        }
    }

    setLocale(locale) {
        if (locale) {
            this.locale = locale;
        }
    }

    /**
     * Low-level request with a bounded timeout via AbortController.
     * Does not retry — see requestJson for retrying JSON calls.
     *
     * @param {string} endpoint  Path beginning with "/" (e.g. "/chat").
     * @param {Object} [options] fetch options (method, headers, body, signal...).
     * @returns {Promise<Response>}
     */
    async request(endpoint, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        try {
            const response = await fetch(`${this.apiUrl}${endpoint}`, {
                ...options,
                signal: options.signal || controller.signal
            });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                const timeoutError = new Error('request_timeout');
                timeoutError.code = 'timeout';
                throw timeoutError;
            }
            error.code = error.code || 'network';
            throw error;
        }
    }

    /**
     * Build a JSON POST body, injecting the active locale (Req 21.3).
     * The locale is only added when not already present, so callers may override.
     */
    _withLocale(payload) {
        const data = { ...(payload || {}) };
        if (data.locale === undefined) {
            data.locale = this.locale;
        }
        return data;
    }

    /**
     * Append the active locale to a GET endpoint's query string (Req 21.3).
     * Merges with any existing query params and never overrides a locale the
     * caller already set. Backward compatible: harmless on endpoints that
     * ignore the parameter (e.g. /health, /maintenance/list).
     *
     * @param {string} endpoint  Path, possibly already carrying a query string.
     * @returns {string} endpoint with `locale` ensured in the query string.
     */
    _withLocaleQuery(endpoint) {
        if (!this.locale) {
            return endpoint;
        }
        const [path, existingQuery = ''] = String(endpoint).split('#')[0].split('?');
        const params = new URLSearchParams(existingQuery);
        if (!params.has('locale')) {
            params.set('locale', this.locale);
        }
        const query = params.toString();
        return query ? `${path}?${query}` : path;
    }

    /**
     * GET a JSON resource with timeout. Returns the parsed body.
     * The active locale is appended to the query string (Req 21.3).
     * Throws an Error with `.status` set on non-2xx responses.
     */
    async getJson(endpoint) {
        const response = await this.request(this._withLocaleQuery(endpoint), { method: 'GET' });
        return this._parseJsonResponse(response);
    }

    /**
     * POST a JSON payload (with locale) and return the parsed body.
     * Retries transient network/timeout errors up to maxRetries with backoff.
     *
     * @param {string} endpoint
     * @param {Object} payload            JSON-serializable body.
     * @param {Object} [opts]
     * @param {Function} [opts.onRetry]   Callback(attempt, maxRetries) fired before each retry.
     * @returns {Promise<Object>} parsed JSON body
     */
    async postJson(endpoint, payload, opts = {}) {
        const body = JSON.stringify(this._withLocale(payload));
        let attempt = 0;

        for (;;) {
            try {
                const response = await this.request(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body
                });
                return await this._parseJsonResponse(response);
            } catch (error) {
                const transient = error.code === 'timeout' || error.code === 'network';
                if (transient && attempt < this.maxRetries) {
                    attempt++;
                    if (typeof opts.onRetry === 'function') {
                        opts.onRetry(attempt, this.maxRetries);
                    }
                    await this._delay(this._backoffMs(attempt));
                    continue;
                }
                throw error;
            }
        }
    }

    /**
     * Parse a fetch Response as JSON, mapping non-2xx to an Error carrying the
     * backend message (when present) and the HTTP status.
     */
    async _parseJsonResponse(response) {
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const err = new Error(errorData.message || `server_error_${response.status}`);
            err.status = response.status;
            err.data = errorData;
            err.code = 'http';
            throw err;
        }
        return response.json();
    }

    _backoffMs(attempt) {
        // Simple linear backoff capped at 4s.
        return Math.min(1000 * attempt, 4000);
    }

    _delay(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
}

if (typeof window !== 'undefined') {
    window.AIMaintenanceHttpClient = AIMaintenanceHttpClient;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AIMaintenanceHttpClient;
}
