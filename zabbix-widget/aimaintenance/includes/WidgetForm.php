<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Includes;

use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\CWidgetFieldTextBox;
use Zabbix\Widgets\CWidgetField;

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
            );
    }
}