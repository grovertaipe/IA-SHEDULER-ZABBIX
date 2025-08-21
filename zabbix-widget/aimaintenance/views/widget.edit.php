<?php declare(strict_types = 0);

/**
 * AI Maintenance widget form view.
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
    ->show();
