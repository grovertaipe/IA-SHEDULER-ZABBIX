<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Includes;

/**
 * Translator.php — self-contained i18n catalog for the AI Maintenance widget
 * PHP view (Req 33.2).
 *
 * Rationale: the module's user-facing strings are NOT present in Zabbix's .mo
 * catalogs, so `_()` would just echo the English source. To guarantee a single,
 * consistent UI language that follows the Zabbix user's own language selection,
 * this class ships its own dictionary for Spanish (es), English (en) and
 * Portuguese (pt).
 *
 * Language resolution:
 *   - Reads the Zabbix user language from CWebUser::$data['lang'] (values look
 *     like "es", "en_US", "pt_BR" or "default").
 *   - Maps to one of es/en/pt by the 2-letter prefix.
 *   - Falls back to "en" for "default" or any unsupported/unknown value.
 *
 * API:
 *   Translator::init(?string $lang)  — resolve and store the active language.
 *   Translator::t(string $key): string — translate; falls back to the key
 *   (English source) when a translation is missing.
 */
class Translator {

    /** @var string Active resolved language: one of 'es', 'en', 'pt'. */
    private static $lang = 'en';

    /** @var string[] Supported languages. */
    private static $supported = ['es', 'en', 'pt'];

    /**
     * Resolve the active language from a raw Zabbix language value and store it.
     *
     * @param string|null $lang Raw value (e.g. "es", "en_US", "pt_BR", "default").
     */
    public static function init(?string $lang): void {
        self::$lang = self::resolveLang($lang);
    }

    /** Currently active resolved language (es/en/pt). */
    public static function getLang(): string {
        return self::$lang;
    }

    /**
     * Map a raw Zabbix language value to a supported language code.
     * Falls back to 'en' when the value is empty, "default" or unsupported.
     */
    public static function resolveLang(?string $lang): string {
        if ($lang === null || $lang === '' || strtolower($lang) === 'default') {
            return 'en';
        }

        $prefix = strtolower(substr($lang, 0, 2));

        return in_array($prefix, self::$supported, true) ? $prefix : 'en';
    }

    /**
     * Translate a key (English source string) into the active language.
     * Falls back to the key itself when the entry or language is missing.
     */
    public static function t(string $key): string {
        $catalog = self::catalog();

        if (isset($catalog[$key][self::$lang])) {
            return $catalog[$key][self::$lang];
        }

        return $key;
    }

    /**
     * Translation dictionary keyed by the ENGLISH source string. Each entry
     * carries es/en/pt values. Covers every user-facing string in
     * views/widget.view.php, including the localized example snippets.
     *
     * @return array<string, array<string, string>>
     */
    private static function catalog(): array {
        return [
            // Header.
            'AI Maintenance Assistant' => [
                'es' => 'Asistente de Mantenimiento IA',
                'en' => 'AI Maintenance Assistant',
                'pt' => 'Assistente de Manutenção IA'
            ],
            '🐧 With routine maintenance support' => [
                'es' => '🐧 Con soporte de mantenimiento rutinario',
                'en' => '🐧 With routine maintenance support',
                'pt' => '🐧 Com suporte a manutenção rotineira'
            ],
            'View routine maintenance templates' => [
                'es' => 'Ver plantillas de mantenimiento rutinario',
                'en' => 'View routine maintenance templates',
                'pt' => 'Ver modelos de manutenção rotineira'
            ],
            'Unknown user' => [
                'es' => 'Usuario desconocido',
                'en' => 'Unknown user',
                'pt' => 'Usuário desconhecido'
            ],

            // Conversation region.
            'Conversation history' => [
                'es' => 'Historial de conversación',
                'en' => 'Conversation history',
                'pt' => 'Histórico da conversa'
            ],

            // Welcome block.
            '🎯 Maintenance Assistant!' => [
                'es' => '🎯 ¡Asistente de Mantenimiento!',
                'en' => '🎯 Maintenance Assistant!',
                'pt' => '🎯 Assistente de Manutenção!'
            ],
            'Full support for routine maintenance:' => [
                'es' => 'Soporte completo para mantenimiento rutinario:',
                'en' => 'Full support for routine maintenance:',
                'pt' => 'Suporte completo para manutenção rotineira:'
            ],

            // Feature-card labels.
            'Specific servers' => [
                'es' => 'Servidores específicos',
                'en' => 'Specific servers',
                'pt' => 'Servidores específicos'
            ],
            'Full groups' => [
                'es' => 'Grupos completos',
                'en' => 'Full groups',
                'pt' => 'Grupos completos'
            ],
            'Daily maintenance' => [
                'es' => 'Mantenimiento diario',
                'en' => 'Daily maintenance',
                'pt' => 'Manutenção diária'
            ],
            'Weekly maintenance' => [
                'es' => 'Mantenimiento semanal',
                'en' => 'Weekly maintenance',
                'pt' => 'Manutenção semanal'
            ],
            'Monthly maintenance' => [
                'es' => 'Mantenimiento mensual',
                'en' => 'Monthly maintenance',
                'pt' => 'Manutenção mensal'
            ],
            'Ticket management' => [
                'es' => 'Gestión de tickets',
                'en' => 'Ticket management',
                'pt' => 'Gestão de tickets'
            ],

            // Accessible label for the clickable welcome example cards. The
            // example text is appended by the view (e.g. "Use this example: ...").
            'Use this example:' => [
                'es' => 'Usar este ejemplo:',
                'en' => 'Use this example:',
                'pt' => 'Usar este exemplo:'
            ],

            // Feature-card example snippets (localized). Tickets accept ANY
            // nomenclature (INC0012345, JIRA-4521, 100-178306, ...); the ones
            // below are just samples, not a mandatory format.
            'example.specific_servers' => [
                'es' => 'srv-web01 mañana 22:00-23:00 ticket 100-178306',
                'en' => 'srv-web01 tomorrow 22:00-23:00 ticket 100-178306',
                'pt' => 'srv-web01 amanhã 22:00-23:00 ticket 100-178306'
            ],
            'example.full_groups' => [
                'es' => 'grupo Cloud hoy 14:00-16:00 ticket 100-178306',
                'en' => 'group Cloud today 14:00-16:00 ticket 100-178306',
                'pt' => 'grupo Cloud hoje 14:00-16:00 ticket 100-178306'
            ],
            'example.daily' => [
                'es' => 'backup diario 02:00-03:00 ticket 100-178306',
                'en' => 'daily backup 02:00-03:00 ticket 100-178306',
                'pt' => 'backup diário 02:00-03:00 ticket 100-178306'
            ],
            'example.weekly' => [
                'es' => 'cada domingo 01:00-03:00 ticket 100-178306',
                'en' => 'every Sunday 01:00-03:00 ticket 100-178306',
                'pt' => 'todo domingo 01:00-03:00 ticket 100-178306'
            ],
            'example.monthly' => [
                'es' => 'día 1 de cada mes 02:00-04:00 ticket 100-178306',
                'en' => 'day 1 of every month 02:00-04:00 ticket 100-178306',
                'pt' => 'dia 1 de cada mês 02:00-04:00 ticket 100-178306'
            ],
            'example.ticket' => [
                'es' => 'srv-db01 hoy 03:00-04:00 ticket INC0012345',
                'en' => 'srv-db01 today 03:00-04:00 ticket INC0012345',
                'pt' => 'srv-db01 hoje 03:00-04:00 ticket INC0012345'
            ],

            // Welcome footer.
            '💡 Click the 📋 button to see examples. Include ticket numbers for better tracking.' => [
                'es' => '💡 Pulsa el botón 📋 para ver ejemplos. Incluye números de ticket para un mejor seguimiento.',
                'en' => '💡 Click the 📋 button to see examples. Include ticket numbers for better tracking.',
                'pt' => '💡 Clique no botão 📋 para ver exemplos. Inclua números de ticket para melhor acompanhamento.'
            ],

            // Input area.
            'Message to the assistant' => [
                'es' => 'Mensaje para el asistente',
                'en' => 'Message to the assistant',
                'pt' => 'Mensagem para o assistente'
            ],
            'placeholder.input' => [
                'es' => '💬 Describe el mantenimiento... ej. "srv-web01 mañana 22:00-23:00 ticket 100-178306"',
                'en' => '💬 Describe the maintenance... e.g. "srv-web01 tomorrow 22:00-23:00 ticket 100-178306"',
                'pt' => '💬 Descreva a manutenção... ex. "srv-web01 amanhã 22:00-23:00 ticket 100-178306"'
            ],
            'Send message (Enter to send)' => [
                'es' => 'Enviar mensaje (Enter para enviar)',
                'en' => 'Send message (Enter to send)',
                'pt' => 'Enviar mensagem (Enter para enviar)'
            ],
            'Send message' => [
                'es' => 'Enviar mensaje',
                'en' => 'Send message',
                'pt' => 'Enviar mensagem'
            ],

            // Confirmation dialog.
            'Confirm maintenance' => [
                'es' => 'Confirmar mantenimiento',
                'en' => 'Confirm maintenance',
                'pt' => 'Confirmar manutenção'
            ],
            '✅ Confirm Maintenance' => [
                'es' => '✅ Confirmar Mantenimiento',
                'en' => '✅ Confirm Maintenance',
                'pt' => '✅ Confirmar Manutenção'
            ],
            '✅ Create Maintenance' => [
                'es' => '✅ Crear Mantenimiento',
                'en' => '✅ Create Maintenance',
                'pt' => '✅ Criar Manutenção'
            ],
            '❌ Cancel' => [
                'es' => '❌ Cancelar',
                'en' => '❌ Cancel',
                'pt' => '❌ Cancelar'
            ],

            // Loading.
            'Processing request...' => [
                'es' => 'Procesando solicitud...',
                'en' => 'Processing request...',
                'pt' => 'Processando solicitação...'
            ]
        ];
    }
}
