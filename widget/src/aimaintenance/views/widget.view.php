<?php declare(strict_types = 1);

/**
 * AI Maintenance widget view - Versión con soporte para mantenimientos rutinarios y tickets
 *
 * @var CView $this
 * @var array $data
 */

$chatHeight = $data['fields_values']['chat_height'] ?? 500;
$apiUrl = $data['fields_values']['api_url'] ?? 'http://localhost:5005';

// Obtener información del usuario actual
$userInfo = CWebUser::$data;
$userDisplay = '';
if (!empty($userInfo)) {
    $userDisplay = trim(($userInfo['name'] ?? '') . ' ' . ($userInfo['surname'] ?? ''));
    if (empty($userDisplay)) {
        $userDisplay = $userInfo['username'] ?? 'Usuario desconocido';
    }
}

// Contenedor principal con mejor manejo de temas
$container = (new CDiv())
    ->addClass('ai-maintenance-widget')
    ->addStyle('height: 100%; overflow: hidden;')
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
                            ->addItem((new CTag('h3', true, 'AI Maintenance Assistant')))
                            ->addItem((new CSpan('🐧 Con soporte para mantenimientos rutinarios'))->addClass('ai-status'))
                    )
                    ->addItem(
                        (new CDiv())
                            ->addClass('ai-header-actions')
                            ->addItem(
                                (new CButton('templates-btn', ''))
                                    ->setId('templates-btn')
                                    ->addClass('templates-button')
                                    ->setAttribute('title', 'Ver plantillas de mantenimientos rutinarios')
                                    ->addItem(
                                        (new CTag('svg'))
                                            ->setAttribute('viewBox', '0 0 24 24')
                                            ->setAttribute('width', '18')
                                            ->setAttribute('height', '18')
                                            ->setAttribute('fill', 'currentColor')
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
            ->addItem(
                (new CDiv())
                    ->addClass('ai-message system welcome-message')
                    ->addItem(
                        (new CDiv())
                            ->addClass('message-content')
                            ->addItem((new CDiv())->addClass('welcome-title')->addItem('🎯 ¡Asistente de Mantenimientos!'))
                            ->addItem((new CDiv())->addClass('welcome-subtitle')->addItem('Soporte completo para mantenimientos rutinarios:'))
                            ->addItem(
                                (new CDiv())
                                    ->addClass('feature-grid')
                                    ->addItem(
                                        (new CDiv())
                                            ->addClass('feature-card')
                                            ->addItem((new CDiv())->addClass('feature-icon')->addItem('🖥️'))
                                            ->addItem((new CDiv())->addClass('feature-text')->addItem('Servidores específicos'))
                                            ->addItem((new CDiv())->addClass('feature-example')->addItem('"srv-tuxito mañana 8-10h ticket 100-178306"'))
                                    )
                                    ->addItem(
                                        (new CDiv())
                                            ->addClass('feature-card')
                                            ->addItem((new CDiv())->addClass('feature-icon')->addItem('👥'))
                                            ->addItem((new CDiv())->addClass('feature-text')->addItem('Grupos completos'))
                                            ->addItem((new CDiv())->addClass('feature-example')->addItem('"grupo Cloud hoy 14-16h con ticket 200-8341"'))
                                    )
                                    ->addItem(
                                        (new CDiv())
                                            ->addClass('feature-card')
                                            ->addItem((new CDiv())->addClass('feature-icon')->addItem('🔄'))
                                            ->addItem((new CDiv())->addClass('feature-text')->addItem('Mantenimientos diarios'))
                                            ->addItem((new CDiv())->addClass('feature-example')->addItem('"backup diario a las 2 AM ticket 500-43116"'))
                                    )
                                    ->addItem(
                                        (new CDiv())
                                            ->addClass('feature-card')
                                            ->addItem((new CDiv())->addClass('feature-icon')->addItem('📅'))
                                            ->addItem((new CDiv())->addClass('feature-text')->addItem('Mantenimientos semanales'))
                                            ->addItem((new CDiv())->addClass('feature-example')->addItem('"cada domingo de 1-3 AM con ticket 100-12345"'))
                                    )
                                    ->addItem(
                                        (new CDiv())
                                            ->addClass('feature-card')
                                            ->addItem((new CDiv())->addClass('feature-icon')->addItem('🗓️'))
                                            ->addItem((new CDiv())->addClass('feature-text')->addItem('Mantenimientos mensuales'))
                                            ->addItem((new CDiv())->addClass('feature-example')->addItem('"primer día cada mes ticket 200-67890"'))
                                    )
                                    ->addItem(
                                        (new CDiv())
                                            ->addClass('feature-card')
                                            ->addItem((new CDiv())->addClass('feature-icon')->addItem('🎫'))
                                            ->addItem((new CDiv())->addClass('feature-text')->addItem('Gestión de tickets'))
                                            ->addItem((new CDiv())->addClass('feature-example')->addItem('"formato: 100-178306, 200-8341"'))
                                    )
                            )
                            ->addItem(
                                (new CDiv())
                                    ->addClass('welcome-footer')
                                    ->addItem('💡 Haz clic en el botón 📋 para ver ejemplos. Incluye números de ticket para mejor seguimiento.')
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
                            ->setAttribute('placeholder', _('💬 Describe el mantenimiento... Ej: "srv-web01 mañana 8-10h ticket 100-178306", "backup diario 2 AM con ticket 200-8341"'))
                            ->setAttribute('rows', '3')
                    )
                    ->addItem(
                        (new CButton('ai-send-btn', ''))
                            ->setId('ai-send-btn')
                            ->addClass('send-button')
                            ->setAttribute('title', 'Enviar mensaje (Enter para enviar)')
                            ->addItem(
                                (new CTag('svg'))
                                    ->setAttribute('viewBox', '0 0 24 24')
                                    ->setAttribute('width', '20')
                                    ->setAttribute('height', '20')
                                    ->setAttribute('fill', 'currentColor')
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
            ->addItem(
                (new CDiv())
                    ->addClass('confirmation-content')
                    ->addItem(new CTag('h4', true, _('✅ Confirmar Mantenimiento')))
                    ->addItem(
                        (new CDiv())
                            ->setId('maintenance-details')
                            ->addClass('maintenance-details')
                    )
                    ->addItem(
                        (new CDiv())
                            ->addClass('confirmation-actions')
                            ->addItem(
                                (new CButton('confirm-maintenance', _('✅ Crear Mantenimiento')))
                                    ->setId('confirm-maintenance')
                                    ->addClass('btn-alt btn-success')
                            )
                            ->addItem(
                                (new CButton('cancel-maintenance', _('❌ Cancelar')))
                                    ->setId('cancel-maintenance')
                                    ->addClass('btn-alt btn-cancel')
                            )
                    )
            )
    )
    ->addItem(
        (new CDiv())
            ->setId('ai-loading')
            ->addClass('ai-loading')
            ->addStyle('display: none;')
            ->addItem((new CDiv())->addClass('loading-spinner'))
            ->addItem(new CSpan(_('Procesando solicitud...')))
    );

(new CWidgetView($data))
    ->addItem($container)
    ->setVar('api_url', $apiUrl)
    ->setVar('user_info', $userInfo)  // Añadir información del usuario
    ->setVar('fields_values', $data['fields_values'])
    ->show();