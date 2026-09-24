"""Spanish message catalog — the product default and complete key set (Req 21.5).

``es`` is the default catalog: it is the authoritative, complete list of message
keys. Every other catalog (e.g. :mod:`i18n.catalogs.en`) mirrors these keys, and
:func:`i18n.messages.get_message` falls back to this catalog when a key is
missing elsewhere (Req 21.4, 21.6).

Templates use :meth:`str.format`-style ``{placeholders}``. Keys are grouped by
purpose: conversational responses, confirmation summaries and error messages.
"""

from __future__ import annotations

CATALOG: dict[str, str] = {
    # --- Conversational responses (Req 13, 21.1) ---
    "conversational.help": (
        "Puedo ayudarte a programar ventanas de mantenimiento en Zabbix. "
        "Indícame los hosts o grupos afectados, cuándo debe ocurrir "
        "(una vez, diario, semanal o mensual), la hora de inicio y la duración. "
        "Por ejemplo: «mantenimiento para el host web01 mañana de 22:00 a 23:00»."
    ),
    "conversational.off_topic": (
        "Solo puedo ayudarte con la programación de mantenimientos en Zabbix. "
        "Cuéntame qué ventana de mantenimiento necesitas crear."
    ),
    "conversational.clarification": (
        "Necesito algunos datos más para continuar. ¿Puedes precisar "
        "los hosts o grupos, la fecha/hora de inicio y la duración?"
    ),
    "conversational.maintenance_ready": (
        "He preparado tu mantenimiento. Revisa los detalles y confírmalo "
        "para crearlo en Zabbix."
    ),
    "conversational.clarification_recurrence": (
        "¿Con qué frecuencia debe ejecutarse el mantenimiento: una vez, "
        "diario, semanal o mensual?"
    ),
    "conversational.clarification_target": (
        "¿Sobre qué hosts o grupos de hosts debe aplicarse el mantenimiento?"
    ),
    "conversational.greeting": (
        "Hola, soy tu asistente de mantenimientos de Zabbix. "
        "¿Qué ventana de mantenimiento quieres programar?"
    ),
    # --- Confirmation summaries (Req 24.4, 24.5) ---
    "confirmation.maintenance_created": (
        "Mantenimiento «{name}» creado correctamente (ID {maintenance_id}). "
        "{summary}"
    ),
    "confirmation.summary": (
        "Se aplicará a {targets}. Programación: {schedule}. "
        "Inicio a las {start_time}, duración {duration}."
    ),
    "confirmation.hosts_not_found": (
        "No se encontraron los siguientes recursos: {missing}. "
        "El mantenimiento se creó para: {found}."
    ),
    # --- Error messages (Req 15.7, 21.1) ---
    "error.invalid_recurrence": (
        "El tipo de recurrencia «{value}» no es válido. "
        "Usa: una vez, diario, semanal o mensual."
    ),
    "error.duration_out_of_range": (
        "La duración indicada está fuera del rango permitido "
        "(entre {min_minutes} y {max_minutes} minutos)."
    ),
    "error.missing_host_or_group": (
        "Debes indicar al menos un host o un grupo de hosts para el mantenimiento."
    ),
    "error.host_not_found": (
        "No se encontró ningún host ni grupo que coincida con «{target}»."
    ),
    "error.unauthorized": (
        "No estás autorizado para realizar esta acción. "
        "Verifica tus credenciales de usuario."
    ),
    "error.ai_unavailable": (
        "El asistente de IA no está disponible en este momento. "
        "Inténtalo de nuevo más tarde."
    ),
    "error.rate_limited": (
        "Has superado el número de solicitudes permitidas. "
        "Espera unos momentos antes de volver a intentarlo."
    ),
    "error.invalid_request": (
        "La solicitud no es válida o le faltan datos obligatorios. "
        "Revisa la información e inténtalo de nuevo."
    ),
    "error.internal": (
        "Ocurrió un error inesperado al procesar tu solicitud. "
        "Inténtalo de nuevo más tarde."
    ),
}
