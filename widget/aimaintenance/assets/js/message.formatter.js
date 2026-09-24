/**
 * message.formatter.js — Message formatting + human-readable maintenance preview.
 *
 * Responsibilities (Req 22.4, 24.4):
 *   - Turn raw text into safe HTML (escaping + minimal markdown + ticket highlight).
 *   - Decode day/month bitmasks to human-readable names.
 *   - Build a human-readable recurrence configuration string.
 *   - Build the maintenance confirmation details and a readable preview.
 *   - Replicate the backend's maintenance-name generation for the preview.
 *
 * This module is PURE with respect to the DOM: it returns strings only and never
 * touches document/window state. Rendering belongs to ui.renderer.js and HTTP to
 * http.client.js. Translatable labels are resolved via an injected translate
 * function `t` (Zabbix JS i18n, Req 33.2); it falls back to identity when absent.
 */
class AIMaintenanceMessageFormatter {
    /**
     * @param {Object} [options]
     * @param {Function} [options.t]  Translation function t(key) -> string (Req 33.2).
     */
    constructor(options = {}) {
        this.t = typeof options.t === 'function' ? options.t : (s) => s;
    }

    /**
     * Escape HTML special characters. Pure string transform (no DOM required),
     * safe to run under Node for syntax/logic checks.
     */
    escapeHtml(text) {
        if (text == null) {
            return '';
        }
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Format a chat message body: escape, preserve newlines, apply minimal
     * markdown (**bold**) and highlight ticket identifiers of ANY nomenclature.
     */
    formatMessage(message) {
        let formatted = this.escapeHtml(message).replace(/\n/g, '<br>');
        formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        formatted = this.highlightTickets(formatted);
        return formatted;
    }

    /**
     * Highlight ticket identifiers of ANY nomenclature, mirroring the backend
     * fallback (core/domain.py). Tickets have no single mandatory format
     * (INC0012345, JIRA-4521, CHG-2024-001, #88213, REQ-99, 100-178306, ...).
     *
     * Runs on ALREADY-ESCAPED HTML (so it never re-escapes and does not touch the
     * markup produced above). Two shapes are recognized, conservatively, to avoid
     * wrapping every number/word or clock times like 22:00 / 22:00-23:00:
     *   1. label-anchored: an optional `ticket:` / `ticket` / `#` prefix followed
     *      by an alnum token with optional `-` `_` `.` separators (>=1 digit,
     *      >=3 chars) — only the identifier (not the label) is wrapped;
     *   2. bare: an UPPERCASE alphanumeric id with >=1 digit (INC0012345,
     *      JIRA-4521, REQ-99) OR a numeric hyphenated id (100-178306). Lowercase
     *      hostnames (srv-web01) and plain numbers are intentionally left alone.
     * The `ticket-highlight` span output is preserved for both shapes.
     */
    highlightTickets(html) {
        const wrap = (id) => `<span class="ticket-highlight">${id}</span>`;

        // 1) Label-anchored (case-insensitive). Keep the label, wrap the id.
        //    Boundaries reject a preceding word char / ':' and a trailing ':'.
        let out = html.replace(
            /(^|[^A-Za-z0-9:._-])(ticket\s*[:#]?\s*|#)([A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*)(?![A-Za-z0-9:])/gi,
            (match, lead, label, id) => {
                if (!/[0-9]/.test(id) || id.length < 3) {
                    return match; // require a digit and >=3 chars
                }
                return `${lead}${label}${wrap(id)}`;
            }
        );

        // 2) Bare, unambiguous ticket shapes (case-sensitive). Skip anything that
        //    is already inside a highlight span from step 1.
        out = out.replace(
            /(^|[^A-Za-z0-9:._>-])((?:[A-Z0-9]+(?:[._-][A-Z0-9]+)*|[0-9]{2,}-[0-9]{2,}))(?![A-Za-z0-9:])/g,
            (match, lead, id) => {
                const hasDigit = /[0-9]/.test(id);
                const isNumericHyphen = /^[0-9]{2,}-[0-9]{2,}$/.test(id);
                const isUpperAlnum = /[A-Z]/.test(id) && hasDigit;
                if (id.length < 3 || (!isNumericHyphen && !isUpperAlnum)) {
                    return match;
                }
                return `${lead}${wrap(id)}`;
            }
        );

        return out;
    }

    /** Bitmask (Zabbix dayofweek) -> list of localized day names. */
    decodeDaysBitmask(bitmask) {
        const keys = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
        const result = [];
        for (let i = 0; i < 7; i++) {
            if (bitmask & (1 << i)) {
                result.push(this.t(keys[i]));
            }
        }
        return result.length > 0 ? result : [this.t('Monday')];
    }

    /** Bitmask (Zabbix month) -> list of localized month names. */
    decodeMonthsBitmask(bitmask) {
        const keys = ['January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'];
        const result = [];
        for (let i = 0; i < 12; i++) {
            if (bitmask & (1 << i)) {
                result.push(this.t(keys[i]));
            }
        }
        return result.length > 0 ? result : [this.t('All months')];
    }

    /** Human-readable label for a recurrence type. */
    getRecurrenceTypeLabel(type) {
        const labels = {
            once: this.t('Single'),
            daily: this.t('Daily'),
            weekly: this.t('Weekly'),
            monthly: this.t('Monthly')
        };
        return labels[type] || type;
    }

    _formatTimeOfDay(secondsFromMidnight) {
        const hours = Math.floor(secondsFromMidnight / 3600);
        const minutes = Math.floor((secondsFromMidnight % 3600) / 60);
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
    }

    /**
     * Build a human-readable recurrence configuration string.
     * Returns '' when there is nothing meaningful to show.
     */
    formatRecurrenceConfig(type, config) {
        if (!config || typeof config !== 'object') {
            return '';
        }

        let info = '';
        switch (type) {
            case 'daily':
                info = `${this.t('Every')} ${config.every || 1} ${this.t('day(s)')}`;
                if (config.start_time !== undefined) {
                    info += ` ${this.t('at')} ${this._formatTimeOfDay(config.start_time)}`;
                }
                break;

            case 'weekly': {
                const dayNames = this.decodeDaysBitmask(config.dayofweek || 1);
                info = `${this.t('Every')} ${config.every || 1} ${this.t('week(s)')} ${this.t('on')} ${dayNames.join(', ')}`;
                if (config.start_time !== undefined) {
                    info += ` ${this.t('at')} ${this._formatTimeOfDay(config.start_time)}`;
                }
                break;
            }

            case 'monthly':
                if (config.day !== undefined) {
                    info = `${this.t('Day')} ${config.day} ${this.t('of every')} ${config.every || 1} ${this.t('month(s)')}`;
                } else if (config.dayofweek !== undefined) {
                    const dayNames = this.decodeDaysBitmask(config.dayofweek);
                    const weekNames = {
                        1: this.t('first'),
                        2: this.t('second'),
                        3: this.t('third'),
                        4: this.t('fourth'),
                        5: this.t('last')
                    };
                    const weekName = weekNames[config.every] || this.t('first');
                    info = `${weekName} ${this.t('week')} - ${dayNames.join(', ')} ${this.t('of every month')}`;
                }
                if (config.start_time !== undefined) {
                    info += ` ${this.t('at')} ${this._formatTimeOfDay(config.start_time)}`;
                }
                break;

            default:
                info = this.t('Custom configuration');
        }
        return info;
    }

    /** Does the parsed data have valid hosts/groups to target? */
    hasValidTargets(data) {
        return (data && data.found_hosts && data.found_hosts.length > 0) ||
            (data && data.found_groups && data.found_groups.length > 0);
    }

    /**
     * Replicate the backend maintenance-name generation for the preview.
     * Preserves the existing behavior (ticket as principal component).
     */
    generateMaintenanceName(data) {
        if (!data) {
            return `AI Maintenance: ${this.t('No data')}`;
        }

        const ticketNumber = data.ticket_number && data.ticket_number.trim();
        const recurrenceType = data.recurrence_type || 'once';
        const basePrefix = recurrenceType === 'once'
            ? 'AI Maintenance'
            : `AI Maintenance ${this.t('Routine')}`;

        if (ticketNumber) {
            return `${basePrefix}: ${ticketNumber}`;
        }

        const parts = [];
        if (data.found_hosts && data.found_hosts.length > 0) {
            const hostNames = data.found_hosts.map((h) => h.name || h.host).slice(0, 3);
            parts.push(...hostNames);
            if (data.found_hosts.length > 3) {
                parts.push(`${this.t('and')} ${data.found_hosts.length - 3} ${this.t('more hosts')}`);
            }
        }
        if (data.found_groups && data.found_groups.length > 0) {
            const groupNames = data.found_groups.map((g) => `${this.t('Group')} ${g.name}`).slice(0, 2);
            parts.push(...groupNames);
            if (data.found_groups.length > 2) {
                parts.push(`${this.t('and')} ${data.found_groups.length - 2} ${this.t('more groups')}`);
            }
        }

        if (parts.length > 0) {
            return `${basePrefix}: ${parts.join(', ')}`;
        }
        return `${basePrefix}: ${this.t('Various resources')}`;
    }

    /**
     * Build the analysis summary message shown after a maintenance_request.
     * Returns a plain text (markdown) string; rendering/escaping happens later.
     */
    buildMaintenanceSummary(data) {
        if (!data) {
            return '';
        }

        let message = '';
        if (data.message && data.message.trim()) {
            message = data.message + '\n\n';
        } else {
            message = `**${this.t('Analysis completed')}**\n\n`;
        }

        if (data.ticket_number && data.ticket_number.trim()) {
            message += `**${this.t('Ticket')}:** ${data.ticket_number}\n\n`;
        }

        const recurrenceLabel = this.getRecurrenceTypeLabel(data.recurrence_type);
        const isRoutine = data.recurrence_type !== 'once';
        const typeIcon = isRoutine ? this.t('Routine') : this.t('Single');
        message += `**${this.t('Type')}:** ${recurrenceLabel} (${typeIcon})\n\n`;

        if (isRoutine && data.recurrence_config) {
            const configInfo = this.formatRecurrenceConfig(data.recurrence_type, data.recurrence_config);
            if (configInfo) {
                message += `**${this.t('Configuration')}:** ${configInfo}\n\n`;
            }
        }

        if (data.search_summary) {
            const summary = data.search_summary;
            message += `**${this.t('Summary')}:**\n`;
            message += `• ${this.t('Hosts found')}: ${summary.total_hosts_found}\n`;
            message += `• ${this.t('Groups found')}: ${summary.total_groups_found}\n`;
            if (summary.hosts_by_tags > 0) {
                message += `• ${this.t('Hosts by tags')}: ${summary.hosts_by_tags}\n`;
            }
            if (summary.has_ticket) {
                message += `• ${this.t('With ticket')}: ${this.t('Yes')}\n`;
            }
            if (summary.is_routine) {
                message += `• ${this.t('Routine maintenance')}: ${this.t('Yes')}\n`;
            }
            message += '\n';
        }

        message = this.appendResourcesInfo(message, data);

        if (data.start_time && data.end_time) {
            message += `**${this.t('Period')}:**\n`;
            message += `• ${this.t('From')}: ${data.start_time}\n`;
            message += `• ${this.t('To')}: ${data.end_time}\n\n`;
        }

        if (data.description && data.description.trim()) {
            message += `**${this.t('Description')}:** ${data.description}\n\n`;
        }

        if (data.confidence && data.confidence > 0) {
            message += `**${this.t('Confidence')}:** ${data.confidence}%`;
        }

        return message;
    }

    /** Append found/missing hosts, groups and trigger tags to a base message. */
    appendResourcesInfo(baseMessage, data) {
        let message = baseMessage;

        if (data.found_hosts && data.found_hosts.length > 0) {
            message += `**${this.t('Servers found')} (${data.found_hosts.length}):**\n`;
            data.found_hosts.forEach((host) => {
                const displayName = host.name || host.host;
                message += `• ${displayName} (${host.host})\n`;
            });
            message += '\n';
        }

        if (data.found_groups && data.found_groups.length > 0) {
            message += `**${this.t('Groups found')} (${data.found_groups.length}):**\n`;
            data.found_groups.forEach((group) => {
                message += `• ${group.name}\n`;
            });
            message += '\n';
        }

        if (data.trigger_tags && data.trigger_tags.length > 0) {
            message += `**${this.t('Trigger tags')}:**\n`;
            data.trigger_tags.forEach((tag) => {
                message += `• ${tag.tag}: ${tag.value}\n`;
            });
            message += '\n';
        }

        if (data.missing_hosts && data.missing_hosts.length > 0) {
            message += `**${this.t('Servers NOT found')}:**\n`;
            data.missing_hosts.forEach((host) => {
                message += `• ${host}\n`;
            });
            message += '\n';
        }

        if (data.missing_groups && data.missing_groups.length > 0) {
            message += `**${this.t('Groups NOT found')}:**\n`;
            data.missing_groups.forEach((group) => {
                message += `• ${group}\n`;
            });
            message += '\n';
        }

        return message;
    }

    /**
     * Build the HTML for the maintenance confirmation details panel.
     * Returns an HTML string (already escaped where user data is inserted).
     */
    buildConfirmationDetailsHtml(data) {
        const isRoutine = data.recurrence_type !== 'once';
        const recurrenceLabel = this.getRecurrenceTypeLabel(data.recurrence_type);
        const hasTicket = data.ticket_number && data.ticket_number.trim();

        let html = `<h5>${this.t('Maintenance details')}:</h5><ul>`;

        if (hasTicket) {
            html += `<li><strong>${this.t('Ticket')}:</strong> ${this.escapeHtml(data.ticket_number)}</li>`;
        }

        html += `<li><strong>${this.t('Type')}:</strong> ${this.escapeHtml(recurrenceLabel)}` +
            `${isRoutine ? ` (${this.t('Routine')})` : ''}</li>`;

        if (isRoutine && data.recurrence_config) {
            const configInfo = this.formatRecurrenceConfig(data.recurrence_type, data.recurrence_config);
            if (configInfo) {
                html += `<li><strong>${this.t('Recurrence')}:</strong> ${this.escapeHtml(configInfo)}</li>`;
            }

            html += `<li><strong>${this.t('Technical configuration')}:</strong> `;
            if (data.recurrence_type === 'weekly') {
                html += `${this.t('Days bitmask')}: ${data.recurrence_config.dayofweek || 1}`;
            } else if (data.recurrence_type === 'monthly') {
                if (data.recurrence_config.day !== undefined) {
                    html += `${this.t('Day')} ${data.recurrence_config.day} ${this.t('of the month')}`;
                } else if (data.recurrence_config.dayofweek !== undefined) {
                    html += `${this.t('Days bitmask')}: ${data.recurrence_config.dayofweek}, ` +
                        `${this.t('Week')}: ${data.recurrence_config.every || 1}`;
                }
                if (data.recurrence_config.month !== undefined && data.recurrence_config.month !== 4095) {
                    const monthNames = this.decodeMonthsBitmask(data.recurrence_config.month);
                    html += `, ${this.t('Months')}: ${monthNames.join(', ')} (bitmask: ${data.recurrence_config.month})`;
                }
            } else if (data.recurrence_type === 'daily') {
                html += `${this.t('Every')} ${data.recurrence_config.every || 1} ${this.t('day(s)')}`;
            }
            html += '</li>';
        }

        if (data.found_hosts && data.found_hosts.length > 0) {
            const hostNames = data.found_hosts.map((h) => h.name || h.host).join(', ');
            html += `<li><strong>${this.t('Servers')} (${data.found_hosts.length}):</strong> ${this.escapeHtml(hostNames)}</li>`;
        }

        if (data.found_groups && data.found_groups.length > 0) {
            const groupNames = data.found_groups.map((g) => g.name).join(', ');
            html += `<li><strong>${this.t('Groups')} (${data.found_groups.length}):</strong> ${this.escapeHtml(groupNames)}</li>`;
        }

        if (data.trigger_tags && data.trigger_tags.length > 0) {
            const tagStrings = data.trigger_tags.map((t) => `${t.tag}: ${t.value}`).join(', ');
            html += `<li><strong>${this.t('Trigger tags')}:</strong> ${this.escapeHtml(tagStrings)}</li>`;
        }

        if (Array.isArray(data.problem_tags) && data.problem_tags.length > 0) {
            const problemTagStrings = data.problem_tags.map((t) => `${t.tag}: ${t.value}`).join(', ');
            html += `<li><strong>${this.t('Problem tags')}:</strong> ${this.escapeHtml(problemTagStrings)}</li>`;
        }

        if (data.maintenance_type === 1) {
            html += `<li><strong>${this.t('Without data collection')}</strong></li>`;
        }

        if (data.start_time && data.end_time) {
            html += `<li><strong>${this.t('Period')}:</strong> ${this.escapeHtml(data.start_time)} - ${this.escapeHtml(data.end_time)}</li>`;
        }

        const previewName = this.generateMaintenanceName(data);
        html += `<li><strong>${this.t('Name')}:</strong> ${this.escapeHtml(previewName)}</li>`;
        html += '</ul>';

        if (isRoutine) {
            html += '<div class="routine-warning">';
            html += `<strong>${this.t('Routine maintenance')}:</strong><br>`;
            html += this.t('This maintenance repeats automatically according to the configured schedule. Review times and frequency carefully before confirming.');
            html += '</div>';
        }

        if (!hasTicket) {
            html += '<div class="no-ticket-warning">';
            html += `<strong>${this.t('No ticket')}:</strong><br>`;
            html += this.t('The standard name will be used. To include a ticket in future requests, mention it in the message — any ticket/incident/change ID works (e.g. "ticket INC0012345", "JIRA-4521" or "100-178306").');
            html += '</div>';
        }

        return html;
    }
}

if (typeof window !== 'undefined') {
    window.AIMaintenanceMessageFormatter = AIMaintenanceMessageFormatter;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AIMaintenanceMessageFormatter;
}
