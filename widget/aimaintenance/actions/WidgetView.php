<?php declare(strict_types = 1);

namespace Modules\AIMaintenance\Actions;

use CControllerDashboardWidgetView;
use CControllerResponseData;
use CSessionHelper;
use CWebUser;

class WidgetView extends CControllerDashboardWidgetView {

    protected function doAction(): void {
        // SECURITY: the backend authenticates every acting request against
        // Zabbix using the frontend SESSION id (user.checkAuthentication),
        // instead of trusting a client-supplied userid. We expose that session
        // id here so the widget JS can forward it to the backend, which asks
        // Zabbix "who owns this session?" and trusts ONLY that answer.
        //
        // The session id lives in the PHP session ($_SESSION['sessionid']) and
        // is retrieved with CSessionHelper::getId() — the same source the Zabbix
        // frontend itself uses for server/API calls (see CSystemInfoHelper,
        // CControllerQueue*). It is NOT reliably present in CWebUser::$data on a
        // normal authenticated request: on anything other than a fresh login,
        // CWebUser::$data is populated from API::User()->checkAuthentication(),
        // whose result does NOT include the 'sessionid' key — so reading
        // CWebUser::$data['sessionid'] yields null and the backend (correctly)
        // rejects the request with HTTP 401. CSessionHelper::getId() is the
        // authoritative source; keep the CWebUser value only as a last-resort
        // fallback (e.g. immediately after login).
        //
        // The sessionid is the user's session CREDENTIAL. It is passed to the
        // trusted backend ONLY. The backend MUST be reached over a trusted
        // channel (TLS/HTTPS via a reverse proxy, network-restricted to the
        // Zabbix frontend host); see the backend README "Security / secure
        // deployment" section. It is never displayed and never persisted.
        $sessionid = CSessionHelper::getId();
        if ($sessionid === '') {
            $sessionid = CWebUser::$data['sessionid'] ?? null;
        }

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
        'sessionid' => $sessionid
    ]));
    }
}
