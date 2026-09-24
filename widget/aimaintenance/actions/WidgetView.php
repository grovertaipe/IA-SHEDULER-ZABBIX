<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use CWebUser;

class WidgetView extends CControllerDashboardWidgetView {

    protected function doAction(): void {
        $this->setResponse(new CControllerResponseData([
        'name' => $this->getInput('name', $this->widget->getName()),
        'fields_values' => $this->fields_values,
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