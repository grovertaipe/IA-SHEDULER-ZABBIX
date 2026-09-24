"""Prompt externalizado del Proveedor_IA (Req 3).

Principio de diseño "la IA extrae, el backend calcula" (Req 3.2): el prompt pide
al modelo que devuelva **datos estructurados** (conjuntos de NOMBRES de días,
meses y ocurrencias, hora de inicio, duración en horas, hosts, grupos, ticket,
tipo de recurrencia e intención) y **no** contiene ninguna aritmética de
bitmasks (Req 3.1). Esto reemplaza el prompt monolítico legado
(``backend/main.py::_build_interactive_prompt``, ~330 líneas plagadas de sumas
de bitmasks) por una versión corta orientada a la reducción de tokens (Req 3.4).

Task 8.1 scope (implemented here):
    * :func:`build_prompt_context` — construye un :class:`~core.domain.PromptContext`
      con ``today_iso`` / ``tomorrow_iso`` en ISO 8601 (``YYYY-MM-DD``) a partir de
      una fecha base **inyectable** (por defecto ``date.today()``) para ser
      determinista y testeable (Req 3.6, 13.6);
    * :data:`PROMPT_TEMPLATE` — la plantilla del prompt cargada desde un recurso
      externalizado (``prompt_template.txt``) (Req 3.3);
    * :func:`build_prompt` — ensambla la plantilla + fechas inyectadas + como
      máximo 5 ejemplos (uno por tipo de recurrencia) + el mensaje del usuario
      (Req 3.5).

Todas las funciones son puras/deterministas dada la fecha base; no se invoca
``datetime.now()`` en lo profundo de la lógica (Req 3.6).

Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 13.6.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from core.domain import ConversationTurn, PromptContext

#: Placeholder text rendered when no prior conversation history is provided, so
#: the template still formats cleanly and the model knows there is no context.
_EMPTY_HISTORY = "(sin historial previo)"

#: Role labels for the compact transcript rendered into the prompt. A turn whose
#: role is not exactly ``"assistant"`` is labeled as the user (defensive: the
#: history is normalized upstream, but the transcript never mislabels a turn).
_ROLE_LABELS: dict[str, str] = {"user": "Usuario", "assistant": "Asistente"}

#: Recurso externalizado con la plantilla del prompt (Req 3.3).
_TEMPLATE_PATH = Path(__file__).with_name("prompt_template.txt")

#: Plantilla del Prompt_IA cargada desde el recurso externalizado (Req 3.3).
#:
#: Usa marcadores de una sola llave ``{today_iso}`` / ``{tomorrow_iso}`` /
#: ``{conversation_history}`` / ``{user_message}`` y llaves dobles ``{{`` /
#: ``}}`` para el JSON literal, de modo que se resuelve con :meth:`str.format`.
PROMPT_TEMPLATE: str = _TEMPLATE_PATH.read_text(encoding="utf-8")


def build_prompt_context(base_date: date | None = None) -> PromptContext:
    """Construye el :class:`~core.domain.PromptContext` para una fecha base.

    La fecha base es **inyectable** (por defecto ``date.today()``) para mantener
    la función determinista y testeable: no se llama a ``datetime.now()`` en lo
    profundo de la lógica (Req 3.6). ``today_iso`` es la fecha base y
    ``tomorrow_iso`` es el día siguiente, ambos en ISO 8601 ``YYYY-MM-DD``
    (Req 3.6, 13.6).

    Args:
        base_date: la fecha considerada "hoy". Por defecto ``date.today()``.

    Returns:
        Un :class:`PromptContext` con ``today_iso`` / ``tomorrow_iso`` en ISO 8601.
    """
    today = base_date if base_date is not None else date.today()
    tomorrow = today + timedelta(days=1)
    return PromptContext(
        today_iso=today.isoformat(),
        tomorrow_iso=tomorrow.isoformat(),
    )


def _escape_braces(text: str) -> str:
    """Double any ``{`` / ``}`` so the text survives :meth:`str.format`.

    The prompt template is filled with :meth:`str.format`, where ``{`` / ``}``
    are meta-characters (single braces start a replacement field, and the
    template already doubles them for its literal JSON). The transcript we build
    from the user-supplied conversation is spliced INTO the template as one
    ``{conversation_history}`` value; a stray ``{`` or ``}`` inside a user turn
    would otherwise be re-interpreted as a replacement field and make
    ``str.format`` raise. Doubling the braces here keeps the format call robust
    regardless of what the user typed. Pure and deterministic.
    """
    return text.replace("{", "{{").replace("}", "}}")


def render_history(history: list[ConversationTurn] | None) -> str:
    """Render prior conversation turns into a compact role-labeled transcript.

    Produces lines like ``Usuario: ...`` / ``Asistente: ...`` (oldest-first) so
    the model sees the accumulated maintenance context before the current
    message. Empty/absent history yields :data:`_EMPTY_HISTORY` so the template
    still formats cleanly. Blank-content turns are skipped. Braces in the turn
    content are escaped (see :func:`_escape_braces`) so the resulting string is
    safe to splice into the :meth:`str.format` template. Pure and deterministic.
    """
    if not history:
        return _EMPTY_HISTORY

    lines: list[str] = []
    for turn in history:
        content = (turn.content or "").strip()
        if not content:
            continue
        label = _ROLE_LABELS.get(turn.role, _ROLE_LABELS["user"])
        lines.append(f"{label}: {content}")

    if not lines:
        return _EMPTY_HISTORY
    return _escape_braces("\n".join(lines))


def build_prompt(
    user_message: str,
    ctx: PromptContext,
    history: list[ConversationTurn] | None = None,
) -> str:
    """Ensambla el Prompt_IA final para un mensaje de usuario.

    Combina la plantilla externalizada (Req 3.3) con las fechas inyectadas del
    ``ctx`` (Req 3.6) y el mensaje del usuario. La plantilla ya incluye como
    máximo 5 ejemplos, uno por tipo de recurrencia (``once``, ``daily``,
    ``weekly``, ``monthly`` por día del mes y ``monthly`` por día de la semana),
    y su salida es **estructurada** (nombres/horas), sin ninguna aritmética de
    bitmasks (Req 3.1, 3.5).

    ``history`` (opcional) son los turnos previos del MISMO mantenimiento en
    curso, del más antiguo al más reciente, que el widget reenvía en cada
    llamada para que el backend, que es sin estado, acumule los datos entre
    mensajes. Se renderizan como una transcripción compacta ``Usuario:`` /
    ``Asistente:`` ANTES del mensaje actual (:func:`render_history`); las llaves
    del contenido del usuario se escapan para que :meth:`str.format` no falle.
    Cuando ``history`` está vacío/ausente el resultado es idéntico al de una
    extracción de un solo mensaje.

    Función pura: el resultado depende únicamente de ``user_message``, ``ctx`` e
    ``history``.

    Args:
        user_message: el mensaje original del usuario a analizar.
        ctx: el contexto con ``today_iso`` / ``tomorrow_iso`` en ISO 8601.
        history: turnos previos del mismo mantenimiento (o ``None``).

    Returns:
        El prompt completo listo para enviar al proveedor de IA.
    """
    return PROMPT_TEMPLATE.format(
        today_iso=ctx.today_iso,
        tomorrow_iso=ctx.tomorrow_iso,
        conversation_history=render_history(history),
        user_message=user_message,
    )
