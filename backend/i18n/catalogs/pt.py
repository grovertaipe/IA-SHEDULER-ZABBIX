"""Portuguese message catalog — mirrors the default Spanish key set (Req 21.4).

``pt`` is an alternate catalog. It mirrors exactly the keys defined in the
default catalog (:mod:`i18n.catalogs.es`); any key missing here is resolved by
:func:`i18n.messages.get_message` via fallback to the default catalog (Req 21.4).

Templates use :meth:`str.format`-style ``{placeholders}``.
"""

from __future__ import annotations

CATALOG: dict[str, str] = {
    # --- Conversational responses (Req 13, 21.1) ---
    "conversational.help": (
        "Posso ajudar você a agendar janelas de manutenção no Zabbix. "
        "Informe os hosts ou grupos afetados, quando deve ocorrer "
        "(uma vez, diário, semanal ou mensal), o horário de início e a duração. "
        "Por exemplo: \"manutenção para o host web01 amanhã das 22:00 às 23:00\"."
    ),
    "conversational.off_topic": (
        "Só posso ajudar você com o agendamento de manutenções no Zabbix. "
        "Diga-me qual janela de manutenção você precisa criar."
    ),
    "conversational.clarification": (
        "Preciso de mais alguns dados para continuar. Você pode especificar "
        "os hosts ou grupos, a data/hora de início e a duração?"
    ),
    "conversational.maintenance_ready": (
        "Preparei sua manutenção. Revise os detalhes e confirme "
        "para criá-la no Zabbix."
    ),
    "conversational.clarification_recurrence": (
        "Com que frequência a manutenção deve ser executada: uma vez, "
        "diário, semanal ou mensal?"
    ),
    "conversational.clarification_target": (
        "A quais hosts ou grupos de hosts a manutenção deve ser aplicada?"
    ),
    "conversational.greeting": (
        "Olá, sou seu assistente de manutenções do Zabbix. "
        "Qual janela de manutenção você quer agendar?"
    ),
    # --- Confirmation summaries (Req 24.4, 24.5) ---
    "confirmation.maintenance_created": (
        "Manutenção \"{name}\" criada com sucesso (ID {maintenance_id}). "
        "{summary}"
    ),
    "confirmation.summary": (
        "Será aplicada a {targets}. Programação: {schedule}. "
        "Início às {start_time}, duração {duration}."
    ),
    "confirmation.hosts_not_found": (
        "Os seguintes recursos não foram encontrados: {missing}. "
        "A manutenção foi criada para: {found}."
    ),
    # --- Error messages (Req 15.7, 21.1) ---
    "error.invalid_recurrence": (
        "O tipo de recorrência \"{value}\" não é válido. "
        "Use: uma vez, diário, semanal ou mensal."
    ),
    "error.duration_out_of_range": (
        "A duração informada está fora do intervalo permitido "
        "(entre {min_minutes} e {max_minutes} minutos)."
    ),
    "error.missing_host_or_group": (
        "Você deve indicar ao menos um host ou grupo de hosts para a manutenção."
    ),
    "error.host_not_found": (
        "Nenhum host ou grupo correspondente a \"{target}\" foi encontrado."
    ),
    "error.unauthorized": (
        "Você não está autorizado a realizar esta ação. "
        "Verifique suas credenciais de usuário."
    ),
    "error.ai_unavailable": (
        "O assistente de IA não está disponível no momento. "
        "Tente novamente mais tarde."
    ),
    "error.rate_limited": (
        "Você excedeu o número de solicitações permitidas. "
        "Aguarde alguns instantes antes de tentar novamente."
    ),
    "error.invalid_request": (
        "A solicitação é inválida ou faltam dados obrigatórios. "
        "Revise as informações e tente novamente."
    ),
    "error.internal": (
        "Ocorreu um erro inesperado ao processar sua solicitação. "
        "Tente novamente mais tarde."
    ),
}
