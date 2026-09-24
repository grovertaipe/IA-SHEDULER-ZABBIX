"""Validación de la respuesta de IA contra el ``Esquema_JSON`` (Req 29).

La respuesta cruda del proveedor de IA (el contrato :class:`ExtractedRequest`
serializado a ``dict``) se valida contra un JSON Schema formal
(:data:`EXTRACTED_REQUEST_SCHEMA`, Draft 2020-12). La **decisión** de si una
respuesta es conforme es una función pura y determinista
(:func:`validate_against_schema`): no realiza E/S, no depende de Flask ni de la
red y no invoca el cálculo de bitmasks (Req 29.4). El ``FailoverAIProvider``
(Task 21.x) consume esta decisión pura para reintentar hasta
``ai_schema_max_attempts`` antes de fallar (Req 29.2, 29.3).

El esquema marca ``intent`` como obligatorio y restringe ``recurrence_type`` al
enum soportado (``once``/``daily``/``weekly``/``monthly``), tipa
``hosts``/``groups``/``trigger_tags``/``ticket``/``recurrence`` y —de forma
aditiva (Req 32)— ``problem_tags``/``tags_evaltype``/``maintenance_type``. Es
permisivo con los campos opcionales pero estricto en el tipo obligatorio de
``intent`` y en los tipos JSON de arrays/objetos.
"""

from __future__ import annotations

from collections.abc import Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

# Los cuatro tipos de recurrencia soportados (Req 4-8). Coincide con
# ``core.domain.RecurrenceType`` sin importarlo, para mantener el esquema como
# un dato JSON puro y auto-contenido.
_RECURRENCE_TYPES: list[str] = ["once", "daily", "weekly", "monthly"]

# --------------------------------------------------------------------------- #
# Esquema del subobjeto de recurrencia (ExtractedRecurrence, Req 3.2)         #
# --------------------------------------------------------------------------- #
_RECURRENCE_SCHEMA: dict = {
    # Acepta objeto o null. ``properties``/``required`` solo aplican cuando la
    # instancia es un objeto (Draft 2020-12), por lo que null es válido y los
    # errores de subcampo (p. ej. ``recurrence_type`` fuera del enum) afloran
    # con su ruta completa en lugar de quedar ocultos bajo un ``oneOf``.
    "type": ["object", "null"],
    "properties": {
        # Restringido al enum soportado (Req 29.1). Obligatorio dentro de la
        # recurrencia: si hay recurrencia, debe declarar su tipo.
        "recurrence_type": {"type": "string", "enum": _RECURRENCE_TYPES},
        "days": {"type": "array", "items": {"type": "string"}},
        "months": {"type": "array", "items": {"type": "string"}},
        "occurrences": {"type": "array", "items": {"type": "string"}},
        "day_of_month": {"type": ["integer", "null"]},
        "start_hour": {"type": ["integer", "null"]},
        "duration_hours": {"type": ["number", "null"]},
        "every": {"type": ["integer", "null"]},
        # ISO YYYY-MM-DD resolved calendar date for a ``once`` maintenance, or
        # null. The backend computes the epochs from it (Req 3.2); the date
        # format itself is validated in the recurrence engine, not here.
        "start_date": {"type": ["string", "null"]},
        "start_ts": {"type": ["integer", "null"]},
        "end_ts": {"type": ["integer", "null"]},
    },
    "required": ["recurrence_type"],
    "additionalProperties": True,
}

# --------------------------------------------------------------------------- #
# Esquema de un tag de problema (ProblemTag, Req 32.2)                        #
# --------------------------------------------------------------------------- #
_PROBLEM_TAG_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tag": {"type": "string"},
        "value": {"type": "string"},
        "operator": {"type": "integer"},
    },
    "required": ["tag"],
    "additionalProperties": True,
}

# --------------------------------------------------------------------------- #
# Esquema completo del contrato de IA (ExtractedRequest, Req 29.1)            #
# --------------------------------------------------------------------------- #
EXTRACTED_REQUEST_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        # Único campo obligatorio del contrato (Req 29.1, 13).
        "intent": {"type": "string"},
        # Respuesta conversacional en el idioma del usuario (prosa, opcional):
        # texto libre que el backend prefiere sobre el catálogo i18n. No es
        # obligatorio, por lo que el esquema valida con o sin él.
        "assistant_message": {"type": "string"},
        "hosts": {"type": "array", "items": {"type": "string"}},
        "groups": {"type": "array", "items": {"type": "string"}},
        # trigger_tags: descubrimiento de hosts (Req 14.4), lista de objetos.
        "trigger_tags": {"type": "array", "items": {"type": "object"}},
        # Aditivo (Req 32): supresión de problemas del mantenimiento.
        "problem_tags": {"type": "array", "items": _PROBLEM_TAG_SCHEMA},
        "tags_evaltype": {"type": "integer"},
        "maintenance_type": {"type": "integer"},
        "ticket": {"type": ["string", "null"]},
        "recurrence": _RECURRENCE_SCHEMA,
        "raw_message": {"type": "string"},
    },
    "required": ["intent"],
    "additionalProperties": True,
}


def _error_field_path(error: ValidationError) -> str:
    """Traduce un error de validación a una ruta de campo legible.

    - Para un campo obligatorio ausente, la ruta apunta al campo faltante
      (``error.absolute_path`` está vacía en la raíz, por lo que se toma el
      nombre del campo desde ``error.validator_value`` cuando es posible).
    - En el resto de casos se usa ``json_path`` (p. ej. ``$.recurrence.recurrence_type``)
      recortando el prefijo ``$.``/``$`` para obtener una ruta con puntos.
    """
    # 'required' reporta el error en el objeto contenedor; el campo concreto
    # ausente viaja en el mensaje. Reconstruimos la ruta al campo faltante.
    if error.validator == "required":
        missing = _missing_required_field(error)
        prefix = _dotted_prefix(error.absolute_path)
        if missing is not None:
            return f"{prefix}.{missing}" if prefix else missing

    json_path = getattr(error, "json_path", "$")
    if json_path.startswith("$."):
        return json_path[2:]
    if json_path == "$":
        return "$"
    return json_path.lstrip("$")


def _missing_required_field(error: ValidationError) -> str | None:
    """Extrae el nombre del campo obligatorio ausente de un error 'required'."""
    # jsonschema no expone el campo faltante como atributo estructurado, pero
    # sí como texto entre comillas: "'intent' is a required property".
    message = error.message
    if "'" in message:
        return message.split("'", 2)[1]
    return None


def _dotted_prefix(absolute_path: Iterable[object]) -> str:
    """Convierte una ruta absoluta de jsonschema en un prefijo con puntos."""
    return ".".join(str(part) for part in absolute_path)


def validate_against_schema(
    response: dict, schema: dict = EXTRACTED_REQUEST_SCHEMA
) -> tuple[bool, list[str]]:
    """Valida ``response`` contra ``schema`` (Req 29.4). Función PURA.

    Recolecta TODOS los errores de validación (``iter_errors``) y mapea cada
    uno a la ruta del campo que incumple.

    Returns:
        ``(True, [])`` si la respuesta es conforme al esquema; en caso
        contrario ``(False, campos)`` donde ``campos`` es la lista no vacía de
        rutas de los campos que incumplen (campo obligatorio ausente, tipo
        incorrecto o valor fuera del enum).
    """
    validator = Draft202012Validator(schema)
    offending_fields: list[str] = []
    for error in validator.iter_errors(response):
        offending_fields.append(_error_field_path(error))
    if offending_fields:
        return (False, offending_fields)
    return (True, [])
