class WidgetAIMaintenance extends CWidget {
    
    onInitialize() {
        super.onInitialize();
        this.api_url = '';
        this.current_parsed_data = null;
        this.user_info = null;
        this.templates = null;
        this.request_timeout = 60000; // 60 segundos
        this.retry_count = 0;
        this.max_retries = 2;
    }

    processUpdateResponse(response) {
        this.api_url = response.fields_values?.api_url || 'http://localhost:5005';
        
        // Procesar información del usuario correctamente
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
        this.setupEventListeners();
        this.loadMaintenanceTemplates();
        this.checkBackendConnection();
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
                // Mostrar información de funciones disponibles
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
                `Estado del Sistema:\n` +
                `No se pudo verificar la conexión con el backend.\n` +
                `URL: ${this.api_url}\n` +
                `Las funciones pueden estar limitadas hasta que se restablezca la conexión.`,
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
            input.placeholder = 'Describe el mantenimiento que necesitas...';
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
                console.log("Plantillas cargadas:", Object.keys(this.templates || {}).length);
            } else {
                console.warn(`Error cargando plantillas: ${response.status}`);
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.warn("Timeout cargando plantillas");
            } else {
                console.error("Error cargando plantillas:", error);
            }
        }
    }

    showTemplates() {
        if (!this.templates) {
            this.addMessage(
                "Las plantillas no están disponibles en este momento.\n\n" +
                "**Ejemplos de mantenimientos rutinarios:**\n" +
                "• **Diario:** 'backup diario a las 2 AM con ticket 100-178306'\n" +
                "• **Semanal:** 'mantenimiento domingos de 1-3 AM ticket 200-8341'\n" +
                "• **Mensual día específico:** 'limpieza día 5 cada mes con ticket 500-43116'\n" +
                "• **Mensual día de semana:** 'actualización primer domingo cada mes ticket 600-78901'",
                'info'
            );
            return;
        }
        
        let templateMsg = "**Plantillas de Mantenimientos Rutinarios**\n\n";
        
        Object.entries(this.templates).forEach(([type, info]) => {
            const icon = type === 'daily' ? 'Diario' : type === 'weekly' ? 'Semanal' : 'Mensual';
            templateMsg += `${icon} **${info.name}**\n`;
            templateMsg += `${info.description}\n`;
            templateMsg += "**Ejemplos:**\n";
            info.examples.forEach(example => {
                templateMsg += `• "${example}"\n`;
            });
            templateMsg += "\n";
        });
        
        templateMsg += "**Consejos para mantenimientos rutinarios:**\n";
        templateMsg += "• **Diarios:** 'cada día', 'todos los días', 'diariamente'\n";
        templateMsg += "• **Semanales:** 'cada lunes', 'todos los domingos', 'semanalmente'\n";
        templateMsg += "• **Mensuales (día):** 'día 5 cada mes', 'el día 15', 'día 1 mensualmente'\n";
        templateMsg += "• **Mensuales (semana):** 'primer domingo', 'segunda semana', 'último viernes'\n";
        templateMsg += "• **Tickets:** Incluye siempre números como '100-178306', '200-8341'\n";
        templateMsg += "\n**Tip:** Los mantenimientos rutinarios usan bitmasks internos para una programación precisa.";
        
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

        // Validación de longitud
        if (message.length < 5) {
            this.addMessage("El mensaje es muy corto. Describe qué tipo de mantenimiento necesitas crear.", 'warning');
            this.highlightInput(input);
            return;
        }

        if (message.length > 1000) {
            this.addMessage("El mensaje es muy largo. Por favor, sé más conciso.", 'warning');
            return;
        }

        // Añadir animación de "pensando" al avatar
        const avatar = this._body.querySelector('.ai-avatar');
        if (avatar) {
            avatar.classList.add('thinking');
        }

        // Limpiar input y mostrar mensaje del usuario
        input.value = '';
        input.style.height = 'auto';
        this.addMessage(message, 'user');
        this.showLoading(true, 'Analizando solicitud...');

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
                throw new Error(errorData.message || `Error del servidor (${response.status})`);
            }

            const data = await response.json();
            this.handleInteractiveResponse(data);
            this.retry_count = 0;

        } catch (error) {
            console.error("Error en onSendMessage:", error);
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
                throw new Error('La solicitud tardó demasiado tiempo. Intenta de nuevo.');
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
                `Error de conexión (intento ${this.retry_count}/${this.max_retries + 1}). Reintentando...`,
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
                ? "No se pudo conectar con el backend. Verifica que el servicio esté funcionando."
                : `Error: ${error.message}`;
            
            this.addMessage(`${errorMessage}`, 'error');
        }
    }

    handleInteractiveResponse(data) {
        if (!data || typeof data !== 'object') {
            this.addMessage("Respuesta inválida del servidor", 'error');
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
                    data.message || 'Recibí una respuesta que no pude procesar completamente.', 
                    'assistant'
                );
                break;
        }
    }

    showDetectedInfo(detectedInfo) {
        let infoMsg = "\n**Información detectada:**\n";
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
            message = `**Análisis completado**\n\n`;
        }
        
        // Mostrar información de ticket si está presente
        if (data.ticket_number && data.ticket_number.trim()) {
            message += `**Ticket:** ${data.ticket_number}\n\n`;
        }
        
        // Mostrar tipo de mantenimiento
        const recurrenceLabel = this.getRecurrenceTypeLabel(data.recurrence_type);
        const isRoutine = data.recurrence_type !== 'once';
        
        const typeIcon = isRoutine ? 'Rutinario' : 'Único';
        message += `**Tipo:** ${recurrenceLabel} (${typeIcon})\n\n`;
        
        // Configuración de recurrencia si aplica
        if (isRoutine && data.recurrence_config) {
            const configInfo = this.formatRecurrenceConfig(data.recurrence_type, data.recurrence_config);
            if (configInfo) {
                message += `**Configuración:** ${configInfo}\n\n`;
            }
        }
        
        // Mostrar resumen de búsqueda si está disponible
        if (data.search_summary) {
            const summary = data.search_summary;
            message += `**Resumen:**\n`;
            message += `• Hosts encontrados: ${summary.total_hosts_found}\n`;
            message += `• Grupos encontrados: ${summary.total_groups_found}\n`;
            if (summary.hosts_by_tags > 0) {
                message += `• Hosts por tags: ${summary.hosts_by_tags}\n`;
            }
            if (summary.has_ticket) {
                message += `• Con ticket: Sí\n`;
            }
            if (summary.is_routine) {
                message += `• Mantenimiento rutinario: Sí\n`;
            }
            message += '\n';
        }
        
        // Mostrar recursos encontrados
        message = this.appendResourcesInfo(message, data);
        
        // Mostrar horario
        if (data.start_time && data.end_time) {
            message += `**Período:**\n`;
            message += `• Desde: ${data.start_time}\n`;
            message += `• Hasta: ${data.end_time}\n\n`;
        }
        
        if (data.description && data.description.trim()) {
            message += `**Descripción:** ${data.description}\n\n`;
        }

        if (data.confidence && data.confidence > 0) {
            message += `**Confianza:** ${data.confidence}%`;
        }

        this.addMessage(message, 'assistant');

        // Mostrar confirmación si hay recursos válidos
        const hasValidTargets = this.hasValidTargets(data);
        
        if (hasValidTargets) {
            this.showConfirmation(data);
        } else {
            this.addMessage('No se encontraron hosts ni grupos válidos para crear el mantenimiento', 'warning');
        }
    }
    
    appendResourcesInfo(baseMessage, data) {
        let message = baseMessage;

        // Hosts encontrados
        if (data.found_hosts && data.found_hosts.length > 0) {
            message += `**Servidores encontrados (${data.found_hosts.length}):**\n`;
            data.found_hosts.forEach(host => {
                const displayName = host.name || host.host;
                message += `• ${displayName} (${host.host})\n`;
            });
            message += '\n';
        }

        // Grupos encontrados
        if (data.found_groups && data.found_groups.length > 0) {
            message += `**Grupos encontrados (${data.found_groups.length}):**\n`;
            data.found_groups.forEach(group => {
                message += `• ${group.name}\n`;
            });
            message += '\n';
        }

        // Tags de triggers
        if (data.trigger_tags && data.trigger_tags.length > 0) {
            message += `**Tags de triggers:**\n`;
            data.trigger_tags.forEach(tag => {
                message += `• ${tag.tag}: ${tag.value}\n`;
            });
            message += '\n';
        }

        // Recursos no encontrados
        if (data.missing_hosts && data.missing_hosts.length > 0) {
            message += `**Servidores NO encontrados:**\n`;
            data.missing_hosts.forEach(host => {
                message += `• ${host}\n`;
            });
            message += '\n';
        }

        if (data.missing_groups && data.missing_groups.length > 0) {
            message += `**Grupos NO encontrados:**\n`;
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
        
        let exampleMsg = "\n**Ejemplos:**\n\n";
        
        examples.forEach((example, index) => {
            exampleMsg += `${index + 1}. **${example.title}**\n`;
            exampleMsg += `   "${example.example}"\n\n`;
        });
        
        this.addMessage(exampleMsg, 'info');
    }

    async onConfirmMaintenance() {
        if (!this.current_parsed_data) {
            this.addMessage("No hay datos de mantenimiento para confirmar", 'error');
            return;
        }
        
        // Verificar que hay al menos hosts o grupos
        const hasValidTargets = this.hasValidTargets(this.current_parsed_data);
        
        if (!hasValidTargets) {
            this.addMessage('No hay hosts ni grupos válidos para crear el mantenimiento', 'error');
            return;
        }
        
        this.showLoading(true, 'Creando mantenimiento...');
        
        try {
            // Preparar datos para enviar
            const maintenanceData = {
                start_time: this.current_parsed_data.start_time,
                end_time: this.current_parsed_data.end_time,
                description: this.current_parsed_data.description || '',
                trigger_tags: this.current_parsed_data.trigger_tags || [],
                recurrence_type: this.current_parsed_data.recurrence_type || 'once',
                ticket_number: this.current_parsed_data.ticket_number || '',
                user_info: this.user_info
            };

            // Agregar configuración de recurrencia si existe
            if (this.current_parsed_data.recurrence_config) {
                maintenanceData.recurrence_config = this.current_parsed_data.recurrence_config;
            }

            // Agregar hosts si existen
            if (this.current_parsed_data.found_hosts && this.current_parsed_data.found_hosts.length > 0) {
                maintenanceData.hosts = this.current_parsed_data.found_hosts.map(h => h.host);
            }

            // Agregar grupos si existen
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
                throw new Error(errorData.message || `Error del servidor (${response.status})`);
            }

            const data = await response.json();            
            
            this.addMessage(data.message, 'success');
            
            // Mostrar información adicional para mantenimientos rutinarios
            if (data.is_routine) {
                this.addMessage(
                    `**Mantenimiento Rutinario Configurado**\n` +
                    `• Tipo: ${data.recurrence_type}\n` +
                    `• ID: ${data.maintenance_id || 'Generado automáticamente'}\n` +
                    `• Se ejecutará automáticamente según la configuración\n` +
                    `• Usa bitmasks internos para programación precisa`,
                    'info'
                );
            }
            
            // Actualizar lista de mantenimientos
            this.updateMaintenanceList();

        } catch (error) {
            console.error("Error creando mantenimiento:", error);
            this.addMessage(
                `Error al crear mantenimiento: ${error.message}`,
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
            
            // Mostrar estadísticas de mantenimientos
            const maintenances = data.maintenances || [];
            if (maintenances.length > 0) {
                const routineCount = maintenances.filter(m => m.is_routine).length;
                const oneTimeCount = maintenances.length - routineCount;
                const withTickets = maintenances.filter(m => m.ticket_number).length;
                
                // Contar por tipos de rutinarios
                const dailyCount = maintenances.filter(m => m.routine_type === 'daily').length;
                const weeklyCount = maintenances.filter(m => m.routine_type === 'weekly').length;
                const monthlyCount = maintenances.filter(m => m.routine_type === 'monthly').length;
                
                this.addMessage(
                    `**Resumen de mantenimientos:**\n` +
                    `• Únicos: ${oneTimeCount}\n` + 
                    `• Rutinarios: ${routineCount}\n` +
                    `  - Diarios: ${dailyCount}\n` +
                    `  - Semanales: ${weeklyCount}\n` +
                    `  - Mensuales: ${monthlyCount}\n` +
                    `• Con tickets: ${withTickets}\n` +
                    `• Total: ${maintenances.length}`, 
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
        
        // Preservar saltos de línea y formato básico de markdown
        let formattedMessage = this.escapeHtml(message).replace(/\n/g, '<br>');
        
        // Convertir texto en negrita **texto** a <strong>
        formattedMessage = formattedMessage.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Destacar tickets en el texto
        formattedMessage = formattedMessage.replace(
            /\b(\d{3}-\d{3,6})\b/g,
            '<span class="ticket-highlight">$1</span>'
        );
        
        contentDiv.innerHTML = formattedMessage;
        
        messageDiv.appendChild(contentDiv);
        messages.appendChild(messageDiv);
        
        // Scroll suave al final
        this.scrollToBottom(messages);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollToBottom(element) {
        if (!element) return;
        
        // Usar requestAnimationFrame para mejor performance
        requestAnimationFrame(() => {
            element.scrollTop = element.scrollHeight;
        });
    }

    showLoading(show, message = 'Procesando...') {
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
            'once': 'Único',
            'daily': 'Diario',
            'weekly': 'Semanal',
            'monthly': 'Mensual'
        };
        return labels[type] || type;
    }
    
    formatRecurrenceConfig(type, config) {
        if (!config || typeof config !== 'object') return '';
        
        let info = '';
        
        switch (type) {
            case 'daily':
                info = `Cada ${config.every || 1} día(s)`;
                if (config.start_time !== undefined) {
                    const hours = Math.floor(config.start_time / 3600);
                    const minutes = Math.floor((config.start_time % 3600) / 60);
                    info += ` a las ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                }
                break;
                
            case 'weekly': {                
                const dayNames = this.decodeDaysBitmask(config.dayofweek || 1);
                info = `Cada ${config.every || 1} semana(s) los ${dayNames.join(', ')}`;
                if (config.start_time !== undefined) {
                    const hours = Math.floor(config.start_time / 3600);
                    const minutes = Math.floor((config.start_time % 3600) / 60);
                    info += ` a las ${hours.toString().padStart(2,'0')}:${minutes.toString().padStart(2,'0')}`;
                }
                break;
            }
                
            case 'monthly':
                if (config.day !== undefined) {
                    info = `El día ${config.day} de cada ${config.every || 1} mes(es)`;
                } else if (config.dayofweek !== undefined) {
                    const dayNames = this.decodeDaysBitmask(config.dayofweek);
                    const weekNames = {1: 'primera', 2: 'segunda', 3: 'tercera', 4: 'cuarta', 5: 'última'};
                    const weekName = weekNames[config.every] || 'primera';
                    info = `${weekName} semana - ${dayNames.join(', ')} de cada mes`;
                }
                
                if (config.start_time !== undefined) {
                    const hours = Math.floor(config.start_time / 3600);
                    const minutes = Math.floor((config.start_time % 3600) / 60);
                    info += ` a las ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                }
                break;
                
            default:
                info = 'Configuración personalizada';
        }
        
        return info;
    }
    
    decodeDaysBitmask(bitmask) {
        const days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
        const result = [];
        
        for (let i = 0; i < 7; i++) {
            if (bitmask & (1 << i)) {
                result.push(days[i]);
            }
        }
        
        return result.length > 0 ? result : ['Lunes'];
    }
    
    decodeMonthsBitmask(bitmask) {
        const months = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                       'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
        const result = [];
        
        for (let i = 0; i < 12; i++) {
            if (bitmask & (1 << i)) {
                result.push(months[i]);
            }
        }
        
        return result.length > 0 ? result : ['Todos los meses'];
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

        let detailsHtml = '<h5>Detalles del Mantenimiento:</h5><ul>';

        // Mostrar ticket si está presente
        if (hasTicket) {
            detailsHtml += `<li><strong>Ticket:</strong> ${this.escapeHtml(data.ticket_number)}</li>`;
        }

        // Tipo de mantenimiento
        detailsHtml += `<li><strong>Tipo:</strong> ${recurrenceLabel}${isRoutine ? ' (Rutinario)' : ''}</li>`;

        // Configuración de recurrencia si aplica
        if (isRoutine && data.recurrence_config) {
            const configInfo = this.formatRecurrenceConfig(data.recurrence_type, data.recurrence_config);
            if (configInfo) {
                detailsHtml += `<li><strong>Recurrencia:</strong> ${this.escapeHtml(configInfo)}</li>`;
            }
            
            // Mostrar detalles técnicos para rutinarios
            detailsHtml += `<li><strong>Configuración técnica:</strong> `;
            if (data.recurrence_type === 'weekly') {
                detailsHtml += `Bitmask días: ${data.recurrence_config.dayofweek || 1}`;
            } else if (data.recurrence_type === 'monthly') {
                if (data.recurrence_config.day !== undefined) {
                    detailsHtml += `Día ${data.recurrence_config.day} del mes`;
                } else if (data.recurrence_config.dayofweek !== undefined) {
                    detailsHtml += `Bitmask días: ${data.recurrence_config.dayofweek}, Semana: ${data.recurrence_config.every || 1}`;
                }
                
                // Mostrar bitmask de meses si está presente
                if (data.recurrence_config.month !== undefined && data.recurrence_config.month !== 4095) {
                    const monthNames = this.decodeMonthsBitmask(data.recurrence_config.month);
                    detailsHtml += `, Meses: ${monthNames.join(', ')} (bitmask: ${data.recurrence_config.month})`;
                }
            } else if (data.recurrence_type === 'daily') {
                detailsHtml += `Cada ${data.recurrence_config.every || 1} día(s)`;
            }
            detailsHtml += `</li>`;
        }

        // Mostrar servidores si los hay
        if (data.found_hosts && data.found_hosts.length > 0) {
            const hostNames = data.found_hosts.map(h => h.name || h.host).join(', ');
            detailsHtml += `<li><strong>Servidores (${data.found_hosts.length}):</strong> ${this.escapeHtml(hostNames)}</li>`;
        }

        // Mostrar grupos si los hay
        if (data.found_groups && data.found_groups.length > 0) {
            const groupNames = data.found_groups.map(g => g.name).join(', ');
            detailsHtml += `<li><strong>Grupos (${data.found_groups.length}):</strong> ${this.escapeHtml(groupNames)}</li>`;
        }

        // Mostrar tags de triggers si los hay
        if (data.trigger_tags && data.trigger_tags.length > 0) {
            const tagStrings = data.trigger_tags.map(t => `${t.tag}: ${t.value}`).join(', ');
            detailsHtml += `<li><strong>Tags de triggers:</strong> ${this.escapeHtml(tagStrings)}</li>`;
        }

        detailsHtml += `<li><strong>Período:</strong> ${this.escapeHtml(data.start_time)} - ${this.escapeHtml(data.end_time)}</li>`;
        
        // Mostrar nombre que se generará
        const previewName = this.generateMaintenanceName(data);
        detailsHtml += `<li><strong>Nombre:</strong> ${this.escapeHtml(previewName)}</li>`;
        
        detailsHtml += '</ul>';

        // Advertencia para mantenimientos rutinarios
        if (isRoutine) {
            detailsHtml += '<div class="routine-warning">';
            detailsHtml += '<strong>Mantenimiento Rutinario:</strong><br>';
            detailsHtml += 'Este mantenimiento se repetirá automáticamente según la configuración especificada. ';
            detailsHtml += 'Usa bitmasks internos para programación precisa en Zabbix. ';
            detailsHtml += 'Revisa cuidadosamente los horarios y la frecuencia antes de confirmar.';
            detailsHtml += '</div>';
        }

        // Advertencia si no hay ticket
        if (!hasTicket) {
            detailsHtml += '<div class="no-ticket-warning">';
            detailsHtml += '<strong>Sin Ticket:</strong><br>';
            detailsHtml += 'Se usará el nombre estándar. Para incluir un ticket en futuras solicitudes, ';
            detailsHtml += 'menciónalo en el mensaje (ej: "ticket 100-178306").';
            detailsHtml += '</div>';
        }

        details.innerHTML = detailsHtml;
        confirmation.style.display = 'flex';
        
        // Enfocar el primer botón para accesibilidad
        const confirmButton = confirmation.querySelector('#confirm-maintenance');
        if (confirmButton) {
            setTimeout(() => confirmButton.focus(), 100);
        }
    }

    generateMaintenanceName(data) {
        /**
         * Genera el nombre del mantenimiento para mostrar en la vista previa
         * Replica la lógica del backend
         */
        if (!data) return "AI Maintenance: Sin datos";
        
        const ticket_number = data.ticket_number && data.ticket_number.trim();
        const recurrence_type = data.recurrence_type || 'once';
        
        // Prefijo base según tipo de mantenimiento
        let base_prefix;
        if (recurrence_type === 'once') {
            base_prefix = 'AI Maintenance';
        } else {
            base_prefix = 'AI Maintenance Rutinario';
        }
        
        // Si hay ticket, usarlo como nombre principal
        if (ticket_number) {
            return `${base_prefix}: ${ticket_number}`;
        }
        
        // Si no hay ticket, usar el sistema actual (nombres de recursos)
        const maintenance_name_parts = [];
        
        if (data.found_hosts && data.found_hosts.length > 0) {
            const hostNames = data.found_hosts.map(h => h.name || h.host).slice(0, 3);
            maintenance_name_parts.push(...hostNames);
            if (data.found_hosts.length > 3) {
                maintenance_name_parts.push(`y ${data.found_hosts.length - 3} hosts más`);
            }
        }
        
        if (data.found_groups && data.found_groups.length > 0) {
            const groupNames = data.found_groups.map(g => `Grupo ${g.name}`).slice(0, 2);
            maintenance_name_parts.push(...groupNames);
            if (data.found_groups.length > 2) {
                maintenance_name_parts.push(`y ${data.found_groups.length - 2} grupos más`);
            }
        }
        
        if (maintenance_name_parts.length > 0) {
            return `${base_prefix}: ${maintenance_name_parts.join(', ')}`;
        } else {
            return `${base_prefix}: Recursos varios`;
        }
    }

    onCancelMaintenance() {
        const confirmation = this._body.querySelector('#ai-confirmation');
        if (confirmation) {
            confirmation.style.display = 'none';
        }
        this.current_parsed_data = null;
        
        // Enfocar de vuelta al input para mejor UX
        const input = this._body.querySelector('#ai-input');
        if (input) {
            setTimeout(() => input.focus(), 100);
        }
    }

    // Método para limpiar recursos cuando el widget se destruye
    destroy() {
        // Cancelar cualquier solicitud pendiente
        if (this.currentRequest) {
            this.currentRequest.abort();
        }
        
        // Limpiar timeouts
        if (this.retryTimeout) {
            clearTimeout(this.retryTimeout);
        }
        
        super.destroy?.();
    }
}