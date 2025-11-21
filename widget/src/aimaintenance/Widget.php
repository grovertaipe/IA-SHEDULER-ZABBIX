<?php declare(strict_types = 1);

namespace Modules\AIMaintenance;

use Zabbix\Core\CWidget;

class Widget extends CWidget {
    public function getDefaultWidth(): int {
        return 6; // Ancho por defecto del widget
    }

    public function getDefaultHeight(): int {
        return 5; // Alto por defecto del widget
    }

    public function getTranslationStrings(): array {
        return [
            'class.widget.js' => [
                'Send message' => _('Send message'),
                'Processing...' => _('Processing...'),
                'Confirm maintenance' => _('Confirm maintenance'),
                'Error' => _('Error'),
                'No data' => _('No data')
            ]
        ];
    }
}
