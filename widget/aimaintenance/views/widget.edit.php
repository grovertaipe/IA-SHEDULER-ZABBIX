<?php declare(strict_types = 0);

/**
 * AI Maintenance widget configuration form view (Req 33.3, 33.4).
 *
 * Renders the CWidgetField views declared by WidgetForm. The form benefits from
 * the native inline validation (api_url is flagged NOT_EMPTY) and the palette
 * color picker (accent_color via CWidgetFieldColorView).
 *
 * @var CView $this
 * @var array $data
 */

(new CWidgetFormView($data))
    ->addField(
        new CWidgetFieldTextBoxView($data['fields']['api_url'])
    )
    ->addField(
        new CWidgetFieldTextBoxView($data['fields']['chat_height'])
    )
    ->addField(
        new CWidgetFieldColorView($data['fields']['accent_color'])
    )
    ->show();
