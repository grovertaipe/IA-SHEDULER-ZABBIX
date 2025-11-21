<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use CWebUser;
use CCsrfTokenHelper;

class WidgetView extends CControllerDashboardWidgetView {

    protected function init(): void {
        parent::init();
        
        // Habilitar protección CSRF para este widget
        $this->disableCsrfValidation();
    }

    protected function checkInput(): bool {
        $fields = [
            'name' => 'string',
            'fields_values' => 'array'
        ];

        $ret = $this->validateInput($fields);

        if (!$ret) {
            $this->setResponse(
                new CControllerResponseData(['main_block' => json_encode([
                    'error' => 'Invalid input parameters'
                ])])
            );
        }

        return $ret;
    }

    protected function checkPermissions(): bool {
        // Verificar que el usuario tiene permisos para usar el widget
        return parent::checkPermissions() && 
               CWebUser::getType() >= USER_TYPE_ZABBIX_USER;
    }

    protected function doAction(): void {
        // Generar token CSRF para las requests del widget
        $csrf_token = CCsrfTokenHelper::get('widget');
        
        $this->setResponse(new CControllerResponseData([
            'name' => $this->getInput('name', $this->widget->getName()),
            'fields_values' => $this->fields_values,
            'csrf_token' => $csrf_token,
            'user_info' => [
                'userid'   => CWebUser::$data['userid']   ?? null,
                'username' => CWebUser::$data['username'] ?? null,
                'name'     => CWebUser::$data['name']     ?? null,
                'surname'  => CWebUser::$data['surname']  ?? null,
                'roleid'   => CWebUser::$data['roleid']   ?? null,
                'debug_mode' => $this->getDebugMode()
            ]
        ]));
    }
}