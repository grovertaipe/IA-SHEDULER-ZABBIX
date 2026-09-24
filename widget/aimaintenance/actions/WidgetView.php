<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use CWebUser;

class WidgetView extends CControllerDashboardWidgetView {

    protected function doAction(): void {
        // SECURITY: the backend now authenticates every acting request against
        // Zabbix using the frontend SESSION id (user.checkAuthentication),
        // instead of trusting a client-supplied userid. In Zabbix 7.2 the
        // logged-in frontend session token lives in CWebUser::$data['sessionid'].
        // We expose it here so the widget JS can send it to the backend, which
        // asks Zabbix "who owns this session?" and trusts ONLY that answer.
        //
        // The sessionid is the user's session CREDENTIAL. It is passed to the
        // trusted backend ONLY. The backend MUST be reached over a trusted
        // channel (TLS/HTTPS via a reverse proxy, network-restricted to the
        // Zabbix frontend host); see the backend README "Security / secure
        // deployment" section. It is never displayed and never persisted.
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
        ],
        // The verified-session credential used for backend authentication.
        'sessionid' => CWebUser::$data['sessionid'] ?? null
    ]));
    }
}