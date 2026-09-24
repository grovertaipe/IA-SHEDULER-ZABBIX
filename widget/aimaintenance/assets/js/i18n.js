/**
 * i18n.js — self-contained JS translation catalog for the AI Maintenance widget
 * (Req 33.2).
 *
 * The module's dynamic strings are not present in Zabbix's .mo catalogs, so the
 * native `t()` helper would only echo the English key. This class ships the
 * module's own dictionary for Spanish (es), English (en) and Portuguese (pt) so
 * every dynamic message follows the Zabbix user's language.
 *
 * Usage:
 *   const i18n = new AIMaintenanceI18n('es');
 *   i18n.t('Send message'); // -> 'Enviar mensaje'
 *
 * The key is the ENGLISH source string; the value is the translation. When a key
 * (or the language) is missing, t() falls back to the key itself (English).
 *
 * Registered FIRST in manifest.json so it is available to the orchestrator and
 * the injected `t` used by message.formatter.js and ui.renderer.js.
 */
class AIMaintenanceI18n {
    /**
     * @param {string} [lang] One of 'es', 'en', 'pt'. Unknown values fall back to 'en'.
     */
    constructor(lang) {
        const supported = ['es', 'en', 'pt'];
        const candidate = (lang || 'en').toString().slice(0, 2).toLowerCase();
        this.lang = supported.indexOf(candidate) !== -1 ? candidate : 'en';
        this.catalog = AIMaintenanceI18n.catalog();
    }

    /**
     * Translate an English source key into the active language. Falls back to the
     * key when the entry or language is missing.
     * @param {string} key
     * @returns {string}
     */
    t(key) {
        const entry = this.catalog[key];
        if (entry && typeof entry[this.lang] === 'string') {
            return entry[this.lang];
        }
        return key;
    }

    /**
     * The full translation dictionary. Keyed by English source string.
     * @returns {Object<string, Object<string, string>>}
     */
    static catalog() {
        return {
            // ---- Controls / ARIA labels ---------------------------------
            'Send message': { es: 'Enviar mensaje', en: 'Send message', pt: 'Enviar mensagem' },
            'Message to the assistant': { es: 'Mensaje para el asistente', en: 'Message to the assistant', pt: 'Mensagem para o assistente' },
            'Conversation history': { es: 'Historial de conversación', en: 'Conversation history', pt: 'Histórico da conversa' },
            'View routine maintenance templates': { es: 'Ver plantillas de mantenimiento rutinario', en: 'View routine maintenance templates', pt: 'Ver modelos de manutenção rotineira' },
            'Confirm maintenance': { es: 'Confirmar mantenimiento', en: 'Confirm maintenance', pt: 'Confirmar manutenção' },
            'Retry': { es: 'Reintentar', en: 'Retry', pt: 'Tentar novamente' },
            'Retry last request': { es: 'Reintentar la última solicitud', en: 'Retry last request', pt: 'Repetir a última solicitação' },
            'Start a new request': { es: 'Nueva solicitud', en: 'Start a new request', pt: 'Nova solicitação' },
            'Context reset. Describe a new maintenance.': { es: 'Contexto reiniciado. Describe un nuevo mantenimiento.', en: 'Context reset. Describe a new maintenance.', pt: 'Contexto reiniciado. Descreva uma nova manutenção.' },

            // ---- Processing / status ------------------------------------
            'Processing...': { es: 'Procesando...', en: 'Processing...', pt: 'Processando...' },
            'Analyzing request...': { es: 'Analizando solicitud...', en: 'Analyzing request...', pt: 'Analisando solicitação...' },
            'Creating maintenance...': { es: 'Creando mantenimiento...', en: 'Creating maintenance...', pt: 'Criando manutenção...' },
            'Retrying...': { es: 'Reintentando...', en: 'Retrying...', pt: 'Tentando novamente...' },
            'Connection error': { es: 'Error de conexión', en: 'Connection error', pt: 'Erro de conexão' },

            // ---- Health / connection ------------------------------------
            'System reports status': { es: 'El sistema reporta el estado', en: 'System reports status', pt: 'O sistema reporta o estado' },
            'Zabbix status': { es: 'Estado de Zabbix', en: 'Zabbix status', pt: 'Estado do Zabbix' },
            'AI provider': { es: 'Proveedor de IA', en: 'AI provider', pt: 'Provedor de IA' },
            'Not available': { es: 'No disponible', en: 'Not available', pt: 'Não disponível' },
            'Connected': { es: 'Conectado', en: 'Connected', pt: 'Conectado' },
            'Disconnected': { es: 'Desconectado', en: 'Disconnected', pt: 'Desconectado' },
            'Degraded': { es: 'Degradado', en: 'Degraded', pt: 'Degradado' },
            'Some features may be limited.': { es: 'Algunas funciones pueden estar limitadas.', en: 'Some features may be limited.', pt: 'Alguns recursos podem estar limitados.' },
            'System connected': { es: 'Sistema conectado', en: 'System connected', pt: 'Sistema conectado' },
            'Features': { es: 'Funciones', en: 'Features', pt: 'Recursos' },
            'Tickets': { es: 'Tickets', en: 'Tickets', pt: 'Tickets' },
            'System status': { es: 'Estado del sistema', en: 'System status', pt: 'Estado do sistema' },
            'Could not verify the connection with the backend.': { es: 'No se pudo verificar la conexión con el backend.', en: 'Could not verify the connection with the backend.', pt: 'Não foi possível verificar a conexão com o backend.' },
            'Features may be limited until the connection is restored.': { es: 'Las funciones pueden estar limitadas hasta que se restablezca la conexión.', en: 'Features may be limited until the connection is restored.', pt: 'Os recursos podem ficar limitados até que a conexão seja restabelecida.' },
            'Could not connect to the backend. Verify the service is running.': { es: 'No se pudo conectar con el backend. Verifica que el servicio esté en ejecución.', en: 'Could not connect to the backend. Verify the service is running.', pt: 'Não foi possível conectar ao backend. Verifique se o serviço está em execução.' },
            'The request took too long. You can try again.': { es: 'La solicitud tardó demasiado. Puedes intentarlo de nuevo.', en: 'The request took too long. You can try again.', pt: 'A solicitação demorou demais. Você pode tentar novamente.' },

            // ---- Validation / errors ------------------------------------
            'Error': { es: 'Error', en: 'Error', pt: 'Erro' },
            'No data': { es: 'Sin datos', en: 'No data', pt: 'Sem dados' },
            'Invalid response from server': { es: 'Respuesta no válida del servidor', en: 'Invalid response from server', pt: 'Resposta inválida do servidor' },
            'The message is too short. Describe what kind of maintenance you need to create.': { es: 'El mensaje es demasiado corto. Describe qué tipo de mantenimiento necesitas crear.', en: 'The message is too short. Describe what kind of maintenance you need to create.', pt: 'A mensagem é muito curta. Descreva que tipo de manutenção você precisa criar.' },
            'The message is too long. Please be more concise.': { es: 'El mensaje es demasiado largo. Por favor sé más conciso.', en: 'The message is too long. Please be more concise.', pt: 'A mensagem é muito longa. Por favor, seja mais conciso.' },
            'I received a response I could not fully process.': { es: 'Recibí una respuesta que no pude procesar por completo.', en: 'I received a response I could not fully process.', pt: 'Recebi uma resposta que não consegui processar completamente.' },
            'There is no maintenance data to confirm': { es: 'No hay datos de mantenimiento para confirmar', en: 'There is no maintenance data to confirm', pt: 'Não há dados de manutenção para confirmar' },
            'There are no valid hosts or groups to create the maintenance': { es: 'No hay hosts o grupos válidos para crear el mantenimiento', en: 'There are no valid hosts or groups to create the maintenance', pt: 'Não há hosts ou grupos válidos para criar a manutenção' },
            'No valid hosts or groups found to create the maintenance': { es: 'No se encontraron hosts o grupos válidos para crear el mantenimiento', en: 'No valid hosts or groups found to create the maintenance', pt: 'Nenhum host ou grupo válido encontrado para criar a manutenção' },
            'Error creating maintenance': { es: 'Error al crear el mantenimiento', en: 'Error creating maintenance', pt: 'Erro ao criar a manutenção' },

            // ---- Templates ----------------------------------------------
            'Templates are not available right now.': { es: 'Las plantillas no están disponibles en este momento.', en: 'Templates are not available right now.', pt: 'Os modelos não estão disponíveis no momento.' },
            'Routine maintenance examples': { es: 'Ejemplos de mantenimiento rutinario', en: 'Routine maintenance examples', pt: 'Exemplos de manutenção rotineira' },
            'Routine maintenance templates': { es: 'Plantillas de mantenimiento rutinario', en: 'Routine maintenance templates', pt: 'Modelos de manutenção rotineira' },
            'Examples': { es: 'Ejemplos', en: 'Examples', pt: 'Exemplos' },
            'Detected information': { es: 'Información detectada', en: 'Detected information', pt: 'Informação detectada' },

            // ---- Template example bodies (were hard-coded Spanish) -------
            'template.example.daily': { es: 'backup diario 02:00-03:00 ticket 100-178306', en: 'daily backup 02:00-03:00 ticket 100-178306', pt: 'backup diário 02:00-03:00 ticket 100-178306' },
            'template.example.weekly': { es: 'cada domingo 01:00-03:00 ticket 100-178306', en: 'every Sunday 01:00-03:00 ticket 100-178306', pt: 'todo domingo 01:00-03:00 ticket 100-178306' },
            'template.example.monthly': { es: 'día 1 de cada mes 02:00-04:00 ticket 100-178306', en: 'day 1 of every month 02:00-04:00 ticket 100-178306', pt: 'dia 1 de cada mês 02:00-04:00 ticket 100-178306' },

            // ---- Maintenance summary / preview --------------------------
            'Analysis completed': { es: 'Análisis completado', en: 'Analysis completed', pt: 'Análise concluída' },
            'Ticket': { es: 'Ticket', en: 'Ticket', pt: 'Ticket' },
            'Type': { es: 'Tipo', en: 'Type', pt: 'Tipo' },
            'Configuration': { es: 'Configuración', en: 'Configuration', pt: 'Configuração' },
            'Summary': { es: 'Resumen', en: 'Summary', pt: 'Resumo' },
            'Hosts found': { es: 'Hosts encontrados', en: 'Hosts found', pt: 'Hosts encontrados' },
            'Groups found': { es: 'Grupos encontrados', en: 'Groups found', pt: 'Grupos encontrados' },
            'Hosts by tags': { es: 'Hosts por etiquetas', en: 'Hosts by tags', pt: 'Hosts por etiquetas' },
            'With ticket': { es: 'Con ticket', en: 'With ticket', pt: 'Com ticket' },
            'Yes': { es: 'Sí', en: 'Yes', pt: 'Sim' },
            'Routine maintenance': { es: 'Mantenimiento rutinario', en: 'Routine maintenance', pt: 'Manutenção rotineira' },
            'Period': { es: 'Período', en: 'Period', pt: 'Período' },
            'From': { es: 'Desde', en: 'From', pt: 'De' },
            'To': { es: 'Hasta', en: 'To', pt: 'Até' },
            'Description': { es: 'Descripción', en: 'Description', pt: 'Descrição' },
            'Confidence': { es: 'Confianza', en: 'Confidence', pt: 'Confiança' },
            'Servers found': { es: 'Servidores encontrados', en: 'Servers found', pt: 'Servidores encontrados' },
            'Trigger tags': { es: 'Etiquetas de trigger', en: 'Trigger tags', pt: 'Etiquetas de trigger' },
            'Problem tags': { es: 'Tags de problema', en: 'Problem tags', pt: 'Tags de problema' },
            'Without data collection': { es: 'Sin recolección de datos', en: 'Without data collection', pt: 'Sem coleta de dados' },
            'Servers NOT found': { es: 'Servidores NO encontrados', en: 'Servers NOT found', pt: 'Servidores NÃO encontrados' },
            'Groups NOT found': { es: 'Grupos NO encontrados', en: 'Groups NOT found', pt: 'Grupos NÃO encontrados' },
            'Maintenance details': { es: 'Detalles del mantenimiento', en: 'Maintenance details', pt: 'Detalhes da manutenção' },
            'Recurrence': { es: 'Recurrencia', en: 'Recurrence', pt: 'Recorrência' },
            'Technical configuration': { es: 'Configuración técnica', en: 'Technical configuration', pt: 'Configuração técnica' },
            'Days bitmask': { es: 'Bitmask de días', en: 'Days bitmask', pt: 'Bitmask de dias' },
            'Week': { es: 'Semana', en: 'Week', pt: 'Semana' },
            'Months': { es: 'Meses', en: 'Months', pt: 'Meses' },
            'Day': { es: 'Día', en: 'Day', pt: 'Dia' },
            'of the month': { es: 'del mes', en: 'of the month', pt: 'do mês' },
            'Servers': { es: 'Servidores', en: 'Servers', pt: 'Servidores' },
            'Groups': { es: 'Grupos', en: 'Groups', pt: 'Grupos' },
            'Name': { es: 'Nombre', en: 'Name', pt: 'Nome' },
            'No ticket': { es: 'Sin ticket', en: 'No ticket', pt: 'Sem ticket' },
            'This maintenance repeats automatically according to the configured schedule. Review times and frequency carefully before confirming.': { es: 'Este mantenimiento se repite automáticamente según la programación configurada. Revisa cuidadosamente los horarios y la frecuencia antes de confirmar.', en: 'This maintenance repeats automatically according to the configured schedule. Review times and frequency carefully before confirming.', pt: 'Esta manutenção se repete automaticamente conforme a programação configurada. Revise cuidadosamente os horários e a frequência antes de confirmar.' },
            'The standard name will be used. To include a ticket in future requests, mention it in the message — any ticket/incident/change ID works (e.g. "ticket INC0012345", "JIRA-4521" or "100-178306").': { es: 'Se usará el nombre estándar. Para incluir un ticket en futuras solicitudes, menciónalo en el mensaje — sirve cualquier ID de ticket/incidente/cambio (ej. "ticket INC0012345", "JIRA-4521" o "100-178306").', en: 'The standard name will be used. To include a ticket in future requests, mention it in the message — any ticket/incident/change ID works (e.g. "ticket INC0012345", "JIRA-4521" or "100-178306").', pt: 'Será usado o nome padrão. Para incluir um ticket em solicitações futuras, mencione-o na mensagem — qualquer ID de ticket/incidente/mudança funciona (ex. "ticket INC0012345", "JIRA-4521" ou "100-178306").' },

            // ---- Recurrence labels --------------------------------------
            'Single': { es: 'Único', en: 'Single', pt: 'Único' },
            'Daily': { es: 'Diario', en: 'Daily', pt: 'Diário' },
            'Weekly': { es: 'Semanal', en: 'Weekly', pt: 'Semanal' },
            'Monthly': { es: 'Mensual', en: 'Monthly', pt: 'Mensal' },
            'Every': { es: 'Cada', en: 'Every', pt: 'A cada' },
            'day(s)': { es: 'día(s)', en: 'day(s)', pt: 'dia(s)' },
            'week(s)': { es: 'semana(s)', en: 'week(s)', pt: 'semana(s)' },
            'month(s)': { es: 'mes(es)', en: 'month(s)', pt: 'mês(es)' },
            'at': { es: 'a las', en: 'at', pt: 'às' },
            'on': { es: 'el', en: 'on', pt: 'em' },
            'of every': { es: 'de cada', en: 'of every', pt: 'de cada' },
            'of every month': { es: 'de cada mes', en: 'of every month', pt: 'de cada mês' },
            'first': { es: 'primera', en: 'first', pt: 'primeira' },
            'second': { es: 'segunda', en: 'second', pt: 'segunda' },
            'third': { es: 'tercera', en: 'third', pt: 'terceira' },
            'fourth': { es: 'cuarta', en: 'fourth', pt: 'quarta' },
            'last': { es: 'última', en: 'last', pt: 'última' },
            'week': { es: 'semana', en: 'week', pt: 'semana' },
            'Custom configuration': { es: 'Configuración personalizada', en: 'Custom configuration', pt: 'Configuração personalizada' },

            // ---- Day names ----------------------------------------------
            'Monday': { es: 'Lunes', en: 'Monday', pt: 'Segunda-feira' },
            'Tuesday': { es: 'Martes', en: 'Tuesday', pt: 'Terça-feira' },
            'Wednesday': { es: 'Miércoles', en: 'Wednesday', pt: 'Quarta-feira' },
            'Thursday': { es: 'Jueves', en: 'Thursday', pt: 'Quinta-feira' },
            'Friday': { es: 'Viernes', en: 'Friday', pt: 'Sexta-feira' },
            'Saturday': { es: 'Sábado', en: 'Saturday', pt: 'Sábado' },
            'Sunday': { es: 'Domingo', en: 'Sunday', pt: 'Domingo' },

            // ---- Month names --------------------------------------------
            'January': { es: 'Enero', en: 'January', pt: 'Janeiro' },
            'February': { es: 'Febrero', en: 'February', pt: 'Fevereiro' },
            'March': { es: 'Marzo', en: 'March', pt: 'Março' },
            'April': { es: 'Abril', en: 'April', pt: 'Abril' },
            'May': { es: 'Mayo', en: 'May', pt: 'Maio' },
            'June': { es: 'Junio', en: 'June', pt: 'Junho' },
            'July': { es: 'Julio', en: 'July', pt: 'Julho' },
            'August': { es: 'Agosto', en: 'August', pt: 'Agosto' },
            'September': { es: 'Septiembre', en: 'September', pt: 'Setembro' },
            'October': { es: 'Octubre', en: 'October', pt: 'Outubro' },
            'November': { es: 'Noviembre', en: 'November', pt: 'Novembro' },
            'December': { es: 'Diciembre', en: 'December', pt: 'Dezembro' },
            'All months': { es: 'Todos los meses', en: 'All months', pt: 'Todos os meses' },

            // ---- Name generation ----------------------------------------
            'Routine': { es: 'Rutinario', en: 'Routine', pt: 'Rotineiro' },
            'Group': { es: 'Grupo', en: 'Group', pt: 'Grupo' },
            'and': { es: 'y', en: 'and', pt: 'e' },
            'more hosts': { es: 'hosts más', en: 'more hosts', pt: 'hosts a mais' },
            'more groups': { es: 'grupos más', en: 'more groups', pt: 'grupos a mais' },
            'Various resources': { es: 'Varios recursos', en: 'Various resources', pt: 'Vários recursos' },

            // ---- Maintenance list summary -------------------------------
            'Routine maintenance configured': { es: 'Mantenimiento rutinario configurado', en: 'Routine maintenance configured', pt: 'Manutenção rotineira configurada' },
            'Auto-generated': { es: 'Autogenerado', en: 'Auto-generated', pt: 'Gerado automaticamente' },
            'It will run automatically according to the configuration': { es: 'Se ejecutará automáticamente según la configuración', en: 'It will run automatically according to the configuration', pt: 'Será executado automaticamente conforme a configuração' },
            'Maintenance summary': { es: 'Resumen de mantenimientos', en: 'Maintenance summary', pt: 'Resumo das manutenções' },
            'With tickets': { es: 'Con tickets', en: 'With tickets', pt: 'Com tickets' },
            'Total': { es: 'Total', en: 'Total', pt: 'Total' }
        };
    }
}

if (typeof window !== 'undefined') {
    window.AIMaintenanceI18n = AIMaintenanceI18n;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AIMaintenanceI18n;
}
