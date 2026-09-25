<?php declare(strict_types = 1);

use Modules\AIMaintenance\Includes\Translator;

/**
 * AI Maintenance widget view - routine maintenance and ticket support.
 *
 * Accessibility (Req 23): the chat controls carry ARIA roles/labels, the
 * messages region is an aria-live log, and interactive controls are focusable
 * (see also assets/js/ui.renderer.js which reinforces these at runtime).
 *
 * i18n (Req 33.2): user-facing strings are resolved through a self-contained
 * catalog (Modules\AIMaintenance\Includes\Translator) that follows the Zabbix
 * user's language (es/en/pt), because the module strings are not present in
 * Zabbix's .mo catalogs. Every user-facing string uses Translator::t().
 *
 * @var CView $this
 * @var array $data
 */

$chatHeight = $data['fields_values']['chat_height'] ?? 500;
$apiUrl = $data['fields_values']['api_url'] ?? 'http://localhost:5005';
$accentColor = $data['fields_values']['accent_color'] ?? '';

// Current user information.
$userInfo = CWebUser::$data;

// The Zabbix frontend SESSION id used by the backend to authenticate every
// acting request via user.checkAuthentication. It lives in the PHP session
// ($_SESSION['sessionid']) and is retrieved with CSessionHelper::getId() — the
// same source the Zabbix frontend uses for its own server/API calls. It is NOT
// reliably present in CWebUser::$data on a normal authenticated request (that
// is populated from API::User()->checkAuthentication(), whose result omits the
// 'sessionid' key), so reading CWebUser::$data['sessionid'] there yields null.
// It is exposed to the widget JS via ->setVar('sessionid', ...) below and sent
// ONLY to the trusted backend over TLS; never displayed or persisted.
$sessionid = \CSessionHelper::getId();
if ($sessionid === '') {
    $sessionid = CWebUser::$data['sessionid'] ?? null;
}

// Resolve the widget UI language from the Zabbix user language (Req 33.2).
Translator::init($userInfo['lang'] ?? null);

$userDisplay = '';
if (!empty($userInfo)) {
    $userDisplay = trim(($userInfo['name'] ?? '') . ' ' . ($userInfo['surname'] ?? ''));
    if (empty($userDisplay)) {
        $userDisplay = $userInfo['username'] ?? Translator::t('Unknown user');
    }
}

// Welcome feature-card examples. Each localized snippet is shown in the card's
// chip AND carried verbatim in data-example so a click/Enter/Space preloads it
// into the input (see assets/js/class.widget.js). Kept in one place so the chip
// text, the data-example payload and the aria-label stay in sync.
$featureExamples = [
    'specific_servers' => Translator::t('example.specific_servers'),
    'full_groups' => Translator::t('example.full_groups'),
    'daily' => Translator::t('example.daily'),
    'weekly' => Translator::t('example.weekly'),
    'monthly' => Translator::t('example.monthly'),
    'ticket' => Translator::t('example.ticket'),
];
$useExampleLabel = Translator::t('Use this example:');

// Build a clickable, keyboard-operable welcome feature card (Req 23). The card
// exposes role="button"/tabindex/aria-label and a data-example payload; the JS
// preloads (does NOT auto-send) the example into the input on activation.
$makeFeatureCard = static function (string $icon, string $title, string $example)
        use ($useExampleLabel): CDiv {
    return (new CDiv())
        ->addClass('feature-item')
        ->setAttribute('role', 'button')
        ->setAttribute('tabindex', '0')
        ->setAttribute('data-example', $example)
        ->setAttribute('aria-label', $useExampleLabel.' '.$example)
        ->addItem((new CSpan($icon))->addClass('feature-icon'))
        ->addItem(
            (new CDiv())
                ->addClass('feature-body')
                ->addItem((new CSpan($title))->addClass('feature-text'))
                ->addItem((new CSpan($example))->addClass('feature-example'))
        );
};

// Main container. When an accent color is configured, expose it as a CSS var so
// theme.css can pick it up without hard-coding a color that ignores the theme.
$container = (new CDiv())
    ->addClass('ai-maintenance-widget')
    ->addStyle('height: 100%; overflow: hidden;'
        . ($accentColor !== '' ? ' --aim-primary-color: #' . $accentColor . ';' : ''))
    ->addItem(
        (new CDiv())
            ->addClass('ai-header')
            ->addItem(
                (new CDiv())
                    ->addClass('ai-header-content')
                    ->addItem((new CDiv())->addClass('ai-avatar')->addItem('🤖'))
                    ->addItem(
                        (new CDiv())
                            ->addClass('ai-header-text')
                            ->addItem((new CSpan(Translator::t('🐧 With routine maintenance support')))->addClass('ai-status'))
                    )
                    ->addItem(
                        (new CDiv())
                            ->addClass('ai-header-actions')
                            ->addItem(
                                (new CSpan(''))
                                    ->setId('ai-status-chip')
                                    ->addClass('ai-status-chip')
                                    ->setAttribute('role', 'status')
                                    ->setAttribute('aria-live', 'polite')
                                    ->addItem((new CSpan(''))->addClass('ai-status-dot')->setAttribute('aria-hidden', 'true'))
                                    ->addItem((new CSpan(''))->addClass('ai-status-label'))
                            )
                            ->addItem(
                                (new CButton('templates-btn', ''))
                                    ->setId('templates-btn')
                                    ->addClass('templates-button')
                                    ->setAttribute('type', 'button')
                                    ->setAttribute('title', Translator::t('View routine maintenance templates'))
                                    ->setAttribute('aria-label', Translator::t('View routine maintenance templates'))
                                    ->addItem(
                                        (new CTag('svg'))
                                            ->setAttribute('viewBox', '0 0 24 24')
                                            ->setAttribute('width', '18')
                                            ->setAttribute('height', '18')
                                            ->setAttribute('fill', 'currentColor')
                                            ->setAttribute('aria-hidden', 'true')
                                            ->setAttribute('focusable', 'false')
                                            ->addItem(
                                                (new CTag('path'))
                                                    ->setAttribute('d', 'M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z')
                                            )
                                    )
                            )
                    )
            )
    )
    ->addItem(
        (new CDiv())
            ->setId('ai-messages')
            ->addClass('ai-messages')
            ->setAttribute('role', 'log')
            ->setAttribute('aria-live', 'polite')
            ->setAttribute('aria-atomic', 'false')
            ->setAttribute('aria-relevant', 'additions text')
            ->setAttribute('aria-label', Translator::t('Conversation history'))
            ->setAttribute('tabindex', '0')
            ->addItem(
                (new CDiv())
                    ->addClass('ai-message system welcome-message')
                    ->addItem(
                        (new CDiv())
                            ->addClass('message-content')
                            ->addItem((new CDiv())->addClass('welcome-title')->addItem(Translator::t('🎯 Maintenance Assistant!')))
                            ->addItem((new CDiv())->addClass('welcome-subtitle')->addItem(Translator::t('Full support for routine maintenance:')))
                            ->addItem(
                                (new CDiv())
                                    ->addClass('feature-list')
                                    ->addItem($makeFeatureCard('🖥️', Translator::t('Specific servers'), $featureExamples['specific_servers']))
                                    ->addItem($makeFeatureCard('👥', Translator::t('Full groups'), $featureExamples['full_groups']))
                                    ->addItem($makeFeatureCard('🔄', Translator::t('Daily maintenance'), $featureExamples['daily']))
                                    ->addItem($makeFeatureCard('🗓️', Translator::t('Weekly maintenance'), $featureExamples['weekly']))
                                    ->addItem($makeFeatureCard('📅', Translator::t('Monthly maintenance'), $featureExamples['monthly']))
                                    ->addItem($makeFeatureCard('🎫', Translator::t('Ticket management'), $featureExamples['ticket']))
                            )
                            ->addItem(
                                (new CDiv())
                                    ->addClass('welcome-footer')
                                    ->addItem(Translator::t('💡 Click the 📋 button to see examples. Include ticket numbers for better tracking.'))
                            )
                    )
            )
    )
    ->addItem(
        (new CDiv())
            ->addClass('ai-input-area')
            ->addItem(
                (new CDiv())
                    ->addClass('input-container')
                    ->addItem(
                        (new CTextArea('ai-input', ''))
                            ->setId('ai-input')
                            ->setAttribute('placeholder', Translator::t('placeholder.input'))
                            ->setAttribute('rows', '3')
                            ->setAttribute('role', 'textbox')
                            ->setAttribute('aria-multiline', 'true')
                            ->setAttribute('aria-label', Translator::t('Message to the assistant'))
                    )
                    ->addItem(
                        (new CButton('ai-send-btn', ''))
                            ->setId('ai-send-btn')
                            ->addClass('send-button')
                            ->setAttribute('type', 'button')
                            ->setAttribute('title', Translator::t('Send message (Enter to send)'))
                            ->setAttribute('aria-label', Translator::t('Send message'))
                            ->addItem(
                                (new CTag('svg'))
                                    ->setAttribute('viewBox', '0 0 24 24')
                                    ->setAttribute('width', '20')
                                    ->setAttribute('height', '20')
                                    ->setAttribute('fill', 'currentColor')
                                    ->setAttribute('aria-hidden', 'true')
                                    ->setAttribute('focusable', 'false')
                                    ->addItem(
                                        (new CTag('path'))
                                            ->setAttribute('d', 'M2.01 21L23 12 2.01 3 2 10l15 2-15 2z')
                                    )
                            )
                    )
            )
    )
    ->addItem(
        (new CDiv())
            ->setId('ai-confirmation')
            ->addClass('ai-confirmation')
            ->addStyle('display: none;')
            ->setAttribute('role', 'dialog')
            ->setAttribute('aria-modal', 'true')
            ->setAttribute('aria-label', Translator::t('Confirm maintenance'))
            ->setAttribute('aria-hidden', 'true')
            ->addItem(
                (new CDiv())
                    ->addClass('confirmation-content')
                    ->addItem(new CTag('h4', true, Translator::t('✅ Confirm Maintenance')))
                    ->addItem(
                        (new CDiv())
                            ->setId('maintenance-details')
                            ->addClass('maintenance-details')
                    )
                    ->addItem(
                        (new CDiv())
                            ->addClass('confirmation-actions')
                            ->addItem(
                                (new CButton('confirm-maintenance', Translator::t('✅ Create Maintenance')))
                                    ->setId('confirm-maintenance')
                                    ->addClass('btn-alt btn-success')
                                    ->setAttribute('type', 'button')
                            )
                            ->addItem(
                                (new CButton('cancel-maintenance', Translator::t('❌ Cancel')))
                                    ->setId('cancel-maintenance')
                                    ->addClass('btn-alt btn-cancel')
                                    ->setAttribute('type', 'button')
                            )
                    )
            )
    )
    ->addItem(
        (new CDiv())
            ->setId('ai-loading')
            ->addClass('ai-loading')
            ->addStyle('display: none;')
            ->setAttribute('role', 'status')
            ->setAttribute('aria-live', 'polite')
            ->setAttribute('aria-hidden', 'true')
            ->addItem((new CDiv())->addClass('loading-spinner')->setAttribute('aria-hidden', 'true'))
            ->addItem(new CSpan(Translator::t('Processing request...')))
    );

(new CWidgetView($data))
    ->addItem($container)
    ->setVar('api_url', $apiUrl)
    ->setVar('user_info', $userInfo)
    ->setVar('sessionid', $sessionid)
    ->setVar('fields_values', $data['fields_values'])
    ->show();
