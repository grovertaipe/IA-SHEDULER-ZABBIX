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
                'No data' => _('No data'),
                'Creating maintenance...' => _('Creating maintenance...'),
                'Processing request...' => _('Processing request...'),
                'System Status' => _('System Status'),
                'Could not verify backend connection' => _('Could not verify backend connection'),
                'Functions may be limited until connection is restored' => _('Functions may be limited until connection is restored'),
                'Templates are not available at this time' => _('Templates are not available at this time'),
                'Routine maintenance examples' => _('Routine maintenance examples'),
                'Daily' => _('Daily'),
                'Weekly' => _('Weekly'),
                'Monthly specific day' => _('Monthly specific day'),
                'Monthly weekday' => _('Monthly weekday')
            ]
        ];
    }
}
