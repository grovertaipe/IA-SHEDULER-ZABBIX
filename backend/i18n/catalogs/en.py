"""English message catalog — mirrors the default Spanish key set (Req 21.4).

``en`` is an alternate catalog. It mirrors exactly the keys defined in the
default catalog (:mod:`i18n.catalogs.es`); any key missing here is resolved by
:func:`i18n.messages.get_message` via fallback to the default catalog (Req 21.4).

Templates use :meth:`str.format`-style ``{placeholders}``.
"""

from __future__ import annotations

CATALOG: dict[str, str] = {
    # --- Conversational responses (Req 13, 21.1) ---
    "conversational.help": (
        "I can help you schedule maintenance windows in Zabbix. "
        "Tell me the affected hosts or groups, when it should happen "
        "(once, daily, weekly or monthly), the start time and the duration. "
        "For example: \"maintenance for host web01 tomorrow from 22:00 to 23:00\"."
    ),
    "conversational.off_topic": (
        "I can only help you schedule maintenance windows in Zabbix. "
        "Let me know which maintenance window you need to create."
    ),
    "conversational.clarification": (
        "I need a bit more information to continue. Could you specify "
        "the hosts or groups, the start date/time and the duration?"
    ),
    "conversational.maintenance_ready": (
        "I've prepared your maintenance. Review the details and confirm it "
        "to create it in Zabbix."
    ),
    "conversational.clarification_recurrence": (
        "How often should the maintenance run: once, daily, weekly or monthly?"
    ),
    "conversational.clarification_target": (
        "Which hosts or host groups should the maintenance apply to?"
    ),
    "conversational.greeting": (
        "Hi, I'm your Zabbix maintenance assistant. "
        "Which maintenance window would you like to schedule?"
    ),
    # --- Confirmation summaries (Req 24.4, 24.5) ---
    "confirmation.maintenance_created": (
        "Maintenance \"{name}\" created successfully (ID {maintenance_id}). "
        "{summary}"
    ),
    "confirmation.summary": (
        "It will apply to {targets}. Schedule: {schedule}. "
        "Starting at {start_time}, duration {duration}."
    ),
    "confirmation.hosts_not_found": (
        "The following resources were not found: {missing}. "
        "The maintenance was created for: {found}."
    ),
    # Localized creation-confirmation message (Req 21.1). Structured, precise
    # fields (NOT free AI text) assembled post-action by the api layer.
    "confirmation.created_message": (
        "Maintenance created successfully!\n\n"
        "Details:\n"
        "• Name: {name}\n"
        "• Hosts affected: {hosts_affected}\n"
        "• Groups affected: {groups_affected}\n"
    ),
    "confirmation.line_routine": "• Type: Routine ({recurrence_type})\n",
    "confirmation.line_ticket": "• Ticket: {ticket}\n",
    "confirmation.line_requested_by": "• Requested by: {user}\n",
    "confirmation.footer_active": "\nThe maintenance is active and running.",
    # --- Error messages (Req 15.7, 21.1) ---
    "error.invalid_recurrence": (
        "The recurrence type \"{value}\" is not valid. "
        "Use: once, daily, weekly or monthly."
    ),
    "error.duration_out_of_range": (
        "The given duration is outside the allowed range "
        "(between {min_minutes} and {max_minutes} minutes)."
    ),
    "error.missing_host_or_group": (
        "You must provide at least one host or host group for the maintenance."
    ),
    "error.host_not_found": (
        "No host or group matching \"{target}\" was found."
    ),
    "error.unauthorized": (
        "You are not authorized to perform this action. "
        "Please check your user credentials."
    ),
    "error.ai_unavailable": (
        "The AI assistant is unavailable right now. Please try again later."
    ),
    "error.rate_limited": (
        "You have exceeded the number of allowed requests. "
        "Please wait a moment before trying again."
    ),
    "error.invalid_request": (
        "The request is invalid or missing required data. "
        "Please review the information and try again."
    ),
    "error.internal": (
        "An unexpected error occurred while processing your request. "
        "Please try again later."
    ),
}
