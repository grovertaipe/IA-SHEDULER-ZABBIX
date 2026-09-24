/**
 * class.widget.js — THIN orchestrator for the AI Maintenance widget (Req 22.2).
 *
 * This class no longer concentrates rendering + HTTP + formatting. It wires the
 * three collaborators and coordinates the conversation flow:
 *   - AIMaintenanceHttpClient       (assets/js/http.client.js)  — backend I/O + locale + retry
 *   - AIMaintenanceUIRenderer       (assets/js/ui.renderer.js)  — DOM, ARIA, focus, theme, typing
 *   - AIMaintenanceMessageFormatter (assets/js/message.formatter.js) — text/HTML formatting + preview
 *
 * i18n (Req 33.2): translatable JS strings are resolved through a SELF-CONTAINED
 * catalog (assets/js/i18n.js, class AIMaintenanceI18n) that follows the Zabbix
 * user's language (es/en/pt). The module strings are not present in Zabbix's .mo
 * catalogs, so the native `t()` helper is not relied upon. `_t()` below delegates
 * to the AIMaintenanceI18n instance and falls back to the key when unavailable.
 *
 * Backward compatibility is preserved: the widget keeps working against the v2
 * backend API contract (/chat, /parse, /create_maintenance, /health,
 * /maintenance/templates, /maintenance/list, /test/routine) and the response
 * `type` vocabulary (maintenance_request/help_request/clarification_needed/
 * off_topic/error). The api_url config field is still honored.
 */
class WidgetAIMaintenance extends CWidget {

    onInitialize() {
        super.onInitialize();
        this.api_url = '';
        this.current_parsed_data = null;
        this.user_info = null;
        this.templates = null;
        this.locale = this._detectLocale();

        // Multi-turn conversation memory (backend stays STATELESS): the widget
        // keeps the recent conversation SCOPED to the maintenance-in-progress
        // and resends it on each /chat call so the AI accumulates fields across
        // messages. The buffer is RESET when a maintenance is created OR
        // cancelled, and via the manual "new request" control, so previously
        // created maintenances never leak into the AI context. A safety cap
        // (MAX_HISTORY_TURNS) limits how many turns are ever resent, even if the
        // user never creates or cancels a maintenance.
        this.conversation_history = [];
        this.MAX_HISTORY_TURNS = 10;

        // Self-contained i18n instance driven by the detected locale (Req 33.2).
        this.i18n = this._buildI18n(this.locale);

        // Collaborators (constructed once contents are available).
        this.http = null;
        this.ui = null;
        this.formatter = null;
    }

    /**
     * Self-contained JS translation wrapper (Req 33.2). Delegates to the
     * AIMaintenanceI18n instance and falls back to the key (English) when the
     * catalog is unavailable (e.g. under a unit-test harness).
     */
    _t(key) {
        try {
            if (this.i18n && typeof this.i18n.t === 'function') {
                return this.i18n.t(key);
            }
        } catch (e) {
            // i18n not available in this context — fall through.
        }
        return key;
    }

    /** Construct an AIMaintenanceI18n instance for the given language, safely. */
    _buildI18n(lang) {
        try {
            if (typeof AIMaintenanceI18n === 'function') {
                return new AIMaintenanceI18n(lang);
            }
        } catch (e) {
            // i18n module not loaded — _t() will fall back to the key.
        }
        return null;
    }

    /**
     * Resolve the active UI language (es/en/pt) from the document language.
     * Defaults to 'en' when the language is missing or unsupported.
     */
    _detectLocale() {
        const supported = ['es', 'en', 'pt'];
        try {
            const lang = (document.documentElement && document.documentElement.lang) || '';
            if (lang) {
                const prefix = lang.split('-')[0].toLowerCase();
                if (supported.indexOf(prefix) !== -1) {
                    return prefix;
                }
            }
        } catch (e) {
            // ignore
        }
        return 'en';
    }

    processUpdateResponse(response) {
        this.api_url = response.fields_values?.api_url || 'http://localhost:5005';

        if (response.user_info) {
            this.user_info = {
                username: response.user_info.username || '',
                name: response.user_info.name || '',
                surname: response.user_info.surname || '',
                userid: response.user_info.userid || ''
            };
        }

        super.processUpdateResponse(response);
    }

    setContents(response) {
        super.setContents(response);
        this._buildCollaborators();
        this.ui.applyTheme();
        this.ui.enhanceAccessibility();
        this.ui.renderNewRequestControl();
        this.setupEventListeners();
        this.loadMaintenanceTemplates();
        this.checkBackendConnection();
    }

    _buildCollaborators() {
        const t = (key) => this._t(key);

        this.formatter = new AIMaintenanceMessageFormatter({ t });
        this.ui = new AIMaintenanceUIRenderer(this._body, { formatter: this.formatter, t });
        this.http = new AIMaintenanceHttpClient({
            apiUrl: this.api_url,
            locale: this.locale,
            timeout: 60000,
            maxRetries: 2
        });
    }

    // ---------------------------------------------------------------------
    // Event wiring
    // ---------------------------------------------------------------------

    setupEventListeners() {
        const send_btn = this._body.querySelector('#ai-send-btn');
        const input = this._body.querySelector('#ai-input');
        const confirm_btn = this._body.querySelector('#confirm-maintenance');
        const cancel_btn = this._body.querySelector('#cancel-maintenance');
        const templates_btn = this._body.querySelector('#templates-btn');
        const new_request_btn = this._body.querySelector('#ai-new-request-btn');

        if (send_btn) {
            send_btn.addEventListener('click', () => this.onSendMessage());
        }
        if (new_request_btn) {
            new_request_btn.addEventListener('click', () => this.onNewRequest());
        }
        if (input) {
            input.addEventListener('keydown', (e) => this.onKeyDown(e));
            input.addEventListener('input', (e) => this.ui.adjustTextareaHeight(e.target));
        }
        if (confirm_btn) {
            confirm_btn.addEventListener('click', () => this.onConfirmMaintenance());
        }
        if (cancel_btn) {
            cancel_btn.addEventListener('click', () => this.onCancelMaintenance());
        }
        if (templates_btn) {
            templates_btn.addEventListener('click', () => this.showTemplates());
        }

        // Escape cancels/clears anywhere in the widget (Req 23.3).
        this._body.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.onEscape(e);
            }
        });

        // Clickable welcome example cards: preload (do NOT auto-send) the card's
        // example into the input. Delegated on the messages/welcome region so it
        // keeps working across re-renders, with keyboard (Enter/Space) parity.
        const messages = this._body.querySelector('#ai-messages');
        if (messages) {
            messages.addEventListener('click', (e) => this.onFeatureCardActivate(e));
            messages.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    this.onFeatureCardActivate(e);
                }
            });
        }
    }

    /**
     * Activate a welcome feature card: copy its data-example into the input and
     * focus it, WITHOUT sending. Handles both click and keyboard (Enter/Space)
     * activation; on Space it prevents the default page scroll (Req 23.3).
     */
    onFeatureCardActivate(event) {
        const card = event.target && event.target.closest
            ? event.target.closest('.feature-item')
            : null;
        if (!card || !card.hasAttribute('data-example')) {
            return;
        }
        // For keyboard activation, stop Space from scrolling / Enter side effects.
        if (event.type === 'keydown') {
            event.preventDefault();
        }
        const example = card.getAttribute('data-example') || '';
        if (!example) {
            return;
        }
        this.ui.setInputValue(example);
        this.ui.focusInput();
    }

    /** Keyboard operability (Req 23.3): Enter sends, Ctrl/Cmd+Enter inserts newline. */
    onKeyDown(event) {
        if (event.key === 'Enter') {
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                const input = event.target;
                const start = input.selectionStart;
                const end = input.selectionEnd;
                input.value = input.value.substring(0, start) + '\n' + input.value.substring(end);
                input.selectionStart = input.selectionEnd = start + 1;
                this.ui.adjustTextareaHeight(input);
            } else {
                event.preventDefault();
                this.onSendMessage();
            }
        }
    }

    /** Escape cancels the confirmation dialog if open, else clears the input. */
    onEscape(event) {
        const confirmation = this._body.querySelector('#ai-confirmation');
        if (confirmation && confirmation.style.display !== 'none') {
            event.preventDefault();
            this.onCancelMaintenance();
            return;
        }
        const input = this._body.querySelector('#ai-input');
        if (input && document.activeElement === input && input.value !== '') {
            event.preventDefault();
            this.ui.clearInput();
        }
    }

    // ---------------------------------------------------------------------
    // Backend interactions (delegated to http client)
    // ---------------------------------------------------------------------

    /**
     * Probe the backend health and reflect it in the discreet header status
     * chip instead of a large chat banner. Healthy -> green "Connected",
     * degraded -> amber "degraded", unreachable/unhealthy -> red "Disconnected".
     * The chip is announced via its own aria-live region (see ui.setStatus).
     */
    async checkBackendConnection() {
        try {
            const data = await this.http.getJson('/health');

            if (data.status === 'unhealthy') {
                this.ui.setStatus('err', this._t('Disconnected'));
            } else if (data.status === 'degraded') {
                this.ui.setStatus('warn', this._t('Degraded'));
            } else {
                this.ui.setStatus('ok', this._t('System connected'));
            }
        } catch (error) {
            console.warn('Error verifying backend connection:', error);
            this.ui.setStatus('err', this._t('Disconnected'));
        }
    }

    async loadMaintenanceTemplates() {
        try {
            const templates = await this.http.getJson('/maintenance/templates');
            this.templates = templates.templates;
        } catch (error) {
            console.warn('Error loading templates:', error);
        }
    }

    showTemplates() {
        if (!this.templates) {
            this.ui.addMessage(
                this._t('Templates are not available right now.') + '\n\n' +
                '**' + this._t('Routine maintenance examples') + ':**\n' +
                '• **' + this._t('Daily') + ':** "' + this._t('template.example.daily') + '"\n' +
                '• **' + this._t('Weekly') + ':** "' + this._t('template.example.weekly') + '"\n' +
                '• **' + this._t('Monthly') + ':** "' + this._t('template.example.monthly') + '"',
                'info'
            );
            return;
        }

        let templateMsg = '**' + this._t('Routine maintenance templates') + '**\n\n';
        Object.entries(this.templates).forEach(([type, info]) => {
            const icon = type === 'daily' ? this._t('Daily')
                : type === 'weekly' ? this._t('Weekly') : this._t('Monthly');
            templateMsg += `${icon} **${info.name}**\n`;
            templateMsg += `${info.description}\n`;
            templateMsg += '**' + this._t('Examples') + ':**\n';
            (info.examples || []).forEach((example) => {
                templateMsg += `• "${example}"\n`;
            });
            templateMsg += '\n';
        });

        this.ui.addMessage(templateMsg, 'info');
    }

    async onSendMessage() {
        const message = this.ui.getInputValue();
        if (!message) {
            this.ui.highlightInput();
            return;
        }
        if (message.length < 5) {
            this.ui.addMessage(this._t('The message is too short. Describe what kind of maintenance you need to create.'), 'warning');
            this.ui.highlightInput();
            return;
        }
        if (message.length > 1000) {
            this.ui.addMessage(this._t('The message is too long. Please be more concise.'), 'warning');
            return;
        }

        this._sendMessage(message);
    }

    // ---------------------------------------------------------------------
    // Conversation memory (widget-side, backend stays stateless)
    // ---------------------------------------------------------------------

    /**
     * Push a turn onto the maintenance-scoped history buffer and enforce the
     * safety cap so we never resend more than MAX_HISTORY_TURNS turns, even if
     * the user never creates or cancels a maintenance.
     * @param {string} role     'user' | 'assistant'
     * @param {string} content  The turn text.
     */
    _pushHistory(role, content) {
        const text = (content == null ? '' : String(content)).trim();
        if (!text) {
            return;
        }
        this.conversation_history.push({ role, content: text });
        if (this.conversation_history.length > this.MAX_HISTORY_TURNS) {
            // Keep only the most recent turns.
            this.conversation_history = this.conversation_history.slice(-this.MAX_HISTORY_TURNS);
        }
    }

    /**
     * Reset the maintenance-scoped conversation memory. Called when a
     * maintenance is created or cancelled and from the manual "new request"
     * control, so a fresh maintenance starts with a clean AI context.
     */
    _resetHistory() {
        this.conversation_history = [];
    }

    /**
     * Remove the trailing user turn matching `content` if it is dangling (i.e.
     * the /chat exchange failed before an assistant reply was recorded), so a
     * manual retry does not duplicate it in the resent history.
     * @param {string} content
     */
    _dropLastUserTurn(content) {
        const last = this.conversation_history[this.conversation_history.length - 1];
        const text = (content == null ? '' : String(content)).trim();
        if (last && last.role === 'user' && last.content === text) {
            this.conversation_history.pop();
        }
    }

    async _sendMessage(message) {
        this.ui.setThinking(true);
        this.ui.clearInput();
        this.ui.addMessage(message, 'user');
        this.ui.showLoading(true, this._t('Analyzing request...'));

        // Record the user's turn BEFORE calling /chat and resend the buffer
        // (prior turns + this user turn) so the stateless backend accumulates
        // fields across messages. The assistant turn is appended only after a
        // successful response, so the current user message is never doubled.
        this._pushHistory('user', message);

        try {
            const data = await this.http.postJson('/chat', {
                message: message,
                user_info: this.user_info,
                history: this.conversation_history
            }, {
                onRetry: (attempt, max) => {
                    this.ui.addMessage(
                        `${this._t('Connection error')} (${attempt}/${max}). ${this._t('Retrying...')}`,
                        'warning'
                    );
                }
            });

            // Append the assistant's reply text (what the user is shown) so the
            // next turn carries it as context.
            if (data && typeof data === 'object' && typeof data.message === 'string') {
                this._pushHistory('assistant', data.message);
            }

            this.handleInteractiveResponse(data);
        } catch (error) {
            console.error('Error in onSendMessage:', error);
            // The exchange failed (no assistant reply). Drop the dangling user
            // turn we optimistically pushed so a manual retry re-adds it exactly
            // once instead of duplicating it in the resent history.
            this._dropLastUserTurn(message);
            this._handleFailure(error, message);
        } finally {
            this.ui.showLoading(false);
            this.ui.setThinking(false);
        }
    }

    /**
     * After automatic retries are exhausted, present a visible manual retry
     * action so the user can re-send the same message (Req 24.3).
     */
    _handleFailure(error, originalMessage) {
        let errorMessage;
        if (error && error.code === 'timeout') {
            errorMessage = this._t('The request took too long. You can try again.');
        } else if (error && (error.code === 'network' || String(error.message).includes('fetch'))) {
            errorMessage = this._t('Could not connect to the backend. Verify the service is running.');
        } else {
            errorMessage = `${this._t('Error')}: ${error.message}`;
        }

        this.ui.showRetry(errorMessage, () => this._sendMessage(originalMessage));
    }

    // ---------------------------------------------------------------------
    // Response handling — preserves the legacy `type` vocabulary
    // ---------------------------------------------------------------------

    handleInteractiveResponse(data) {
        if (!data || typeof data !== 'object') {
            this.ui.addMessage(this._t('Invalid response from server'), 'error');
            return;
        }

        switch (data.type) {
            case 'maintenance_request':
                this.current_parsed_data = data;
                this.showMaintenanceResults(data);
                break;

            case 'help_request':
                this.ui.addMessage(data.message, 'assistant');
                if (data.examples) {
                    this.showExamples(data.examples);
                }
                break;

            case 'off_topic':
                this.ui.addMessage(data.message, 'info');
                break;

            case 'clarification_needed':
                this.ui.addMessage(data.message, 'warning');
                if (data.detected_info && Object.keys(data.detected_info).length > 0) {
                    this.showDetectedInfo(data.detected_info);
                }
                break;

            case 'error':
                this.ui.addMessage(data.message, 'error');
                break;

            default:
                console.warn(`Unknown response type: ${data.type}`);
                this.ui.addMessage(
                    data.message || this._t('I received a response I could not fully process.'),
                    'assistant'
                );
                break;
        }
    }

    showDetectedInfo(detectedInfo) {
        let infoMsg = '\n**' + this._t('Detected information') + ':**\n';
        Object.entries(detectedInfo).forEach(([key, value]) => {
            if (value) {
                const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
                infoMsg += `• ${displayKey}: ${value}\n`;
            }
        });
        this.ui.addMessage(infoMsg, 'info');
    }

    showMaintenanceResults(data) {
        if (!data) {
            return;
        }
        const message = this.formatter.buildMaintenanceSummary(data);
        this.ui.addMessage(message, 'assistant');

        if (this.formatter.hasValidTargets(data)) {
            this.ui.showConfirmation(this.formatter.buildConfirmationDetailsHtml(data));
        } else {
            this.ui.addMessage(this._t('No valid hosts or groups found to create the maintenance'), 'warning');
        }
    }

    showExamples(examples) {
        if (!examples || examples.length === 0) {
            return;
        }
        let exampleMsg = '\n**' + this._t('Examples') + ':**\n\n';
        examples.forEach((example, index) => {
            exampleMsg += `${index + 1}. **${example.title}**\n`;
            exampleMsg += `   "${example.example}"\n\n`;
        });
        this.ui.addMessage(exampleMsg, 'info');
    }

    async onConfirmMaintenance() {
        if (!this.current_parsed_data) {
            this.ui.addMessage(this._t('There is no maintenance data to confirm'), 'error');
            return;
        }
        if (!this.formatter.hasValidTargets(this.current_parsed_data)) {
            this.ui.addMessage(this._t('There are no valid hosts or groups to create the maintenance'), 'error');
            return;
        }

        this.ui.showLoading(true, this._t('Creating maintenance...'));

        try {
            const parsed = this.current_parsed_data;
            const maintenanceData = {
                start_time: parsed.start_time,
                end_time: parsed.end_time,
                description: parsed.description || '',
                trigger_tags: parsed.trigger_tags || [],
                recurrence_type: parsed.recurrence_type || 'once',
                ticket_number: parsed.ticket_number || '',
                user_info: this.user_info
            };
            if (parsed.recurrence_config) {
                maintenanceData.recurrence_config = parsed.recurrence_config;
            }
            if (parsed.found_hosts && parsed.found_hosts.length > 0) {
                maintenanceData.hosts = parsed.found_hosts.map((h) => h.host);
            }
            if (parsed.found_groups && parsed.found_groups.length > 0) {
                maintenanceData.groups = parsed.found_groups.map((g) => g.name);
            }
            // Maintenance suppression config (Req 32): forward what /chat
            // returned so the tags the AI extracted actually reach Zabbix on
            // create. Defensive — only include each field when present.
            if (parsed.problem_tags && parsed.problem_tags.length > 0) {
                maintenanceData.problem_tags = parsed.problem_tags;
            }
            if (parsed.tags_evaltype !== undefined && parsed.tags_evaltype !== null) {
                maintenanceData.tags_evaltype = parsed.tags_evaltype;
            }
            if (parsed.maintenance_type !== undefined && parsed.maintenance_type !== null) {
                maintenanceData.maintenance_type = parsed.maintenance_type;
            }

            const data = await this.http.postJson('/create_maintenance', maintenanceData);
            this.ui.addMessage(data.message, 'success');

            // Maintenance created successfully: reset the maintenance-scoped
            // conversation memory so the next request starts with a clean AI
            // context and the just-created maintenance never leaks into it.
            this._resetHistory();

            if (data.is_routine) {
                this.ui.addMessage(
                    '**' + this._t('Routine maintenance configured') + '**\n' +
                    `• ${this._t('Type')}: ${data.recurrence_type}\n` +
                    `• ID: ${data.maintenance_id || this._t('Auto-generated')}\n` +
                    `• ${this._t('It will run automatically according to the configuration')}`,
                    'info'
                );
            }

            this.updateMaintenanceList();
        } catch (error) {
            console.error('Error creating maintenance:', error);
            this.ui.addMessage(`${this._t('Error creating maintenance')}: ${error.message}`, 'error');
        } finally {
            this.ui.showLoading(false);
            // Clear the pending confirmation WITHOUT resetting history here: on
            // success the history was already reset above; on failure we keep
            // the context so the user can adjust and retry the same maintenance.
            this._clearPendingConfirmation();
        }
    }

    async updateMaintenanceList() {
        try {
            // /maintenance/list now requires a validated logged-in Zabbix user.
            // Being a GET, the user is carried via ?userid= (Req 11). When we
            // have no user the backend replies 401; the catch below just logs
            // it and skips the summary — the widget never crashes.
            const userid = this.user_info?.userid;
            const endpoint = userid
                ? `/maintenance/list?userid=${encodeURIComponent(userid)}`
                : '/maintenance/list';
            const data = await this.http.getJson(endpoint);
            const maintenances = data.maintenances || [];
            if (maintenances.length > 0) {
                const routineCount = maintenances.filter((m) => m.is_routine).length;
                const oneTimeCount = maintenances.length - routineCount;
                const withTickets = maintenances.filter((m) => m.ticket_number).length;

                this.ui.addMessage(
                    '**' + this._t('Maintenance summary') + ':**\n' +
                    `• ${this._t('Single')}: ${oneTimeCount}\n` +
                    `• ${this._t('Routine')}: ${routineCount}\n` +
                    `• ${this._t('With tickets')}: ${withTickets}\n` +
                    `• ${this._t('Total')}: ${maintenances.length}`,
                    'info'
                );
            }
        } catch (error) {
            console.error('Error updating list:', error);
        }
    }

    /**
     * Clear the pending confirmation dialog and the last preview WITHOUT
     * touching the conversation memory. Shared by the create success/failure
     * cleanup and by the user-initiated cancel.
     */
    _clearPendingConfirmation() {
        this.ui.hideConfirmation();
        this.current_parsed_data = null;
    }

    /**
     * User-initiated cancel of the pending maintenance. Clears the confirmation
     * AND resets the maintenance-scoped conversation memory (A): a cancelled
     * request should not bleed into the next one.
     */
    onCancelMaintenance() {
        this._clearPendingConfirmation();
        this._resetHistory();
    }

    /**
     * Manual "new request" reset (B): clear the conversation memory and any
     * pending confirmation so the user can start a brand-new maintenance with a
     * clean AI context. Adds a small system note for feedback.
     */
    onNewRequest() {
        this._resetHistory();
        this._clearPendingConfirmation();
        this.ui.addMessage(this._t('Context reset. Describe a new maintenance.'), 'info');
        this.ui.focusInput();
    }

    destroy() {
        super.destroy?.();
    }
}
