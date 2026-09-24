# Implementation Plan

## Overview

Este plan convierte el diseño de **zabbix-ai-maintenance-v2** en una serie de tareas de codificación incrementales y guiadas por pruebas. La estrategia es construir primero el **núcleo puro** (motor de recurrencia + utilidades de dominio) junto a sus pruebas basadas en propiedades, luego la **abstracción del proveedor de IA** con el prompt externalizado, después el **cliente Zabbix**, los **servicios de orquestación**, la **capa HTTP / app factory**, el **oráculo de paridad** con las pruebas exhaustivas de regresión, el **empaquetado Docker / CI**, y finalmente la **separación de carpetas backend/widget** y la reubicación del widget.

Cada tarea se apoya en las anteriores y termina integrándose en el sistema; no queda código huérfano. Las sub-tareas de pruebas marcadas con `*` son opcionales (unitarias, de propiedad, de integración). Lenguaje de implementación: **Python 3.11+ / Flask** (definido explícitamente en el diseño; sin pseudocódigo), con **pytest + Hypothesis**, **pytest-cov**, **ruff** y **mypy**.

Cada test de propiedad DEBE incluir la etiqueta obligatoria en el formato:
`# Feature: zabbix-ai-maintenance-v2, Property {n}: {property_text}`

Referencias:
- Monolito legado: `backend/main.py` (~1600 líneas) — fuente del oráculo de paridad.
- Widget existente: `zabbix-widget/aimaintenance/` — se reubicará en `widget/aimaintenance/`.

## Tasks

- [x] 1. Preparar la estructura del proyecto backend y las dependencias
  - Crear el paquete `backend/` con `app.py`, `config.py`, y los subpaquetes `api/`, `services/`, `ai/`, `core/`, `zabbix/`, `tests/` (con `__init__.py`).
  - Crear `backend/tests/` con subcarpetas `unit/`, `property/`, `integration/`, `fixtures/` y `conftest.py`.
  - Definir `backend/requirements.txt` con versiones fijadas (flask, requests, proveedores de IA, hypothesis, pytest, pytest-cov, ruff, mypy).
  - Configurar `pyproject.toml`/`pytest.ini` para pytest, ruff y mypy sobre `backend/`.
  - _Requirements: 1.1, 1.6, 20.x (infraestructura de pruebas)_

- [x] 2. Implementar los modelos de datos del dominio
  - [x] 2.1 Definir los modelos de datos en `core/domain.py` (parte de tipos) y/o `core/models.py`
    - `RecurrenceType` (enum), `UserInfo`, `PromptContext`, `ExtractedRecurrence`, `ExtractedRequest` (sin bitmasks precalculados), `RecurrenceConfig`, `TimePeriod`, `MaintenanceWindow`, `RecurrenceError(field, message)`.
    - **Aditivo (Req 32):** definir `TagOperator` (enum: `EQUALS = 0`, `CONTAINS = 2`), `TagsEvalType` (enum: `AND_OR = 0`, `OR = 2`) y `ProblemTag(tag, value="", operator=TagOperator.CONTAINS)`; extender `ExtractedRequest` con `problem_tags: list[ProblemTag]`, `tags_evaltype: int` (def. `TagsEvalType.AND_OR`) y `maintenance_type: int` (def. 0); extender `MaintenancePayload`/`MaintenanceWindow` con `maintenance_type`, `tags: list[ProblemTag]` y `tags_evaltype`. Mantener la distinción explícita frente a `trigger_tags` (solo descubrimiento de hosts, Req 14.4).
    - _Requirements: 1.4, 3.2, 20.1, 32.1, 32.2, 32.3_

- [x] 3. Implementar el Motor_Recurrencia como funciones puras (cálculo de bitmasks y tiempo)
  - [x] 3.1 Implementar el cálculo de bitmasks y conversiones de tiempo en `core/recurrence.py`
    - `compute_day_bitmask` (suma, 1..127, rechaza vacío), `compute_month_bitmask` (suma, 1..4095, rechaza vacío), `compute_week_occurrence` (suma, 1..5), tablas `DAY_VALUES`/`MONTH_VALUES`/`OCCURRENCE_VALUES`.
    - `hours_to_seconds_from_midnight` (0..23 → *3600), `duration_hours_to_seconds` (>0 → *3600).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8_

  - [ ]* 3.2 Escribir test de propiedad para el bitmask de días
    - **Property 1: Bitmask de días como suma de valores**
    - **Validates: Requirements 2.1, 2.6**

  - [ ]* 3.3 Escribir test de propiedad para el bitmask de meses
    - **Property 2: Bitmask de meses como suma de valores**
    - **Validates: Requirements 2.2, 2.6**

  - [ ]* 3.4 Escribir test de propiedad para la ocurrencia de semana
    - **Property 3: Ocurrencia de semana como suma de valores**
    - **Validates: Requirements 2.3, 2.6**

  - [ ]* 3.5 Escribir test de propiedad para las conversiones de tiempo
    - **Property 4: Conversión de tiempo a segundos**
    - **Validates: Requirements 2.4, 2.5**

  - [x] 3.6 Implementar la validación de bitmasks precalculados y de tiempo en `core/recurrence.py`
    - `validate_day_bitmask` (1..127), `validate_month_bitmask` (1..4095), `validate_week_occurrence` (1..5); rechazo con `RecurrenceError` fuera de rango.
    - Rechazo de hora fuera de 0..23 y duración ≤ 0 con `RecurrenceError` de tiempo inválido.
    - _Requirements: 2.7, 2.9, 6.5, 7.5_

  - [ ]* 3.7 Escribir test de propiedad para la validación de rango de bitmasks
    - **Property 5: Validación de rango de bitmasks precalculados**
    - **Validates: Requirements 2.7, 6.5, 7.5**

  - [ ]* 3.8 Escribir test de propiedad para el rechazo de tiempo inválido
    - **Property 6: Rechazo de tiempo inválido**
    - **Validates: Requirements 2.9**

- [x] 4. Implementar la construcción del TimePeriod (despacho por tipo de recurrencia)
  - [x] 4.1 Implementar `build_timeperiod` con el despacho once/daily/weekly/monthly en `core/recurrence.py`
    - `once` → `timeperiod_type=0`, `start_date`, `period=fin−inicio`, ventana `active_since/active_till`; rechazo si fin ≤ inicio.
    - `daily` → `timeperiod_type=2`, `start_time`, `period`, `every` (def. 1).
    - `weekly` → `timeperiod_type=3`, `dayofweek` (Bitmask_Dias), `start_time`, `period`, `every` (def. 1).
    - `monthly` por día del mes → `timeperiod_type=4`, `day`, `month` (def. 4095), `start_time`, `period`, `every`; rechazo si día fuera de 1..31.
    - `monthly` por día de semana → `timeperiod_type=4`, `dayofweek`, `every`=Ocurrencia_Semana (def. 1), `month`, `start_time`, `period`.
    - Exclusividad mensual (ambos campos → error) y ausencia de ambos → error de dato faltante.
    - Validación previa de tipo, `start_time` y `duration` con mensajes específicos de `RecurrenceError`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.4, 6.1, 6.2, 6.3, 6.6, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 4.2 Escribir test de propiedad para el mapeo del mantenimiento único
    - **Property 9: Mapeo del mantenimiento único (once)**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

  - [ ]* 4.3 Escribir test de propiedad para el mapeo del mantenimiento diario
    - **Property 10: Mapeo del mantenimiento diario (daily)**
    - **Validates: Requirements 5.1, 5.2, 5.4**

  - [ ]* 4.4 Escribir test de propiedad para el mapeo del mantenimiento semanal
    - **Property 11: Mapeo del mantenimiento semanal (weekly)**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.6**

  - [ ]* 4.5 Escribir test de propiedad para el mapeo mensual por día del mes
    - **Property 12: Mapeo del mantenimiento mensual por día del mes**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

  - [ ]* 4.6 Escribir test de propiedad para el mapeo mensual por día de la semana
    - **Property 13: Mapeo del mantenimiento mensual por día de la semana**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.6**

  - [ ]* 4.7 Escribir test de propiedad para la exclusividad mutua mensual
    - **Property 14: Exclusividad mutua de la configuración mensual**
    - **Validates: Requirements 8.4**

  - [ ]* 4.8 Escribir test de propiedad para el rechazo de tipo de recurrencia inválido
    - **Property 15: Rechazo de tipo de recurrencia inválido**
    - **Validates: Requirements 9.1**

  - [ ]* 4.9 Escribir tests unitarios por ejemplo y edge cases del Motor_Recurrencia
    - Un caso representativo por tipo (once/daily/weekly/monthly-dom/monthly-dow); conjuntos vacíos; falta de `start_time`/`duration`/config.
    - _Requirements: 2.8, 5.3, 6.4, 8.5, 9.2, 9.3, 9.4, 20.5_

  - [x] 4.10 Implementar la validación de rango de duración y el redondeo a minuto en `core/recurrence.py` (Req 31)
    - Definir `PERIOD_MIN_SECONDS = 300` y `PERIOD_MAX_SECONDS = 86399940`; implementar `validate_period_seconds(period) -> int`: función pura y determinista que devuelve `period` si `300 <= period <= 86399940` y en caso contrario lanza `RecurrenceError("period", ...)` de "duración fuera de rango" (Req 31.1, 31.2, 31.4).
    - Implementar `floor_to_minute(seconds) -> int`: función pura auxiliar que devuelve el mayor múltiplo de 60 ≤ `seconds` (`seconds - seconds % 60`), consistente con el redondeo interno de Zabbix e idempotente (Req 31.3).
    - Cablear `validate_period_seconds` dentro de `build_timeperiod` (tarea 4.1) para TODO periodo (once y recurrente), y aplicar `floor_to_minute` a `active_since`/`active_till`/`period`/`start_date`/`start_time` de forma consistente. No introduce E/S ni ramifica la paridad del núcleo.
    - _Requirements: 31.1, 31.2, 31.3, 31.4_

  - [x] 4.11 Implementar la validación de tags de problema en `core/recurrence.py` (Req 32)
    - Definir `TAGS_EVALTYPE_VALUES = {0, 2}` y `TAG_OPERATOR_VALUES = {0, 2}`; implementar `validate_problem_tags(problem_tags, tags_evaltype, maintenance_type) -> None`: función pura y determinista.
    - Rechazar con `RecurrenceError("problem_tags", ...)` si `problem_tags` no está vacía y `maintenance_type == 1` (los tags solo se permiten con `maintenance_type == 0`, Req 32.3); rechazar `tags_evaltype ∉ {0, 2}` con `RecurrenceError("tags_evaltype", ...)` (Req 32.5) y `operator ∉ {0, 2}` de cualquier tag con `RecurrenceError("operator", ...)` (Req 32.6). Lista de tags vacía es válida con cualquier `maintenance_type` válido (supresión de todos los problemas por defecto, Req 32.4). Sin E/S.
    - _Requirements: 32.3, 32.4, 32.5, 32.6_

  - [ ]* 4.12 Escribir test de propiedad para la frontera del rango de duración
    - **Property 37: Frontera del rango de duración (period)**
    - **Validates: Requirements 31.1, 31.2, 31.4**

  - [ ]* 4.13 Escribir test de propiedad para el redondeo a minuto idempotente y correcto
    - **Property 39: Redondeo a minuto idempotente y correcto**
    - **Validates: Requirements 31.3**

  - [ ]* 4.14 Escribir test de propiedad para los tags de problema según maintenance_type
    - **Property 38: Tags de problema solo con maintenance_type = 0**
    - **Validates: Requirements 32.3, 32.4**

- [x] 5. Implementar las utilidades de dominio (tickets, nombres, descripciones, decode)
  - [x] 5.1 Implementar tickets, nombres y descripciones en `core/domain.py`
    - `extract_ticket` (formato `XXX-XXXXXX`, prefijos `ticket:`/`#`), `generate_maintenance_name` (ticket como componente principal), `generate_maintenance_description` (ticket en línea propia sin duplicar + datos de usuario).
    - _Requirements: 10.1, 10.2, 10.4, 10.5, 11.4_

  - [x] 5.2 Implementar la decodificación de bitmasks en `core/domain.py`
    - `decode_days` (Bitmask_Dias → 7 nombres), `decode_months` (Bitmask_Meses → 12 nombres).
    - _Requirements: 20.6_

  - [ ]* 5.3 Escribir test de propiedad para la extracción de tickets
    - **Property 16: Extracción de tickets**
    - **Validates: Requirements 10.1, 10.2**

  - [ ]* 5.4 Escribir test de propiedad para el ticket en nombre y descripción sin duplicación
    - **Property 18: Ticket en nombre y descripción sin duplicación**
    - **Validates: Requirements 10.4, 10.5**

  - [ ]* 5.5 Escribir test de propiedad para la inclusión de datos de usuario válidos
    - **Property 19: Inclusión de datos de usuario válidos**
    - **Validates: Requirements 11.4**

  - [ ]* 5.6 Escribir test de propiedad para el round-trip de decodificación
    - **Property 29: Round-trip de decodificación de días y meses**
    - **Validates: Requirements 20.6**

  - [ ]* 5.7 Escribir tests unitarios de las utilidades de dominio
    - Casos por ejemplo de tickets, nombres, descripciones y decode a nombres legibles.
    - _Requirements: 10.1, 10.2, 10.4, 10.5, 20.6_

- [x] 6. Checkpoint - Verificar el núcleo puro
  - Ejecutar todas las pruebas del núcleo (propiedad y unitarias), ruff y mypy. Asegurar que todas pasan; preguntar al usuario si surgen dudas.

- [x] 7. Implementar el módulo de configuración
  - [x] 7.1 Implementar `config.py` con `AppConfig` y `from_env`
    - Dataclass congelada con URL/token de Zabbix, proveedor de IA, claves/modelos de Gemini y OpenAI, `cors_allowed_origins` (orígenes permitidos, no comodín), versión.
    - Carga y validación desde variables de entorno; registro de errores sin exponer secretos.
    - _Requirements: 1.3, 12.1, 12.2, 12.3, 15.5, 18.4, 18.5_

  - [ ]* 7.2 Escribir tests unitarios de configuración
    - Carga válida, ausencia de variables de IA (registro sin secretos), parseo de orígenes CORS.
    - _Requirements: 1.3, 18.4, 18.5_

- [x] 8. Implementar el prompt externalizado y la abstracción del Proveedor_IA
  - [x] 8.1 Implementar el prompt externalizado en `ai/prompt.py`
    - Cargar el prompt desde recurso externalizado; construir `PromptContext` con fecha de hoy y mañana en ISO 8601; inyectar ambas fechas; máximo 5 ejemplos cubriendo cada tipo de recurrencia; sin ninguna aritmética de bitmasks.
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 13.6_

  - [x] 8.2 Implementar la interfaz `AIProvider` y las implementaciones en `ai/`
    - `provider.py` (interfaz `extract`/`is_available`), `gemini_provider.py`, `openai_provider.py`; `extract` devuelve `ExtractedRequest` sin bitmasks; reconocimiento de intención (maintenance_request/help/clarification/off_topic) y terminología de infraestructura como hosts; preserva `raw_message`.
    - _Requirements: 3.2, 3.8, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 8.3 Implementar el factory de proveedores en `ai/factory.py`
    - `build_provider(cfg)` selecciona por env (`gemini`/`openai`); registra "proveedor no soportado" ante valor inválido; expone indisponibilidad.
    - _Requirements: 12.1, 12.2, 12.3, 12.6_

  - [ ]* 8.4 Escribir test de propiedad para la inyección determinista de fechas relativas
    - **Property 8: Inyección determinista de fechas relativas**
    - **Validates: Requirements 3.6, 13.6**

  - [ ]* 8.5 Escribir tests unitarios del prompt y verificación de reducción de tokens
    - ≤5 ejemplos, ausencia de aritmética de bitmasks en el prompt, comparación de conteo de tokens legacy vs v2 con reducción ≥30%.
    - _Requirements: 3.1, 3.4, 3.5_

  - [ ]* 8.6 Escribir tests unitarios de selección y disponibilidad del proveedor de IA
    - Selección gemini/openai, valor no soportado (log), indisponibilidad, tipos de respuesta conversacional y terminología de infraestructura (con provider mockeado).
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 9. Implementar el Cliente_Zabbix (JSON-RPC 7.2)
  - [x] 9.1 Implementar `zabbix/client.py`
    - `_rpc`, `user_exists`, `get_hosts_exact`, `search_hosts` (wildcards), `get_groups_exact`, `search_groups`, `get_hosts_by_tags`, `create_maintenance`, `list_maintenance`, `is_connected`.
    - **Aditivo (Req 32):** `create_maintenance` acepta `maintenance_type`, la lista de tags de problema (`ProblemTag` → `{tag, operator, value}` con `operator ∈ {0, 2}`) y `tags_evaltype`, y los mapea al payload de `maintenance.create` (campos `tags` y `tags_evaltype`). Mantener explícita la distinción con `trigger_tags` (descubrimiento de hosts vía `get_hosts_by_tags`, que NO viajan a `maintenance.create`).
    - _Requirements: 11.2, 14.1, 14.2, 14.3, 14.4, 16.2, 16.3, 32.1, 32.2_

  - [ ]* 9.2 Escribir tests de integración del Cliente_Zabbix con mocks
    - `user.get`/401 (11.1–11.3), orden exacta→flexible→tags (14.1–14.4), `create_maintenance` con parámetros válidos (9.5), estados de conexión (16.2, 16.3).
    - **Aditivo (Req 32):** verificar el mapeo de los tags de problema al payload de `maintenance.create` (`tags` con `{tag, operator, value}` y `tags_evaltype`) y que `trigger_tags` NO se envían a `maintenance.create`.
    - _Requirements: 9.5, 11.1, 11.2, 11.3, 14.1, 14.2, 14.3, 14.4, 16.2, 16.3, 32.1, 32.2_

- [x] 10. Implementar los servicios de orquestación
  - [x] 10.1 Implementar `services/chat_service.py`
    - Orquesta la extracción de IA; completa el ticket detectado localmente cuando `ExtractedRequest.ticket` es nulo; produce la respuesta conversacional; preserva `raw_message` y rechaza extracción incompleta sin invocar `build_timeperiod`.
    - _Requirements: 3.8, 10.3, 13.1, 13.2, 13.3, 13.4, 15.7_

  - [x] 10.2 Implementar `services/maintenance_service.py`
    - Orquesta `build_timeperiod` + resolución de hosts/grupos (exacta→flexible→tags, deduplicación por id, partición encontrados/faltantes) + `create_maintenance`; incluye datos de usuario en descripción y confirmación; no crea en Zabbix si la validación falla.
    - **Aditivo (Req 32):** invocar `validate_problem_tags(problem_tags, tags_evaltype, maintenance_type)` antes de `create_maintenance`; si falla, no crear el mantenimiento en Zabbix (Req 15.7); al validar, pasar `maintenance_type`, los `ProblemTag` (con `operator`) y `tags_evaltype` a `create_maintenance`. Mantener separada la fase de descubrimiento por `trigger_tags` (Req 14.4) de los tags de problema (supresión, Req 32).
    - _Requirements: 9.5, 10.3, 11.4, 14.5, 14.6, 14.7, 15.7, 32.3, 32.4_

  - [ ]* 10.3 Escribir test de propiedad para la extracción incompleta
    - **Property 7: Extracción incompleta no invoca el cálculo y preserva el original**
    - **Validates: Requirements 3.8, 15.7**

  - [ ]* 10.4 Escribir test de propiedad para la incorporación del ticket detectado localmente
    - **Property 17: Incorporación del ticket detectado localmente**
    - **Validates: Requirements 10.3**

  - [ ]* 10.5 Escribir test de propiedad para la deduplicación de hosts
    - **Property 20: Deduplicación de hosts por identificador**
    - **Validates: Requirements 14.5**

  - [ ]* 10.6 Escribir test de propiedad para la partición de recursos encontrados y faltantes
    - **Property 21: Partición de recursos encontrados y faltantes**
    - **Validates: Requirements 14.6, 14.7**

- [x] 11. Implementar la capa HTTP (blueprints + app factory)
  - [x] 11.1 Implementar la validación de Info_Usuario en `api/auth.py`
    - Valida `Info_Usuario` vía `user.get` antes de acciones; 401 si ausente/inválida.
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 11.2 Implementar los blueprints de chat y mantenimiento en `api/chat.py` y `api/maintenance.py`
    - `POST /chat`, `POST /parse` (alias con formato idéntico), `POST /create_maintenance`, `GET /maintenance/list`, `GET /maintenance/templates`, `POST /test/routine`; error sin alterar estado ante campos faltantes/inválidos; aclaración si no se encuentra ningún recurso.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.7, 14.6_

  - [x] 11.3 Implementar los blueprints de search y health en `api/search.py` y `api/health.py`
    - `POST /search_hosts`, `POST /search_groups`; `GET /health` (estado, timestamp, conexión Zabbix, proveedor de IA, versión, funcionalidades; healthy/degraded).
    - _Requirements: 15.1, 16.1, 16.2, 16.3, 16.4_

  - [x] 11.4 Implementar el app factory en `app.py` con registro de blueprints y CORS
    - App factory sin lógica de negocio; registra blueprints; CORS con orígenes permitidos configurables y preflight; carga config.
    - _Requirements: 1.2, 1.5, 15.5_

  - [ ]* 11.5 Escribir test de propiedad para la equivalencia de /parse y /chat
    - **Property 22: Equivalencia de /parse y /chat**
    - **Validates: Requirements 15.2**

  - [ ]* 11.6 Escribir test de propiedad para la preservación del esquema de respuesta del contrato
    - **Property 23: Preservación del esquema de respuesta del contrato**
    - **Validates: Requirements 15.3, 15.4**

  - [ ]* 11.7 Escribir test de propiedad para petición inválida no altera el estado
    - **Property 24: Petición inválida no altera el estado**
    - **Validates: Requirements 15.7**

  - [ ]* 11.8 Escribir tests de contrato HTTP e integración de endpoints
    - Presencia de todos los endpoints, CORS preflight con orígenes permitidos, campos del contrato preservados, estados de `/health`.
    - _Requirements: 15.1, 15.5, 16.1, 16.2, 16.3, 16.4_

- [x] 12. Checkpoint - Verificar el backend completo
  - Ejecutar todas las pruebas (propiedad, unitarias, integración con mocks), ruff y mypy. Asegurar que todas pasan; preguntar al usuario si surgen dudas.

- [x] 13. Implementar el oráculo de paridad y las pruebas exhaustivas de regresión
  - [x] 13.1 Extraer la lógica de cálculo del monolito a `tests/fixtures/legacy_reference.py`
    - Congelar la lógica de `backend/main.py` que calcula `dayofweek`, `month`, `every` y los campos de `timeperiod` como funciones de referencia (oráculo), sin dependencias de red.
    - _Requirements: 3.7, 20.1, 20.7_

  - [ ]* 13.2 Escribir test de propiedad de paridad campo por campo
    - **Property 25: Paridad campo por campo con la versión monolítica**
    - **Validates: Requirements 3.7, 20.1**

  - [ ]* 13.3 Escribir test de paridad exhaustiva de bitmask de días (1..127)
    - **Property 26: Paridad exhaustiva de bitmask de días** (parametrizado sobre los 127 casos)
    - **Validates: Requirements 20.2**

  - [ ]* 13.4 Escribir test de paridad exhaustiva de bitmask de meses (1..4095)
    - **Property 27: Paridad exhaustiva de bitmask de meses** (parametrizado sobre los 4095 casos)
    - **Validates: Requirements 20.3**

  - [ ]* 13.5 Escribir test de paridad exhaustiva de ocurrencia de semana (1..5)
    - **Property 28: Paridad exhaustiva de ocurrencia de semana** (parametrizado sobre los 5 casos)
    - **Validates: Requirements 20.4**

  - [ ]* 13.6 Escribir test de reporte de fallo de paridad
    - Verificar que ante una diferencia el fallo reporta entrada, valor esperado y valor obtenido.
    - _Requirements: 20.7_

- [x] 14. Implementar el empaquetado Docker y la configuración de despliegue del backend
  - [x] 14.1 Crear `backend/Dockerfile`, `backend/docker-compose.yml` y `backend/.env.example`
    - Dockerfile que construye la imagen ejecutable; docker-compose con instancias aima1-5 en puertos 5005-5009; `.env.example` con variables requeridas (URL/token Zabbix, proveedor y claves de IA, modelos); sin secretos en código/imagen; requirements pinneados.
    - _Requirements: 1.6, 18.1, 18.2, 18.3, 18.4, 18.5_

  - [ ]* 14.2 Escribir tests smoke de estructura y build del backend
    - `backend/` construible sin `widget/`; `.env.example` presente; ausencia de secretos en código/imagen.
    - _Requirements: 17.2, 18.1, 18.3, 18.5_

- [x] 15. Migrar la estructura de carpetas y reubicar el widget
  - [x] 15.1 Reubicar el widget existente a `widget/aimaintenance/`
    - Mover `zabbix-widget/aimaintenance/` a `widget/aimaintenance/`; preservar id/namespace y estructura del widget compatibles con Zabbix 7.2+; añadir README de empaquetado e instalación.
    - _Requirements: 15.6, 17.1, 17.3, 17.4_

  - [x] 15.2 Documentar despliegue separado y compatibilidad de CI en el repositorio
    - README del backend y del widget separados; mantener estructura de carpetas y workflows de `.github/workflows/` compatibles con el flujo de publicación de GitHub y del registro de contenedores existentes.
    - _Requirements: 17.4, 19.1, 19.2, 19.3, 19.4_

  - [ ]* 15.3 Escribir tests smoke de separación backend/widget y CI
    - `widget/` empaquetable sin el backend; id/namespace del widget inalterados; estructura y workflows de CI compatibles.
    - _Requirements: 15.6, 17.2, 17.3, 19.4_

- [x] 16. Checkpoint final - Verificar el sistema completo
  - Ejecutar toda la batería (propiedad, unitarias, integración, paridad exhaustiva, smoke), ruff y mypy; verificar cobertura >90% en `core/` y la reducción de tokens ≥30%. Asegurar que todas las pruebas pasan; preguntar al usuario si surgen dudas.

## Mejoras transversales v2 (Req 21–30) y experiencia del widget (Req 22–25)

> Las siguientes tareas (17–26) extienden el plan para las mejoras de calidad, robustez y experiencia. Siguen el mismo enfoque dual: primero las **funciones puras** de decisión, luego su **cableado** con efectos, y finalmente los tests de propiedad (marcados `*`) sobre las funciones puras (Propiedades 30–36) más ejemplos/integración/smoke para los bordes y el widget. No alteran el núcleo de paridad ni el `Contrato_API`; el `Locale` no ramifica el `Motor_Recurrencia`.

- [x] 17. Extender la configuración para las mejoras transversales (Req 21, 26, 27, 28, 29)
  - [x] 17.1 Añadir los campos de las mejoras a `AppConfig` y `from_env` en `config.py`
    - Localización: `supported_locales` (incluye `es`), `default_locale` (`"es"`) con valores por defecto seguros (Req 21.4, 21.5, 21.6).
    - Failover: `ai_secondary_provider` (opcional), `ai_failover_max_retries`, `ai_failover_timeout_seconds` (Req 26.1, 26.2, 26.4).
    - Caché de usuario: `user_cache_ttl_seconds` (Req 27.1).
    - Rate limiting: `rate_limit_max_requests`, `rate_limit_window_seconds` (Req 28.1).
    - Validación de esquema: `ai_schema_max_attempts` (Req 29.2).
    - Documentar todas estas variables en `.env.example` sin secretos; reflejar las capacidades en la lista de funcionalidades de `/health` (Req 16.4, 18.3).
    - _Requirements: 21.4, 21.5, 21.6, 26.1, 26.2, 26.4, 27.1, 28.1, 29.2_

  - [ ]* 17.2 Escribir tests unitarios de la configuración extendida
    - Valores por defecto de locale (`es`), parseo de proveedor secundario ausente/presente, TTL, límites de tasa y máximo de intentos de esquema; registro sin secretos.
    - _Requirements: 21.5, 21.6, 26.4, 27.1, 28.1, 29.2_

- [x] 18. Implementar la localización (i18n) (Req 21)
  - [x] 18.1 Implementar la resolución de idioma pura en `i18n/locale.py`
    - `resolve_locale(requested, supported, default="es")`: devuelve el solicitado si pertenece a los soportados; recae al `default` (`es`) si es nulo, vacío o no soportado. Función pura y determinista, sin E/S.
    - _Requirements: 21.5, 21.6, 21.7_

  - [ ]* 18.2 Escribir test de propiedad para la resolución de locale con valor por defecto
    - **Property 30: Resolución de locale con valor por defecto**
    - **Validates: Requirements 21.5, 21.6, 21.7**

  - [x] 18.3 Implementar los catálogos de mensajes y el lookup en `i18n/messages.py` + `catalogs/es.py`, `catalogs/en.py`
    - `es.py` (catálogo por defecto) y `en.py` con claves de mensajes conversacionales, de confirmación y de error; `get_message(key, locale, **params)` con recaída al catálogo por defecto si la clave no existe (Req 21.4).
    - _Requirements: 21.4, 21.5_

  - [x] 18.4 Cablear la localización en los servicios y el contrato HTTP
    - En `services/chat_service.py` y `services/maintenance_service.py`: resolver el `Locale` una vez por solicitud con `resolve_locale(payload.locale, cfg.supported_locales, cfg.default_locale)` y generar todos los textos (conversacionales, confirmación, error) vía `get_message`.
    - Aceptar el campo opcional `locale` en los payloads de los endpoints sin alterar el esquema existente del `Contrato_API` (Req 21.3).
    - _Requirements: 21.1, 21.2, 21.3, 21.4_

  - [ ]* 18.5 Escribir tests unitarios y de integración de la localización (orquestación)
    - Unit: lookup de catálogo por clave y locale (`es`/`en`) y recaída de clave inexistente (21.4).
    - Integración: una petición con `locale` produce mensajes en ese idioma (21.1–21.3).
    - _Requirements: 21.1, 21.2, 21.3, 21.4_

- [x] 19. Implementar la vista previa legible del mantenimiento (Req 24.4, 24.5)
  - [x] 19.1 Implementar `build_maintenance_preview` en `core/domain.py`
    - Función pura que decodifica días y meses a lenguaje natural con `decode_days`/`decode_months` y localiza las etiquetas mediante el catálogo del locale efectivo; produce `MaintenancePreview` (nombres de días/meses, ocurrencias, hora, duración y `text` legible). Incluye EXACTAMENTE los nombres devueltos por `decode_days`/`decode_months` para los bitmasks de la configuración.
    - _Requirements: 24.4, 24.5_

  - [ ]* 19.2 Escribir test de propiedad para la vista previa legible
    - **Property 36: Vista previa legible refleja exactamente la decodificación**
    - **Validates: Requirements 24.4, 24.5**

- [x] 20. Implementar la validación de esquema de la respuesta de IA (Req 29)
  - [x] 20.1 Implementar `ai/schema.py` con el `Esquema_JSON` y la validación pura
    - `EXTRACTED_REQUEST_SCHEMA` (JSON Schema Draft 2020-12 del `ExtractedRequest`: `intent` obligatorio, `recurrence_type` restringido al enum, tipos de `hosts`/`groups`/`trigger_tags`/`ticket`/`recurrence`).
    - `validate_against_schema(response, schema=EXTRACTED_REQUEST_SCHEMA) -> (bool, list[str])`: función pura que devuelve `(True, [])` para respuestas conformes y `(False, campos)` con las rutas de los campos que incumplen.
    - _Requirements: 29.1, 29.4_

  - [ ]* 20.2 Escribir test de propiedad para la aceptación y rechazo de la validación de esquema
    - **Property 33: Aceptación y rechazo de la validación de esquema**
    - **Validates: Requirements 29.4**

- [x] 21. Implementar el failover de proveedores de IA (Req 26, 29)
  - [x] 21.1 Implementar la selección de proveedor pura en `ai/failover.py`
    - `select_provider(primary_ok, has_secondary, secondary_ok) -> "primary"|"secondary"|"unavailable"`: función pura y determinista según la tabla de disponibilidad.
    - _Requirements: 26.1, 26.3, 26.4_

  - [ ]* 21.2 Escribir test de propiedad para la lógica de selección de proveedor
    - **Property 35: Lógica de selección de proveedor (failover)**
    - **Validates: Requirements 26.1, 26.3, 26.4**

  - [x] 21.3 Implementar `FailoverAIProvider` en `ai/failover.py` y actualizar `ai/factory.py`
    - `FailoverAIProvider(primary, secondary, max_retries, timeout_s, logger)`: intenta el primario dentro de `max_retries`/`timeout_s`; ante fallo/timeout aplica `select_provider` para conmutar al secundario; si es `"unavailable"`, degrada con el mensaje localizado de indisponibilidad; registra el evento de failover vía `SecureLogger` sin secretos.
    - Integra `validate_against_schema` sobre cada respuesta y reintenta hasta `ai_schema_max_attempts`; al agotar los intentos reporta "respuesta de IA inválida" sin invocar `build_timeperiod` (Req 29.2, 29.3).
    - Actualizar `build_provider(cfg)` en `ai/factory.py` para construir el primario y el secundario opcional y envolverlos en `FailoverAIProvider` (Req 12.1, 26.1).
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 29.2, 29.3, 12.1_

  - [ ]* 21.4 Escribir tests de integración del failover y la validación de esquema
    - Failover: proveedores simulados que fallan/hacen timeout — respeta reintentos y tiempo límite, conmuta al secundario, degrada cuando ninguno está disponible y emite un registro de failover que pasa por `mask_sensitive` (26.1, 26.2, 26.5).
    - Esquema: proveedor simulado que devuelve respuestas inválidas — reintenta hasta el máximo y, al agotarse, reporta error sin invocar `build_timeperiod` (29.1–29.3).
    - _Requirements: 26.1, 26.2, 26.5, 29.1, 29.2, 29.3_

- [x] 22. Implementar la caché de validación de usuario (Req 27)
  - [x] 22.1 Implementar la vigencia pura y la caché en `cache/user_cache.py`
    - `is_cache_entry_valid(now, cached_at, ttl) -> bool`: pura y determinista; vigente si y solo si `(now - cached_at) < ttl` (la frontera `== ttl` es EXPIRADA).
    - `UserValidationCache(ttl, clock)` con reloj inyectable: `get_valid(userid)` devuelve la `Info_Usuario` cacheada si es vigente o `None` para revalidar; `put(userid, info)` registra con marca de tiempo actual.
    - _Requirements: 27.1, 27.2, 27.3, 27.4_

  - [ ]* 22.2 Escribir test de propiedad para la frontera de expiración del TTL
    - **Property 31: Frontera de expiración del TTL de caché**
    - **Validates: Requirements 27.4**

  - [x] 22.3 Cablear la caché en `api/auth.py`
    - Interponer `UserValidationCache` entre la validación de `Info_Usuario` y el `Cliente_Zabbix`: una entrada vigente evita `user.get`; ausente/expirada revalida contra Zabbix (Req 27.2, 27.3). Un fallo de caché nunca impide la validación de fondo.
    - _Requirements: 27.2, 27.3_

  - [ ]* 22.4 Escribir tests de integración de la caché de usuario
    - Con reloj y `Cliente_Zabbix` simulados: la primera validación consulta y cachea; una segunda dentro del TTL no consulta; tras expirar, revalida.
    - _Requirements: 27.1, 27.2, 27.3_

- [x] 23. Implementar la limitación de tasa por cliente (Req 28)
  - [x] 23.1 Implementar la decisión pura en `api/rate_limit.py`
    - `is_within_rate_limit(count_in_window, limit) -> bool`: pura y determinista; permite si y solo si `count_in_window < limit` (la frontera `== limit` se rechaza).
    - _Requirements: 28.4_

  - [ ]* 23.2 Escribir test de propiedad para la decisión de límite de tasa
    - **Property 32: Decisión de límite de tasa por contador**
    - **Validates: Requirements 28.4**

  - [x] 23.3 Implementar el middleware de rate-limit y cablearlo en el app factory
    - Middleware por cliente que identifica al cliente, mantiene el contador por ventana (`rate_limit_window_seconds`) e invoca `is_within_rate_limit`; si es falso responde **429** con indicación de límite excedido sin ejecutar la acción, si no continúa.
    - Registrar el middleware en `app.py` **antes** de la validación de usuario y de la orquestación de servicios (Req 28.1).
    - _Requirements: 28.1, 28.2, 28.3_

  - [ ]* 23.4 Escribir tests de integración del middleware de rate-limit
    - Dentro del límite responde normalmente; al exceder responde 429.
    - _Requirements: 28.1, 28.2, 28.3_

- [x] 24. Implementar la observabilidad y el registro seguro (Req 30)
  - [x] 24.1 Implementar el enmascaramiento puro y el `SecureLogger` en `observability/logger.py`
    - `mask_sensitive(record) -> dict`: función pura y determinista que copia el registro sustituyendo por máscara el valor de toda clave sensible (por nombre), conservando los no sensibles, recorriendo estructuras anidadas; idempotente.
    - `SecureLogger` estructurado (JSON) cuyos `info`/`error` pasan todo evento por `mask_sensitive` antes de escribir.
    - _Requirements: 30.2, 30.3, 30.4_

  - [ ]* 24.2 Escribir test de propiedad para el enmascaramiento seguro
    - **Property 34: El enmascaramiento nunca filtra secretos**
    - **Validates: Requirements 30.3, 30.4, 26.5**

  - [x] 24.3 Implementar las métricas y el blueprint `/metrics`, y cablear el logger
    - `observability/metrics.py`: registro/colección de métricas (contadores de solicitudes, latencias, tasas de error, eventos de failover) con `prometheus_client`.
    - `api/metrics.py`: blueprint `GET /metrics` en formato Prometheus, sin exponer valores de configuración sensibles.
    - Cablear el `SecureLogger` en los servicios y proveedores; registrar el blueprint de métricas en el app factory (`app.py`).
    - _Requirements: 30.1, 30.2_

  - [ ]* 24.4 Escribir tests de integración/smoke de observabilidad
    - `GET /metrics` responde 200 con formato Prometheus; el `Log_Seguro` emite registros estructurados (JSON) y no filtra secretos.
    - _Requirements: 30.1, 30.2_

- [x] 25. Checkpoint - Verificar las mejoras transversales del backend
  - Ejecutar todas las pruebas nuevas del backend (propiedad 30–36, unitarias, integración de failover/caché/rate-limit/esquema/localización/métricas), ruff y mypy; verificar cobertura >90% en las funciones puras transversales (`i18n/locale.py`, `cache/user_cache.py`, `api/rate_limit.py`, `ai/schema.py`, `ai/failover.py::select_provider`, `observability/logger.py::mask_sensitive`). Asegurar que todas pasan; preguntar al usuario si surgen dudas.

- [x] 26. Modernizar el widget: modularización, accesibilidad, UX del chat y tema (Req 22–25)
  - [x] 26.1 Modularizar el JavaScript del widget en `widget/aimaintenance/assets/js/`
    - Extraer `ui.renderer.js` (renderizado de interfaz), `http.client.js` (cliente HTTP reutilizable) y `message.formatter.js` (formateo de mensajes + vista previa legible); reducir `class.widget.js` a un orquestador delgado que no concentre renderizado + HTTP + formateo.
    - _Requirements: 22.1, 22.2, 22.3, 22.4_

  - [x] 26.2 Implementar accesibilidad WCAG 2.1 AA en `ui.renderer.js`
    - Roles y etiquetas ARIA en los controles del chat; contraste ≥ 4.5:1 (texto normal) / ≥ 3:1 (texto grande); operabilidad por teclado (Tab/Enter/Escape) e indicador de foco visible.
    - _Requirements: 23.1, 23.2, 23.3, 23.4_

  - [x] 26.3 Implementar las mejoras de UX del chat (Req 24.1–24.3)
    - Indicador de procesamiento visible mientras se espera al backend; historial de conversación preservado durante la sesión; acción de reintento manual visible tras un fallo; `http.client.js` envía el `locale` activo en cada petición (enlaza con Req 21.3).
    - _Requirements: 24.1, 24.2, 24.3, 21.3_

  - [x] 26.4 Implementar el soporte de tema claro/oscuro en `assets/css/theme.css`
    - Estilos que respetan el tema activo de Zabbix (claro/oscuro); eliminar colores fijos que ignoren el tema.
    - _Requirements: 25.1, 25.2_

  - [ ]* 26.5 Escribir tests smoke/ejemplo del widget (no PBT)
    - Modularización: existen los módulos separados y `class.widget.js` no concentra renderizado + HTTP + formateo (22).
    - Accesibilidad: auditoría automatizada axe-core/Lighthouse para roles/etiquetas ARIA y contraste; ejemplos de teclado (Tab/Enter/Escape) y foco visible — la validación completa requiere pruebas manuales con tecnología asistiva (23).
    - UX del chat: indicador de procesamiento, historial de sesión, reintento manual visible y envío de `locale` (24.1–24.3).
    - Tema: aplicación de estilos según el tema activo y ausencia de colores fijos (25).
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 23.1, 23.2, 23.3, 23.4, 24.1, 24.2, 24.3, 25.1, 25.2_

  - [x] 26.6 Asegurar la compatibilidad del módulo de widget con Zabbix 7.4 (Req 33)
    - Manifiesto (Req 33.1): `widget/aimaintenance/manifest.json` declara `"manifest_version": 2.0` como valor **numérico** (no la cadena `"2.0"`).
    - Traducción nativa (Req 33.2, ligada a Req 21/33.2): usar el mecanismo nativo de Zabbix para las cadenas traducibles — `_()` en PHP (vistas y clases) y `t()` en JavaScript —; registrar las cadenas JS en la clase del widget mediante `getTranslationStrings()` (punto de registro en `class.widget.js`); sin literales de interfaz incrustados en la lógica.
    - Estructura de clases (Req 33.3): `Widget` **extends** `CWidget` (metadatos, assets, `getTranslationStrings()`); `WidgetView` **extends** `CControllerDashboardWidgetView`; `WidgetForm` **extends** `CWidgetForm` con campos `CWidgetField` (p. ej. `CWidgetFieldColor`, `CWidgetFieldTextBox`, `CWidgetFieldUrl`); vistas `views/widget.view.php` (datos) y `views/widget.edit.php` (configuración).
    - Formulario de configuración (Req 33.4): aprovechar la **validación inline** del formulario y el **selector de color con paletas** (`CWidgetFieldColor`, p. ej. color de acento del chat/tema) en `widget.edit.php`, preservando id/namespace del widget.
    - _Requirements: 33.1, 33.2, 33.3, 33.4_

  - [ ]* 26.7 Escribir test de ejemplo/smoke de compatibilidad del módulo de widget (no PBT)
    - Verificar que `manifest.json` parsea `manifest_version` como **número** (tipo numérico, no cadena) y su valor es `2.0`.
    - Verificar la estructura del módulo: presencia de `Widget.php`, `actions/WidgetView.php`, `includes/WidgetForm.php`, `views/widget.view.php`, `views/widget.edit.php`; señales de herencia esperada (`extends CWidget`, `extends CControllerDashboardWidgetView`, `extends CWidgetForm`) y del registro `getTranslationStrings()`.
    - _Requirements: 33.1, 33.2, 33.3, 33.4_

- [x] 27. Checkpoint final v2 - Verificar el sistema completo con las mejoras
  - Ejecutar toda la batería (núcleo, backend, mejoras transversales, compatibilidad de la versión actual de Zabbix Req 31–33, widget smoke/a11y), ruff y mypy; confirmar que las Propiedades 30–39 pasan y que el `Contrato_API` (incluidos los campos adicionales `tags_evaltype`/`operator` del Req 15.8) y la paridad del núcleo permanecen intactos. Asegurar que todas las pruebas pasan; preguntar al usuario si surgen dudas.

## Notes

- Las sub-tareas marcadas con `*` son opcionales (pruebas) y pueden omitirse para un MVP más rápido; las tareas de implementación centrales nunca se marcan opcionales.
- Cada tarea referencia requisitos específicos para trazabilidad y, cuando aplica, la propiedad de correctitud que valida.
- Las propiedades 26–28 se ejecutan de forma exhaustiva (127 / 4095 / 5 casos) mediante `@pytest.mark.parametrize`, cumpliendo el "FOR ALL" literal del Req 20; el resto de tests de propiedad usan Hypothesis con ≥100 iteraciones.
- El oráculo `legacy_reference.py` congela la lógica del monolito `backend/main.py` para garantizar paridad sin regresiones antes de retirar el monolito.
- Los checkpoints aseguran validación incremental del núcleo puro, del backend completo, de las mejoras transversales y del sistema con despliegue.
- Las mejoras transversales (Req 21–30, tareas 17–27) aíslan su decisión en funciones puras (`resolve_locale`, `build_maintenance_preview`, `validate_against_schema`, `select_provider`, `is_cache_entry_valid`, `is_within_rate_limit`, `mask_sensitive`), verificadas con las Propiedades 30–36; los bordes con efectos (middleware, caché, failover, logger, `/metrics`) y las mejoras del widget (Req 22–25) se cubren con ejemplo/integración/smoke, no con PBT.
- En cada bloque de mejora, la función pura y su test de propiedad preceden al cableado con efectos, para detectar errores de decisión antes de integrarlos.
- La compatibilidad con la versión actual de Zabbix (Req 31–33) reutiliza tareas existentes: las funciones puras `validate_period_seconds`/`floor_to_minute` (Req 31) y `validate_problem_tags` (Req 32) se añaden a la tarea 4 (`core/recurrence.py`) con las Propiedades 37–39; el cableado de tags de problema recae en el `Cliente_Zabbix` (9.1) y `MaintenanceService` (10.2), y la compatibilidad del módulo de widget (Req 33: `manifest_version` numérico, traducción nativa `_()`/`t()`/`getTranslationStrings()`, estructura de clases y validación inline + color picker) se cubre en la tarea 26 con ejemplo/smoke (no PBT), por ser configuración declarativa y estructura PHP/JS.
- La distinción `trigger_tags` (descubrimiento de hosts, Req 14.4) vs `ProblemTag` (supresión de problemas del mantenimiento, Req 32) se mantiene explícita en modelos, cliente y servicio; solo los `ProblemTag` y `tags_evaltype` viajan a `maintenance.create`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1", "5.1", "5.2"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "5.3", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 4, "tasks": ["3.7", "3.8", "4.1"] },
    { "id": 5, "tasks": ["4.10", "7.1", "9.1"] },
    { "id": 6, "tasks": ["4.11", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"] },
    { "id": 7, "tasks": ["4.12", "4.13", "4.14", "7.2", "8.1", "8.2", "8.3", "9.2", "17.1", "18.1", "20.1", "21.1", "22.1", "23.1", "24.1", "26.1"] },
    { "id": 8, "tasks": ["8.4", "8.5", "8.6", "10.1", "10.2", "17.2", "18.2", "18.3", "19.1", "20.2", "21.2", "22.2", "23.2", "24.2", "26.2", "26.3", "26.4", "26.6"] },
    { "id": 9, "tasks": ["10.3", "10.4", "10.5", "10.6", "11.1", "13.1", "18.4", "19.2", "21.3", "22.3", "23.3", "24.3", "26.5", "26.7"] },
    { "id": 10, "tasks": ["11.2", "11.3", "13.2", "13.3", "13.4", "13.5", "13.6", "18.5", "21.4", "22.4", "23.4", "24.4"] },
    { "id": 11, "tasks": ["11.4"] },
    { "id": 12, "tasks": ["11.5", "11.6", "11.7", "11.8", "14.1"] },
    { "id": 13, "tasks": ["14.2", "15.1", "15.2"] },
    { "id": 14, "tasks": ["15.3"] }
  ]
}
```
