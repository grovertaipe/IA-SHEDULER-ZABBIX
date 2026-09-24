<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Includes;

use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\CWidgetField;
use Zabbix\Widgets\Fields\CWidgetFieldTextBox;
use Zabbix\Widgets\Fields\CWidgetFieldColor;

/**
 * AI Maintenance widget configuration form (Req 33.3, 33.4).
 *
 * Extends the native CWidgetForm and declares its configuration with
 * CWidgetField subclasses:
 *   - api_url      (CWidgetFieldTextBox)  backend API URL, required (inline
 *                                          validation via FLAG_NOT_EMPTY).
 *   - chat_height  (CWidgetFieldTextBox)  chat area height.
 *   - accent_color (CWidgetFieldColor)    chat/theme accent color; renders the
 *                                          native palette color picker (Req 33.4).
 *
 * The widget id and namespace are unchanged (preserved in manifest.json).
 */
class WidgetForm extends CWidgetForm {

    public function addFields(): self {
        return $this
            ->addField(
                (new CWidgetFieldTextBox('api_url', _('Backend API URL')))
                    ->setDefault('http://localhost:5005')
                    ->setFlags(CWidgetField::FLAG_NOT_EMPTY)
            )
            ->addField(
                (new CWidgetFieldTextBox('chat_height', _('Chat height')))
                    ->setDefault('400')
            )
            ->addField(
                new CWidgetFieldColor('accent_color', _('Accent color'))
            );
    }
}
