/**
 * ui.renderer.js — UI rendering, DOM, ARIA, focus and theme concerns.
 *
 * Responsibilities (Req 22.1, 23, 24, 25):
 *   - Own all DOM reads/writes for the chat surface.
 *   - Apply WCAG 2.1 AA affordances: ARIA roles/labels, an aria-live messages
 *     region, keyboard operability (Tab/Enter/Escape) and a visible focus ring.
 *   - Render the processing/typing indicator while awaiting the backend (Req 24.1).
 *   - Render a visible manual retry action after a backend failure (Req 24.3).
 *   - Reflect the active Zabbix theme (light/dark) on the widget root (Req 25).
 *
 * This module does NOT talk to the backend (http.client.js) and does NOT format
 * message bodies (message.formatter.js). It receives a formatter for escaping/HTML
 * and a translate function `t` for ARIA labels (Zabbix JS i18n, Req 33.2).
 */
class AIMaintenanceUIRenderer {
    /**
     * @param {HTMLElement} root       Widget body element (this._body).
     * @param {Object} deps
     * @param {Object} deps.formatter  AIMaintenanceMessageFormatter instance.
     * @param {Function} [deps.t]      Translation function t(key) -> string.
     */
    constructor(root, deps = {}) {
        this.root = root;
        this.formatter = deps.formatter;
        this.t = typeof deps.t === 'function' ? deps.t : (s) => s;
        this._typingEl = null;
    }

    $(selector) {
        return this.root ? this.root.querySelector(selector) : null;
    }

    /**
     * Apply accessibility attributes and theme to the static markup rendered by
     * widget.view.php. Called once after the widget content is set.
     */
    enhanceAccessibility() {
        const messages = this.$('#ai-messages');
        if (messages) {
            // Messages region announces new content to assistive tech (Req 23.1).
            messages.setAttribute('role', 'log');
            messages.setAttribute('aria-live', 'polite');
            messages.setAttribute('aria-atomic', 'false');
            messages.setAttribute('aria-relevant', 'additions text');
            messages.setAttribute('aria-label', this.t('Conversation history'));
            messages.setAttribute('tabindex', '0');
        }

        const input = this.$('#ai-input');
        if (input) {
            input.setAttribute('aria-label', this.t('Message to the assistant'));
            input.setAttribute('role', 'textbox');
            input.setAttribute('aria-multiline', 'true');
        }

        const sendBtn = this.$('#ai-send-btn');
        if (sendBtn) {
            sendBtn.setAttribute('aria-label', this.t('Send message'));
            sendBtn.setAttribute('type', 'button');
        }

        const templatesBtn = this.$('#templates-btn');
        if (templatesBtn) {
            templatesBtn.setAttribute('aria-label', this.t('View routine maintenance templates'));
            templatesBtn.setAttribute('type', 'button');
        }

        const confirmation = this.$('#ai-confirmation');
        if (confirmation) {
            confirmation.setAttribute('role', 'dialog');
            confirmation.setAttribute('aria-modal', 'true');
            confirmation.setAttribute('aria-label', this.t('Confirm maintenance'));
        }

        const loading = this.$('#ai-loading');
        if (loading) {
            loading.setAttribute('role', 'status');
            loading.setAttribute('aria-live', 'polite');
        }
    }

    /**
     * Reflect the active Zabbix theme on the widget root so theme.css variables
     * resolve correctly (Req 25.1, 25.2). Detects Zabbix body theme classes and
     * the prefers-color-scheme media query as a fallback.
     */
    applyTheme() {
        const widget = this.$('.ai-maintenance-widget');
        if (!widget) {
            return;
        }
        widget.classList.remove('aim-theme-dark', 'aim-theme-light');

        let isDark = false;
        try {
            const bodyClass = (document.body && document.body.className) || '';
            if (/dark-theme|theme-dark|hc-dark/.test(bodyClass)) {
                isDark = true;
            } else if (/blue-theme|theme-light|hc-light/.test(bodyClass)) {
                isDark = false;
            } else if (window.matchMedia) {
                isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            }
        } catch (e) {
            isDark = false;
        }

        widget.classList.add(isDark ? 'aim-theme-dark' : 'aim-theme-light');
    }

    /**
     * Append a chat message. `type` is one of user/assistant/system/success/
     * warning/error/info. Returns the created element.
     */
    addMessage(message, type) {
        if (!message) {
            return null;
        }
        const messages = this.$('#ai-messages');
        if (!messages) {
            return null;
        }

        const messageDiv = document.createElement('div');
        messageDiv.className = `ai-message ${type}`;
        messageDiv.setAttribute('role', 'listitem');

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = this.formatter.formatMessage(message);

        messageDiv.appendChild(contentDiv);
        messages.appendChild(messageDiv);
        this.scrollToBottom(messages);
        return messageDiv;
    }

    /**
     * Update the discreet header status chip (Req: connection status as a chip,
     * not a chat banner). `state` is one of 'ok' | 'warn' | 'err'; `text` is the
     * short localized label. The chip carries role="status"/aria-live from the
     * markup so the change is announced without flooding the chat log.
     *
     * @param {string} state  'ok' | 'warn' | 'err'
     * @param {string} text   Short label (e.g. "Connected").
     */
    setStatus(state, text) {
        const chip = this.$('#ai-status-chip');
        if (!chip) {
            return;
        }
        const known = state === 'ok' || state === 'warn' || state === 'err';
        const cls = known ? state : 'warn';
        chip.classList.remove('ok', 'warn', 'err');
        chip.classList.add(cls);

        const label = chip.querySelector('.ai-status-label');
        if (label) {
            label.textContent = text || '';
        } else {
            chip.textContent = text || '';
        }
        if (text) {
            chip.setAttribute('title', text);
            chip.setAttribute('aria-label', text);
        }
    }

    /**
     * Show/hide the processing indicator (Req 24.1). While visible it also renders
     * an in-line typing indicator inside the messages region so it is announced.
     */
    showLoading(show, message) {
        const loading = this.$('#ai-loading');
        const text = message || this.t('Processing...');

        if (loading) {
            if (show) {
                const loadingText = loading.querySelector('span');
                if (loadingText) {
                    loadingText.textContent = text;
                }
                loading.style.display = 'flex';
                loading.setAttribute('aria-hidden', 'false');
            } else {
                loading.style.display = 'none';
                loading.setAttribute('aria-hidden', 'true');
            }
        }

        this._toggleTypingIndicator(show, text);
    }

    _toggleTypingIndicator(show, text) {
        const messages = this.$('#ai-messages');
        if (!messages) {
            return;
        }
        if (show) {
            if (!this._typingEl) {
                const el = document.createElement('div');
                el.className = 'ai-message assistant ai-typing';
                el.setAttribute('role', 'status');
                el.setAttribute('aria-live', 'polite');
                el.innerHTML =
                    '<div class="message-content">' +
                    `<span class="typing-label">${this.formatter.escapeHtml(text)}</span>` +
                    '<span class="typing-dots"><span></span><span></span><span></span></span>' +
                    '</div>';
                this._typingEl = el;
                messages.appendChild(el);
                this.scrollToBottom(messages);
            } else {
                const label = this._typingEl.querySelector('.typing-label');
                if (label) {
                    label.textContent = text;
                }
            }
        } else if (this._typingEl) {
            this._typingEl.remove();
            this._typingEl = null;
        }
    }

    /**
     * Render a visible manual retry action after a backend failure (Req 24.3).
     * @param {string} errorMessage  Human-readable error text.
     * @param {Function} onRetry     Invoked when the user clicks retry.
     */
    showRetry(errorMessage, onRetry) {
        const messages = this.$('#ai-messages');
        if (!messages) {
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'ai-message error ai-retry-block';
        wrapper.setAttribute('role', 'alert');

        const content = document.createElement('div');
        content.className = 'message-content';
        content.innerHTML = this.formatter.formatMessage(errorMessage);

        const retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'ai-retry-button';
        retryBtn.textContent = this.t('Retry');
        retryBtn.setAttribute('aria-label', this.t('Retry last request'));
        retryBtn.addEventListener('click', () => {
            wrapper.remove();
            if (typeof onRetry === 'function') {
                onRetry();
            }
        });

        content.appendChild(document.createElement('br'));
        content.appendChild(retryBtn);
        wrapper.appendChild(content);
        messages.appendChild(wrapper);
        this.scrollToBottom(messages);
        // Move focus to the retry action so keyboard users reach it immediately.
        setTimeout(() => retryBtn.focus(), 50);
    }

    /** Render the maintenance confirmation dialog with focus management. */
    showConfirmation(detailsHtml) {
        const confirmation = this.$('#ai-confirmation');
        const details = this.$('#maintenance-details');
        if (!confirmation || !details) {
            return;
        }
        details.innerHTML = detailsHtml;
        confirmation.style.display = 'flex';
        confirmation.setAttribute('aria-hidden', 'false');

        const confirmButton = confirmation.querySelector('#confirm-maintenance');
        if (confirmButton) {
            setTimeout(() => confirmButton.focus(), 100);
        }
    }

    hideConfirmation() {
        const confirmation = this.$('#ai-confirmation');
        if (confirmation) {
            confirmation.style.display = 'none';
            confirmation.setAttribute('aria-hidden', 'true');
        }
        this.focusInput();
    }

    focusInput() {
        const input = this.$('#ai-input');
        if (input) {
            setTimeout(() => input.focus(), 100);
        }
    }

    getInputValue() {
        const input = this.$('#ai-input');
        return input ? input.value.trim() : '';
    }

    setInputValue(value) {
        const input = this.$('#ai-input');
        if (input) {
            input.value = value;
            this.adjustTextareaHeight(input);
        }
    }

    clearInput() {
        const input = this.$('#ai-input');
        if (input) {
            input.value = '';
            input.style.height = 'auto';
        }
    }

    /** Briefly highlight the input to signal invalid/empty submission. */
    highlightInput() {
        const input = this.$('#ai-input');
        if (!input) {
            return;
        }
        input.classList.add('ai-input-invalid');
        input.setAttribute('aria-invalid', 'true');
        input.focus();
        setTimeout(() => {
            input.classList.remove('ai-input-invalid');
            input.removeAttribute('aria-invalid');
        }, 2000);
    }

    adjustTextareaHeight(textarea) {
        if (!textarea) {
            return;
        }
        textarea.style.height = 'auto';
        const maxHeight = 300;
        const newHeight = Math.min(textarea.scrollHeight, maxHeight);
        textarea.style.height = newHeight + 'px';
    }

    setThinking(isThinking) {
        const avatar = this.$('.ai-avatar');
        if (avatar) {
            avatar.classList.toggle('thinking', !!isThinking);
        }
    }

    scrollToBottom(element) {
        const target = element || this.$('#ai-messages');
        if (!target) {
            return;
        }
        requestAnimationFrame(() => {
            target.scrollTop = target.scrollHeight;
        });
    }
}

if (typeof window !== 'undefined') {
    window.AIMaintenanceUIRenderer = AIMaintenanceUIRenderer;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AIMaintenanceUIRenderer;
}
