class WidgetAIMaintenance extends CWidget {
    
    onInitialize() {
        super.onInitialize();
        this.api_url = '';
        this.current_parsed_data = null;
        this.user_info = null;
        this.templates = null;
        this.request_timeout = 60000;
        this.retry_count = 0;
        this.max_retries = 2;
        this.translations = {};
        this.currentLang = 'en';
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
        this.loadTranslations();
    }

    async loadTranslations() {
        this.currentLang = this.getZabbixLocale();
        try {
            const response = await fetch(`widgets/aimaintenance/locale/${this.currentLang}.json`);
            this.translations = await response.json();
        } catch (error) {
            try {
                const response = await fetch('widgets/aimaintenance/locale/en.json');
                this.translations = await response.json();
            } catch (fallbackError) {
                console.warn('Could not load translations, using fallback');
                this.translations = {
                    'templates_not_available': 'Templates are not available at this time',
                    'routine_maintenance_examples': 'Routine maintenance examples',
                    'daily': 'Daily',
                    'weekly': 'Weekly',
                    'monthly_specific_day': 'Monthly specific day',
                    'monthly_weekday': 'Monthly weekday',
                    'daily_backup_example': 'daily backup 2 AM ticket 100-178306',
                    'weekly_maintenance_example': 'Sunday maintenance 1-3 AM ticket 200-8341',
                    'monthly_day_example': 'cleanup day 5 each month ticket 500-43116',
                    'monthly_weekday_example': 'update first Sunday each month ticket 600-78901'
                };
            }
        }
        this.setupEventListeners();
        this.loadMaintenanceTemplates();
        this.checkBackendConnection();
    }

    getZabbixLocale() {
        if (typeof locale !== 'undefined' && locale) {
            return locale.substring(0, 2);
        }
        if (typeof PHP !== 'undefined' && PHP.ZBX_LANG) {
            return PHP.ZBX_LANG.substring(0, 2);
        }
        if (document.documentElement.lang) {
            return document.documentElement.lang.substring(0, 2);
        }
        return 'en';
    }

    t(key) {
        return this.translations[key] || key;
    }

    async checkBackendConnection() {
        try {
            const response = await fetch(`${this.api_url}/health`, {
                method: 'GET',
                timeout: 10000
            });
            
            if (!response.ok) {
                throw new Error(`Backend no disponible (${response.status})`);
            }
            
            const data = await response.json();
            
            if (data.status === 'unhealthy' || data.status === 'degraded') {
                this.addMessage(
                    `Sistema reporta estado: ${data.status}\n` +
                    `Estado de Zabbix: ${data.zabbix_connected ? 'Conectado' : 'Desconectado'}\n` +
                    `Proveedor IA: ${data.ai_provider || 'No disponible'}\n` +
                    `Soporte bitmask: ${data.features?.includes('bitmask_support') ? 'Habilitado' : 'Deshabilitado'}\n` +
                    `${data.status === 'degraded' ? 'Algunas funciones pueden estar limitadas.' : ''}`,
                    'warning'
                );
            } else {
                const features = data.features || [];
                this.addMessage(
                    `Sistema Conectado - v${data.version}\n` +
                    `Zabbix: ${data.zabbix_connected ? 'Conectado' : 'Desconectado'}\n` +
                    `IA: ${data.ai_provider}\n` +
                    `Funciones: ${features.includes('routine_maintenance') ? 'Rutinarios' : ''} ` +
                    `${features.includes('bitmask_support') ? 'Bitmask' : ''} ` +
                    `${features.includes('ticket_support') ? 'Tickets' : ''}`,
                    'success'
                );
            }
            
        } catch (error) {
            console.warn("Error verificando conexión con backend:", error);
            this.addMessage(
                this.t('system_status') + ':\n' +
                this.t('could_not_verify_backend') + '.\n' +
                'URL: ' + this.api_url + '\n' +
                this.t('functions_may_be_limited') + '.',
                'info'
            );
        }
    }

    setupEventListeners() {
        const send_btn = this._body.querySelector('#ai-send-btn');
        const input = this._body.querySelector('#ai-input');
        const confirm_btn = this._body.querySelector('#confirm-maintenance');
        const cancel_btn = this._body.querySelector('#cancel-maintenance');
        const templates_btn = this._body.querySelector('#templates-btn');

        if (send_btn) {
            send_btn.addEventListener('click', () => this.onSendMessage());
        }
        
        if (input) {
            input.addEventListener('keypress', (e) => this.onKeyPress(e));
            input.addEventListener('input', (e) => this.adjustTextareaHeight(e.target));
            input.addEventListener('focus', this.clearPlaceholderOnce.bind(this));
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
    }

    clearPlaceholderOnce(event) {
        const input = event.target;
        if (input.value === '' && input.placeholder.includes('Ej:')) {
            input.placeholder = this.t('description_placeholder');
        }
        input.removeEventListener('focus', this.clearPlaceholderOnce);
    }

    adjustTextareaHeight(textarea) {
        if (!textarea) return;
        
        textarea.style.height = 'auto';
        const maxHeight = 300;
        const newHeight = Math.min(textarea.scrollHeight, maxHeight);
        textarea.style.height = newHeight + 'px';
    }

    onKeyPress(event) {
        if (event.key === 'Enter') {
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                const input = event.target;
                const start = input.selectionStart;
                const end = input.selectionEnd;
                input.value = input.value.substring(0, start) + '\n' + input.value.substring(end);
                input.selectionStart = input.selectionEnd = start + 1;
                this.adjustTextareaHeight(input);
            } else {
                event.preventDefault();
                this.onSendMessage();
            }
        }
    }

    async loadMaintenanceTemplates() {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);

            const response = await fetch(`${this.api_url}/maintenance/templates`, {
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);

            if (response.ok) {
                const templates = await response.json();
                this.templates = templates.templates;
                console.log("Templates loaded:", Object.keys(this.templates || {}).length);
            } else {
                console.warn(`Error cargando plantillas: ${response.status}`);
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.warn("Timeout loading templates");
            } else {
                console.error("Error loading templates:", error);
            }
        }
    }

    showTemplates() {
        if (!this.templates) {
            this.addMessage(
                this.t('templates_not_available') + '.\n\n' +
                '**' + this.t('routine_maintenance_examples') + ':**\n' +
                '• **' + this.t('daily') + ':** \'' + this.t('daily_backup_example') + '\'\n' +
                '• **' + this.t('weekly') + ':** \'' + this.t('weekly_maintenance_example') + '\'\n' +
                '• **' + this.t('monthly_specific_day') + ':** \'' + this.t('monthly_day_example') + '\'\n' +
                '• **' + this.t('monthly_weekday') + ':** \'' + this.t('monthly_weekday_example') + '\'',
                'info'
            );
            return;
        }
        
        let templateMsg = "**" + this.t('routine_maintenance_templates') + "**\n\n";
        
        Object.entries(this.templates).forEach(([type, info]) => {
            const icon = type === 'daily' ? this.t('daily') : type === 'weekly' ? this.t('weekly') : this.t('monthly');
            templateMsg += `${icon} **${info.name}**\n`;
            templateMsg += `${info.description}\n`;
            templateMsg += "**" + this.t('examples') + ":**\n";
            info.examples.forEach(example => {
                templateMsg += `• "${example}"\n`;
            });
            templateMsg += "\n";
        });
        
        templateMsg += "**" + this.t('tips_for_routine_maintenance') + ":**\n";
        templateMsg += "• **" + this.t('daily') + ":** '" + this.t('daily_keywords') + "'\n";
        templateMsg += "• **" + this.t('weekly') + ":** '" + this.t('weekly_keywords') + "'\n";
        templateMsg += "• **" + this.t('monthly_day') + ":** '" + this.t('monthly_day_keywords') + "'\n";
        templateMsg += "• **" + this.t('monthly_week') + ":** '" + this.t('monthly_week_keywords') + "'\n";
        templateMsg += "• **" + this.t('tickets') + ":** " + this.t('ticket_tip') + "\n";
        templateMsg += "\n**" + this.t('tip') + ":** " + this.t('routine_bitmask_tip');
        
        this.addMessage(templateMsg, 'info');
    }

    async onSendMessage() {
        const input = this._body.querySelector('#ai-input');
        if (!input) return;
        
        const message = input.value.trim();
        if (!message) {
            this.highlightInput(input);
            return;
        }

        if (message.length < 5) {
            this.addMessage(this.t('message_too_short'), 'warning');
            this.highlightInput(input);
            return;
        }

        if (message.length > 1000) {
            this.addMessage(this.t('message_too_long'), 'warning');
            return;
        }

        const avatar = this._body.querySelector('.ai-avatar');
        if (avatar) {
            avatar.classList.add('thinking');
        }

        input.value = '';
        input.style.height = 'auto';
        this.addMessage(message, 'user');
        this.showLoading(true, this.t('processing_request'));

        try {
            const requestData = { 
                message: message,
                user_info: this.user_info
            };

            const response = await this.makeRequest('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `${this.t('server_error')} (${response.status})`);
            }

            const data = await response.json();
            this.handleInteractiveResponse(data);
            this.retry_count = 0;

        } catch (error) {
            console.error("Error in onSendMessage:", error);
            this.handleRequestError(error, message);
        } finally {
            this.showLoading(false);
            if (avatar) {
                avatar.classList.remove('thinking');
            }
        }
    }

    async makeRequest(endpoint, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.request_timeout);

        try {
            const response = await fetch(`${this.api_url}${endpoint}`, {
                ...options,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error(this.t('request_timeout'));
            }
            throw error;
        }
    }

    highlightInput(input) {
        if (!input) return;
        
        input.style.borderColor = '#ff4757';
        input.focus();
        
        setTimeout(() => {
            input.style.borderColor = '';
        }, 2000);
    }

    handleRequestError(error, originalMessage) {
        if (this.retry_count < this.max_retries && 
            (error.message.includes('timeout') || error.message.includes('network'))) {
            
            this.retry_count++;
            this.addMessage(
                `${this.t('connection_error')} ${this.retry_count}/${this.max_retries + 1}). ${this.t('retrying')}`,
                'warning'
            );
            
            setTimeout(() => {
                const input = this._body.querySelector('#ai-input');
                if (input) {
                    input.value = originalMessage;
                    this.onSendMessage();
                }
            }, 2000);
        } else {
            this.retry_count = 0;
            const errorMessage = error.message.includes('fetch') 
                ? this.t('could_not_connect_backend')
                : `Error: ${error.message}`;
            
            this.addMessage(`${errorMessage}`, 'error');
        }
    }

    handleInteractiveResponse(data) {
        if (!data || typeof data !== 'object') {
            this.addMessage(this.t('invalid_server_response'), 'error');
            return;
        }

        const responseType = data.type;
        
        switch (responseType) {
            case 'maintenance_request':
                this.current_parsed_data = data;
                this.showMaintenanceResults(data);
                break;
                
            case 'help_request':
                this.addMessage(data.message, 'assistant');
                if (data.examples) {
                    this.showExamples(data.examples);
                }
                break;
                
            case 'off_topic':
                this.addMessage(data.message, 'info');
                break;
                
            case 'clarification_needed':
                this.addMessage(data.message, 'warning');
                if (data.detected_info && Object.keys(data.detected_info).length > 0) {
                    this.showDetectedInfo(data.detected_info);
                }
                break;
                
            case 'error':
                this.addMessage(data.message, 'error');
                break;
                
            default:
                console.warn(`Tipo de respuesta desconocido: ${responseType}`);
                this.addMessage(
                    data.message || this.t('unknown_response'), 
                    'assistant'
                );
                break;
        }
    }

    showDetectedInfo(detectedInfo) {
        let infoMsg = "\n**" + this.t('detected_information') + ":**\n";
        Object.entries(detectedInfo).forEach(([key, value]) => {
            if (value) {
                const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                infoMsg += `• ${displayKey}: ${value}\n`;
            }
        });
        this.addMessage(infoMsg, 'info');
    }

    showMaintenanceResults(data) {
        if (!data) return;

        let message = '';
        
        if (data.message && data.message.trim()) {
            message = data.message + '\n\n';
        } else {
            message = `**${this.t('analysis_completed')}**\n\n`;
        }
        
        if (data.ticket_number && data.ticket_number.trim()) {
            message += `**${this.t('ticket')}:** ${data.ticket_number}\n\n`;
        }
        
        const recurrenceLabel = this.getRecurrenceTypeLabel(data.recurrence_type);
        const isRoutine = data.recurrence_type !== 'once';
        
        const typeIcon = isRoutine ? this.t('routine') : this.t('unique');
        message += `**${this.t('type')}:** ${recurrenceLabel} (${typeIcon})\n\n`;
        
        if (isRoutine && data.recurrence_config) {
            const configInfo = this.formatRecurrenceConfig(data.recurrence_type, data.recurrence_config);
            if (configInfo) {
                message += `**${this.t('configuration')}:** ${configInfo}\n\n`;
            }
        }
        
        if (data.search_summary) {
            const summary = data.search_summary;
            message += `**${this.t('summary')}:**\n`;
            message += `• ${this.t('hosts_found')}: ${summary.total_hosts_found}\n`;
            message += `• ${this.t('groups_found')}: ${summary.total_groups_found}\n`;
            if (summary.hosts_by_tags > 0) {
                message += `• ${this.t('hosts_by_tags')}: ${summary.hosts_by_tags}\n`;
            }
            if (summary.has_ticket) {
                message += `• ${this.t('with_ticket')}: ${this.t('yes')}\n`;
            }
            if (summary.is_routine) {
                message += `• ${this.t('routine_maintenance')}: ${this.t('yes')}\n`;
            }
            message += '\n';
        }
        
        message = this.appendResourcesInfo(message, data);
        
        if (data.start_time && data.end_time) {
            message += `**${this.t('period')}:**\n`;
            message += `• ${this.t('from')}: ${data.start_time}\n`;
            message += `• ${this.t('to')}: ${data.end_time}\n\n`;
        }
        
        if (data.description && data.description.trim()) {
            message += `**${this.t('description')}:** ${data.description}\n\n`;
        }

        if (data.confidence && data.confidence > 0) {
            message += `**${this.t('confidence')}:** ${data.confidence}%`;
        }

        this.addMessage(message, 'assistant');

        const hasValidTargets = this.hasValidTargets(data);
        
        if (hasValidTargets) {
            this.showConfirmation(data);
        } else {
            this.addMessage(this.t('no_valid_hosts_groups'), 'warning');
        }
    }
    
    appendResourcesInfo(baseMessage, data) {
        let message = baseMessage;

        if (data.found_hosts && data.found_hosts.length > 0) {
            message += `**${this.t('servers_found')} (${data.found_hosts.length}):**\n`;
            data.found_hosts.forEach(host => {
                const displayName = host.name || host.host;
                message += `• ${displayName} (${host.host})\n`;
            });
            message += '\n';
        }

        if (data.found_groups && data.found_groups.length > 0) {
            message += `**${this.t('groups_found')} (${data.found_groups.length}):**\n`;
            data.found_groups.forEach(group => {
                message += `• ${group.name}\n`;
            });
            message += '\n';
        }

        if (data.trigger_tags && data.trigger_tags.length > 0) {
            message += `**${this.t('trigger_tags')}:**\n`;
            data.trigger_tags.forEach(tag => {
                message += `• ${tag.tag}: ${tag.value}\n`;
            });
            message += '\n';
        }

        if (data.missing_hosts && data.missing_hosts.length > 0) {
            message += `**${this.t('servers_not_found')}:**\n`;
            data.missing_hosts.forEach(host => {
                message += `• ${host}\n`;
            });
            message += '\n';
        }

        if (data.missing_groups && data.missing_groups.length > 0) {
            message += `**${this.t('groups_not_found')}:**\n`;
            data.missing_groups.forEach(group => {
                message += `• ${group}\n`;
            });
            message += '\n';
        }

        return message;
    }

    hasValidTargets(data) {
        return (data.found_hosts && data.found_hosts.length > 0) || 
               (data.found_groups && data.found_groups.length > 0);
    }

    showExamples(examples) {
        if (!examples || examples.length === 0) return;
        
        let exampleMsg = "\n**" + this.t('examples') + ":**\n\n";
        
        examples.forEach((example, index) => {
            exampleMsg += `${index + 1}. **${example.title}**\n`;
            exampleMsg += `   "${example.example}"\n\n`;
        });
        
        this.addMessage(exampleMsg, 'info');
    }

    async onConfirmMaintenance() {
        if (!this.current_parsed_data) {
            this.addMessage(this.t('no_maintenance_data'), 'error');
            return;
        }
        
        const hasValidTargets = this.hasValidTargets(this.current_parsed_data);
        
        if (!hasValidTargets) {
            this.addMessage(this.t('no_valid_hosts_groups'), 'error');
            return;
        }
        
        this.showLoading(true, this.t('creating_maintenance'));
        
        try {
            const maintenanceData = {
                start_time: this.current_parsed_data.start_time,
                end_time: this.current_parsed_data.end_time,
                description: this.current_parsed_data.description || '',
                trigger_tags: this.current_parsed_data.trigger_tags || [],
                recurrence_type: this.current_parsed_data.recurrence_type || 'once',
                ticket_number: this.current_parsed_data.ticket_number || '',
                user_info: this.user_info
            };

            if (this.current_parsed_data.recurrence_config) {
                maintenanceData.recurrence_config = this.current_parsed_data.recurrence_config;
            }

            if (this.current_parsed_data.found_hosts && this.current_parsed_data.found_hosts.length > 0) {
                maintenanceData.hosts = this.current_parsed_data.found_hosts.map(h => h.host);
            }

            if (this.current_parsed_data.found_groups && this.current_parsed_data.found_groups.length > 0) {
                maintenanceData.groups = this.current_parsed_data.found_groups.map(g => g.name);
            }

            console.log("Datos de mantenimiento a enviar:", maintenanceData);

            const response = await this.makeRequest('/create_maintenance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(maintenanceData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `${this.t('server_error')} (${response.status})`);
            }

            const data = await response.json();            
            
            this.addMessage(data.message, 'success');
            
            if (data.is_routine) {
                this.addMessage(
                    `**${this.t('routine_maintenance_configured')}**\n` +
                    `• ${this.t('type')}: ${data.recurrence_type}\n` +
                    `• ${this.t('id')}: ${data.maintenance_id || this.t('auto_generated')}\n` +
                    `• ${this.t('will_run_automatically')}\n` +
                    `• ${this.t('uses_internal_bitmasks')}`,
                    'info'
                );
            }
            
            this.updateMaintenanceList();

        } catch (error) {
            console.error("Error creating maintenance:", error);
            this.addMessage(
                `${this.t('error_creating_maintenance')}: ${error.message}`,
                'error'
            );
        } finally {
            this.showLoading(false);
            this.onCancelMaintenance();
        }
    }

    async updateMaintenanceList() {
        try {
            const response = await this.makeRequest('/maintenance/list');
            
            if (!response.ok) {
                console.warn(`Error obteniendo lista de mantenimientos: ${response.status}`);
                return;
            }

            const data = await response.json();
            console.log("Mantenimientos actualizados:", data.maintenances?.length || 0);
            
            const maintenances = data.maintenances || [];
            if (maintenances.length > 0) {
                const routineCount = maintenances.filter(m => m.is_routine).length;
                const oneTimeCount = maintenances.length - routineCount;
                const withTickets = maintenances.filter(m => m.ticket_number).length;
                
                const dailyCount = maintenances.filter(m => m.routine_type === 'daily').length;
                const weeklyCount = maintenances.filter(m => m.routine_type === 'weekly').length;
                const monthlyCount = maintenances.filter(m => m.routine_type === 'monthly').length;
                
                this.addMessage(
                    `**${this.t('maintenance_summary')}:**\n` +
                    `• ${this.t('unique')}: ${oneTimeCount}\n` + 
                    `• ${this.t('routine')}: ${routineCount}\n` +
                    `  - ${this.t('daily')}: ${dailyCount}\n` +
                    `  - ${this.t('weekly')}: ${weeklyCount}\n` +
                    `  - ${this.t('monthly')}: ${monthlyCount}\n` +
                    `• ${this.t('with_tickets')}: ${withTickets}\n` +
                    `• ${this.t('total')}: ${maintenances.length}`, 
                    'info'
                );
            }
        } catch (error) {
            console.error("Error actualizando lista:", error);
        }
    }

    addMessage(message, type) {
        if (!message) return;

        const messages = this._body.querySelector('#ai-messages');
        if (!messages) return;

        const messageDiv = document.createElement('div');
        messageDiv.className = `ai-message ${type}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        let formattedMessage = this.escapeHtml(message).replace(/\n/g, '<br>');
        
        formattedMessage = formattedMessage.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        formattedMessage = formattedMessage.replace(
            /\b(\d{3}-\d{3,6})\b/g,
            '<span class="ticket-highlight">$1</span>'
        );
        
        contentDiv.innerHTML = formattedMessage;
        
        messageDiv.appendChild(contentDiv);
        messages.appendChild(messageDiv);
        
        this.scrollToBottom(messages);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollToBottom(element) {
        if (!element) return;
        
        requestAnimationFrame(() => {
            element.scrollTop = element.scrollHeight;
        });
    }

    showLoading(show, message = 'Processing...') {
        const loading = this._body.querySelector('#ai-loading');
        if (!loading) return;

        if (show) {
            const loadingText = loading.querySelector('span');
            if (loadingText) {
                loadingText.textContent = message;
            }
            loading.style.display = 'flex';
        } else {
            loading.style.display = 'none';
        }
    }

    getRecurrenceTypeLabel(type) {
        const labels = {
            'once': this.t('unique'),
            'daily': this.t('daily'),
            'weekly': this.t('weekly'),
            'monthly': this.t('monthly')
        };
        return labels[type] || type;
    }
    
    formatRecurrenceConfig(type, config) {
        if (!config || typeof config !== 'object') return '';
        
        let info = '';
        
        switch (type) {
            case 'daily':
                info = `${this.t('every')} ${config.every || 1} ${this.t('days')}`;
                if (config.start_time !== undefined) {
                    const hours = Math.floor(config.start_time / 3600);
                    const minutes = Math.floor((config.start_time % 3600) / 60);
                    info += ` ${this.t('at')} ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                }
                break;
                
            case 'weekly': {                
                const dayNames = this.decodeDaysBitmask(config.dayofweek || 1);
                info = `${this.t('every')} ${config.every || 1} ${this.t('weeks')} ${this.t('on')} ${dayNames.join(', ')}`;
                if (config.start_time !== undefined) {
                    const hours = Math.floor(config.start_time / 3600);
                    const minutes = Math.floor((config.start_time % 3600) / 60);
                    info += ` ${this.t('at')} ${hours.toString().padStart(2,'0')}:${minutes.toString().padStart(2,'0')}`;
                }
                break;
            }
                
            case 'monthly':
                if (config.day !== undefined) {
                    info = `${this.t('day')} ${config.day} ${this.t('of_every')} ${config.every || 1} ${this.t('months')}`;
                } else if (config.dayofweek !== undefined) {
                    const dayNames = this.decodeDaysBitmask(config.dayofweek);
                    const weekNames = {1: this.t('first'), 2: this.t('second'), 3: this.t('third'), 4: this.t('fourth'), 5: this.t('last')};
                    const weekName = weekNames[config.every] || this.t('first');
                    info = `${weekName} ${this.t('week')} - ${dayNames.join(', ')} ${this.t('of_each_month')}`;
                }
                
                if (config.start_time !== undefined) {
                    const hours = Math.floor(config.start_time / 3600);
                    const minutes = Math.floor((config.start_time % 3600) / 60);
                    info += ` ${this.t('at')} ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                }
                break;
                
            default:
                info = this.t('custom_configuration');
        }
        
        return info;
    }
    
    decodeDaysBitmask(bitmask) {
        const days = [this.t('monday'), this.t('tuesday'), this.t('wednesday'), this.t('thursday'), this.t('friday'), this.t('saturday'), this.t('sunday')];
        const result = [];
        
        for (let i = 0; i < 7; i++) {
            if (bitmask & (1 << i)) {
                result.push(days[i]);
            }
        }
        
        return result.length > 0 ? result : [this.t('monday')];
    }
    
    decodeMonthsBitmask(bitmask) {
        const months = [this.t('january'), this.t('february'), this.t('march'), this.t('april'), this.t('may'), this.t('june'),
                       this.t('july'), this.t('august'), this.t('september'), this.t('october'), this.t('november'), this.t('december')];
        const result = [];
        
        for (let i = 0; i < 12; i++) {
            if (bitmask & (1 << i)) {
                result.push(months[i]);
            }
        }
        
        return result.length > 0 ? result : [this.t('all_months')];
    }

    showConfirmation(data) {
        const confirmation = this._body.querySelector('#ai-confirmation');
        const details = this._body.querySelector('#maintenance-details');
        
        if (!confirmation || !details) {
            console.error("Elementos de confirmación no encontrados");
            return;
        }

        const isRoutine = data.recurrence_type !== 'once';
        const recurrenceLabel = this.getRecurrenceTypeLabel(data.recurrence_type);
        const hasTicket = data.ticket_number && data.ticket_number.trim();

        let detailsHtml = `<h5>${this.t('maintenance_details')}:</h5><ul>`;

        if (hasTicket) {
            detailsHtml += `<li><strong>${this.t('ticket')}:</strong> ${this.escapeHtml(data.ticket_number)}</li>`;
        }

        detailsHtml += `<li><strong>${this.t('type')}:</strong> ${recurrenceLabel}${isRoutine ? ` (${this.t('routine')})` : ''}</li>`;

        if (isRoutine && data.recurrence_config) {
            const configInfo = this.formatRecurrenceConfig(data.recurrence_type, data.recurrence_config);
            if (configInfo) {
                detailsHtml += `<li><strong>${this.t('recurrence')}:</strong> ${this.escapeHtml(configInfo)}</li>`;
            }
            
            detailsHtml += `<li><strong>${this.t('technical_configuration')}:</strong> `;
            if (data.recurrence_type === 'weekly') {
                detailsHtml += `${this.t('days_bitmask')}: ${data.recurrence_config.dayofweek || 1}`;
            } else if (data.recurrence_type === 'monthly') {
                if (data.recurrence_config.day !== undefined) {
                    detailsHtml += `${this.t('day')} ${data.recurrence_config.day} ${this.t('of_month')}`;
                } else if (data.recurrence_config.dayofweek !== undefined) {
                    detailsHtml += `${this.t('days_bitmask')}: ${data.recurrence_config.dayofweek}, ${this.t('week')}: ${data.recurrence_config.every || 1}`;
                }
                
                if (data.recurrence_config.month !== undefined && data.recurrence_config.month !== 4095) {
                    const monthNames = this.decodeMonthsBitmask(data.recurrence_config.month);
                    detailsHtml += `, ${this.t('months')}: ${monthNames.join(', ')} (bitmask: ${data.recurrence_config.month})`;
                }
            } else if (data.recurrence_type === 'daily') {
                detailsHtml += `${this.t('every')} ${data.recurrence_config.every || 1} ${this.t('days')}`;
            }
            detailsHtml += `</li>`;
        }

        if (data.found_hosts && data.found_hosts.length > 0) {
            const hostNames = data.found_hosts.map(h => h.name || h.host).join(', ');
            detailsHtml += `<li><strong>${this.t('servers')} (${data.found_hosts.length}):</strong> ${this.escapeHtml(hostNames)}</li>`;
        }

        if (data.found_groups && data.found_groups.length > 0) {
            const groupNames = data.found_groups.map(g => g.name).join(', ');
            detailsHtml += `<li><strong>${this.t('groups')} (${data.found_groups.length}):</strong> ${this.escapeHtml(groupNames)}</li>`;
        }

        if (data.trigger_tags && data.trigger_tags.length > 0) {
            const tagStrings = data.trigger_tags.map(t => `${t.tag}: ${t.value}`).join(', ');
            detailsHtml += `<li><strong>${this.t('trigger_tags')}:</strong> ${this.escapeHtml(tagStrings)}</li>`;
        }

        detailsHtml += `<li><strong>${this.t('period')}:</strong> ${this.escapeHtml(data.start_time)} - ${this.escapeHtml(data.end_time)}</li>`;
        
        const previewName = this.generateMaintenanceName(data);
        detailsHtml += `<li><strong>${this.t('name')}:</strong> ${this.escapeHtml(previewName)}</li>`;
        
        detailsHtml += '</ul>';

        if (isRoutine) {
            detailsHtml += `<div class="routine-warning">`;
            detailsHtml += `<strong>${this.t('routine_maintenance')}:</strong><br>`;
            detailsHtml += this.t('routine_warning_text');
            detailsHtml += `</div>`;
        }

        if (!hasTicket) {
            detailsHtml += `<div class="no-ticket-warning">`;
            detailsHtml += `<strong>${this.t('no_ticket')}:</strong><br>`;
            detailsHtml += this.t('no_ticket_warning_text');
            detailsHtml += `</div>`;
        }

        details.innerHTML = detailsHtml;
        confirmation.style.display = 'flex';
        
        const confirmButton = confirmation.querySelector('#confirm-maintenance');
        if (confirmButton) {
            setTimeout(() => confirmButton.focus(), 100);
        }
    }

    generateMaintenanceName(data) {
        if (!data) return this.t('ai_maintenance_no_data');
        
        const ticket_number = data.ticket_number && data.ticket_number.trim();
        const recurrence_type = data.recurrence_type || 'once';
        
        let base_prefix;
        if (recurrence_type === 'once') {
            base_prefix = this.t('ai_maintenance');
        } else {
            base_prefix = this.t('ai_routine_maintenance');
        }
        
        if (ticket_number) {
            return `${base_prefix}: ${ticket_number}`;
        }
        
        const maintenance_name_parts = [];
        
        if (data.found_hosts && data.found_hosts.length > 0) {
            const hostNames = data.found_hosts.map(h => h.name || h.host).slice(0, 3);
            maintenance_name_parts.push(...hostNames);
            if (data.found_hosts.length > 3) {
                maintenance_name_parts.push(`${this.t('and')} ${data.found_hosts.length - 3} ${this.t('more_hosts')}`);
            }
        }
        
        if (data.found_groups && data.found_groups.length > 0) {
            const groupNames = data.found_groups.map(g => `${this.t('group')} ${g.name}`).slice(0, 2);
            maintenance_name_parts.push(...groupNames);
            if (data.found_groups.length > 2) {
                maintenance_name_parts.push(`${this.t('and')} ${data.found_groups.length - 2} ${this.t('more_groups')}`);
            }
        }
        
        if (maintenance_name_parts.length > 0) {
            return `${base_prefix}: ${maintenance_name_parts.join(', ')}`;
        } else {
            return `${base_prefix}: ${this.t('various_resources')}`;
        }
    }

    onCancelMaintenance() {
        const confirmation = this._body.querySelector('#ai-confirmation');
        if (confirmation) {
            confirmation.style.display = 'none';
        }
        this.current_parsed_data = null;
        
        const input = this._body.querySelector('#ai-input');
        if (input) {
            setTimeout(() => input.focus(), 100);
        }
    }

    destroy() {
        if (this.currentRequest) {
            this.currentRequest.abort();
        }
        
        if (this.retryTimeout) {
            clearTimeout(this.retryTimeout);
        }
        
        super.destroy?.();
    }
}

function toggleWelcomeDetails() {
    const details = document.getElementById('welcome-details');
    const toggle = document.querySelector('.welcome-toggle');
    
    if (!details || !toggle) return;
    
    if (details.style.display === 'none') {
        details.style.display = 'block';
        details.classList.add('show');
        toggle.classList.add('expanded');
    } else {
        details.style.display = 'none';
        details.classList.remove('show');
        toggle.classList.remove('expanded');
    }
}