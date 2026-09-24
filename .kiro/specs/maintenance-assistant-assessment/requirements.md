# Requirements Document — Maintenance Assistant Assessment

## Introduction

Este documento define los requisitos para la funcionalidad de evaluación (assessment) del proyecto **AI Maintenance Assistant for Zabbix 7.2** (IA-SHEDULER-ZABBIX). El proyecto consiste en un servicio Flask con IA (Gemini/OpenAI) que permite al equipo de operaciones crear y gestionar mantenimientos en Zabbix 7.2 mediante lenguaje natural, desplegado como un widget dentro del dashboard de Zabbix.

El equipo de operaciones presenta alta rotación de personal, por lo cual el asistente fue diseñado para facilitar la creación de mantenimientos sin conocimiento técnico profundo. Esta evaluación busca identificar riesgos, bugs, duplicaciones de código, inconsistencias y analizar la viabilidad de ejecutar funcionalidades de manera nativa desde el widget (sin depender del backend Flask).

El proyecto se compone de:
- **Backend**: Servicio Flask (Python) con integración a Zabbix API 7.2 y proveedores de IA (Gemini, OpenAI)
- **Widget**: Módulo JavaScript/PHP para Zabbix 7.2 que proporciona la interfaz de chat interactivo
- **Infraestructura**: Docker/Docker Compose para despliegue multi-instancia

## Glossary

- **AI_Backend**: El servicio Flask (Python) que procesa solicitudes de mantenimiento, interactúa con la API de Zabbix y orquesta las llamadas a proveedores de IA.
- **Zabbix_Widget**: El módulo de widget para Zabbix 7.2 (PHP + JavaScript) que proporciona la interfaz de chat interactivo dentro del dashboard.
- **Assessment_System**: El sistema de evaluación que analiza el código del proyecto para detectar riesgos, bugs, duplicaciones e inconsistencias.
- **Operations_Team**: El equipo de operaciones que utiliza el widget para crear mantenimientos. Presenta alta rotación de personal.
- **Zabbix_API**: La API JSON-RPC de Zabbix 7.2 utilizada para crear, consultar y gestionar mantenimientos.
- **AI_Provider**: El proveedor de inteligencia artificial (Gemini o OpenAI) que procesa las solicitudes en lenguaje natural.
- **Native_Mode**: Modo de operación donde funcionalidades se ejecutan directamente en el widget JavaScript sin requerir llamadas al AI_Backend.
- **Bitmask_Engine**: La lógica de cálculo de bitmasks para mantenimientos rutinarios (días de semana, meses, ocurrencias).
- **Maintenance_Request**: Una solicitud de mantenimiento procesada por la IA que incluye hosts, grupos, horarios, tipo de recurrencia y configuración de bitmasks.

## Requirements

### Requirement 1: Evaluación de Riesgos de Seguridad del Backend

**User Story:** Como desarrollador del equipo de operaciones, quiero identificar riesgos de seguridad en el AI_Backend, para que pueda mitigar vulnerabilidades antes de que sean explotadas en producción.

#### Acceptance Criteria

1. WHEN el Assessment_System analiza el AI_Backend, THE Assessment_System SHALL identificar endpoints expuestos sin autenticación y clasificarlos por nivel de riesgo (alto, medio, bajo).
2. WHEN el Assessment_System detecta que CORS está configurado con `CORS(app)` sin restricciones de origen, THE Assessment_System SHALL reportar el hallazgo como riesgo alto con recomendación de restringir orígenes permitidos.
3. WHEN el Assessment_System detecta credenciales gestionadas exclusivamente por variables de entorno sin validación de presencia, THE Assessment_System SHALL reportar el riesgo de fallo silencioso y recomendar validación al inicio.
4. WHEN el Assessment_System detecta que el token de Zabbix se transmite en headers sin cifrado de transporte obligatorio, THE Assessment_System SHALL reportar el riesgo y recomendar forzar HTTPS.
5. IF el Assessment_System detecta que no existe rate limiting en los endpoints del AI_Backend, THEN THE Assessment_System SHALL reportar el riesgo de abuso de API y consumo excesivo de tokens de IA.

### Requirement 2: Detección de Bugs y Errores en el Código

**User Story:** Como desarrollador del equipo de operaciones, quiero identificar bugs existentes y potenciales en el código del proyecto, para que pueda corregirlos antes de que afecten a los usuarios.

#### Acceptance Criteria

1. WHEN el Assessment_System analiza el manejo de errores del AI_Backend, THE Assessment_System SHALL identificar rutas de código donde excepciones no capturadas pueden causar respuestas HTTP 500 sin información útil al usuario.
2. WHEN el Assessment_System analiza el parsing de fechas y bitmasks generados por la IA, THE Assessment_System SHALL identificar casos donde valores inválidos o fuera de rango no son validados antes de enviarlos a la Zabbix_API.
3. WHEN el Assessment_System analiza el Zabbix_Widget, THE Assessment_System SHALL identificar condiciones de carrera potenciales entre solicitudes concurrentes (doble clic en confirmar, múltiples envíos simultáneos).
4. WHEN el Assessment_System detecta que el método `_make_request` no valida el esquema de respuesta de Zabbix_API, THE Assessment_System SHALL reportar el riesgo de fallos por cambios en la API.
5. IF el Assessment_System detecta que el timeout de 30 segundos en `_make_request` no tiene manejo de reintentos, THEN THE Assessment_System SHALL reportar el bug potencial de pérdida de solicitudes en redes inestables.

### Requirement 3: Detección de Duplicación de Código

**User Story:** Como desarrollador del equipo de operaciones, quiero identificar código duplicado en el proyecto, para que pueda refactorizar y reducir el costo de mantenimiento.

#### Acceptance Criteria

1. WHEN el Assessment_System analiza el AI_Backend, THE Assessment_System SHALL identificar funciones o bloques de código con similitud mayor al 70% y reportar las ubicaciones exactas.
2. WHEN el Assessment_System detecta lógica de parsing de tickets duplicada entre el prompt de IA y la función `_extract_ticket_number`, THE Assessment_System SHALL reportar la duplicación y sugerir una fuente única de verdad.
3. WHEN el Assessment_System detecta lógica de formateo de mensajes duplicada entre el backend (generate_maintenance_description) y el widget (formatRecurrenceConfig), THE Assessment_System SHALL reportar la inconsistencia y recomendar centralización.
4. THE Assessment_System SHALL identificar patrones de código repetitivo en el manejo de diferentes tipos de recurrencia (daily, weekly, monthly) y sugerir abstracciones.

### Requirement 4: Evaluación de Viabilidad de Ejecución Nativa en Widget

**User Story:** Como desarrollador del equipo de operaciones, quiero evaluar qué funcionalidades pueden ejecutarse directamente en el Zabbix_Widget sin depender del AI_Backend, para que la experiencia sea más rápida y se reduzca la dependencia del servidor.

#### Acceptance Criteria

1. WHEN el Assessment_System evalúa el Bitmask_Engine, THE Assessment_System SHALL determinar si el cálculo de bitmasks (días de semana, meses, ocurrencias) puede ejecutarse nativamente en JavaScript dentro del widget.
2. WHEN el Assessment_System evalúa la validación de formato de tickets (patrón XXX-XXXXXX), THE Assessment_System SHALL confirmar que la validación puede ejecutarse nativamente en el widget sin llamada al backend.
3. WHEN el Assessment_System evalúa la validación de fechas y horarios, THE Assessment_System SHALL determinar si el parsing de formatos de fecha ("mañana de 8 a 10", "24/08/25 10:00am") puede ejecutarse nativamente en el widget.
4. WHEN el Assessment_System evalúa la búsqueda de hosts y grupos, THE Assessment_System SHALL determinar que esta funcionalidad requiere el backend por depender de la Zabbix_API y NO puede ser nativa.
5. THE Assessment_System SHALL producir una matriz de funcionalidades clasificadas como: "nativa viable", "nativa parcial (requiere fallback al backend)", o "requiere backend obligatoriamente".

### Requirement 5: Evaluación de Consistencia entre Prompt de IA y Lógica de Backend

**User Story:** Como desarrollador del equipo de operaciones, quiero verificar que el prompt de IA y la lógica del backend estén alineados, para que no existan discrepancias que causen errores en la creación de mantenimientos.

#### Acceptance Criteria

1. WHEN el Assessment_System compara los valores de bitmask documentados en el prompt con los valores esperados por la Zabbix_API, THE Assessment_System SHALL reportar cualquier discrepancia encontrada.
2. WHEN el Assessment_System compara los formatos de fecha esperados por el prompt con los formatos procesados por el backend, THE Assessment_System SHALL reportar inconsistencias en el parsing.
3. WHEN el Assessment_System analiza los tipos de respuesta definidos en el prompt (maintenance_request, help_request, off_topic, clarification_needed, error) contra los tipos manejados en el widget, THE Assessment_System SHALL reportar tipos no manejados o tipos esperados pero no generados.
4. IF el Assessment_System detecta que el prompt define campos opcionales que el backend trata como obligatorios (o viceversa), THEN THE Assessment_System SHALL reportar la inconsistencia con impacto estimado.

### Requirement 6: Evaluación de Resiliencia y Manejo de Fallos

**User Story:** Como desarrollador del equipo de operaciones, quiero evaluar cómo el sistema maneja fallos de sus dependencias externas, para que pueda mejorar la experiencia del usuario cuando hay problemas de conectividad.

#### Acceptance Criteria

1. WHEN el Assessment_System evalúa el comportamiento del AI_Backend cuando la Zabbix_API no está disponible, THE Assessment_System SHALL verificar si existe degradación graceful o si el sistema falla completamente.
2. WHEN el Assessment_System evalúa el comportamiento del AI_Backend cuando el AI_Provider no responde o retorna errores, THE Assessment_System SHALL verificar si existe manejo de fallback o mensajes informativos al usuario.
3. WHEN el Assessment_System evalúa el Zabbix_Widget, THE Assessment_System SHALL verificar que el mecanismo de retry (max_retries=2) es adecuado y que los timeouts (60s request, 10s health) son apropiados para el contexto de uso.
4. THE Assessment_System SHALL evaluar si el widget maneja correctamente la pérdida de conexión con el backend durante una operación de confirmación de mantenimiento.

### Requirement 7: Evaluación de Escalabilidad Multi-Instancia

**User Story:** Como desarrollador del equipo de operaciones, quiero evaluar la arquitectura multi-instancia del proyecto, para que pueda identificar problemas potenciales al escalar a múltiples servidores Zabbix.

#### Acceptance Criteria

1. WHEN el Assessment_System analiza la configuración Docker Compose multi-instancia, THE Assessment_System SHALL verificar que no existen conflictos de puertos, redes o recursos compartidos entre instancias.
2. WHEN el Assessment_System evalúa el estado compartido entre instancias, THE Assessment_System SHALL identificar si existe riesgo de colisión o inconsistencia cuando múltiples instancias operan simultáneamente.
3. THE Assessment_System SHALL evaluar si la configuración de red (subnet 172.31.10.0/24) es adecuada para el número máximo de instancias planificadas.
4. WHEN el Assessment_System evalúa el consumo de recursos por instancia, THE Assessment_System SHALL estimar el impacto en memoria y CPU de ejecutar 5+ instancias concurrentes con proveedores de IA activos.

### Requirement 8: Evaluación de Experiencia de Usuario para Personal con Alta Rotación

**User Story:** Como supervisor del equipo de operaciones, quiero evaluar si el asistente es suficientemente intuitivo para personal nuevo con alta rotación, para que pueda identificar mejoras en la usabilidad.

#### Acceptance Criteria

1. WHEN el Assessment_System evalúa el flujo de onboarding del widget, THE Assessment_System SHALL verificar si el mensaje de bienvenida y los ejemplos son suficientes para que un usuario nuevo cree su primer mantenimiento sin ayuda externa.
2. WHEN el Assessment_System evalúa los mensajes de error del sistema, THE Assessment_System SHALL verificar que todos los mensajes están en español y son comprensibles para personal no técnico.
3. WHEN el Assessment_System evalúa el flujo de confirmación de mantenimiento, THE Assessment_System SHALL verificar que la información presentada es clara y permite al usuario detectar errores antes de confirmar.
4. THE Assessment_System SHALL evaluar si el widget proporciona suficiente feedback visual durante operaciones largas (loading states, progress indicators).

### Requirement 9: Evaluación de Calidad del Prompt de IA

**User Story:** Como desarrollador del equipo de operaciones, quiero evaluar la calidad y robustez del prompt de IA, para que pueda identificar casos donde la IA puede generar respuestas incorrectas o ambiguas.

#### Acceptance Criteria

1. WHEN el Assessment_System analiza el prompt de IA, THE Assessment_System SHALL identificar ambigüedades en las instrucciones que pueden causar respuestas inconsistentes entre diferentes proveedores (Gemini vs OpenAI).
2. WHEN el Assessment_System evalúa los ejemplos del prompt, THE Assessment_System SHALL verificar que cubren los casos de uso más frecuentes del equipo de operaciones.
3. WHEN el Assessment_System evalúa el manejo de edge cases en el prompt (fechas pasadas, bitmasks inválidos, hosts inexistentes), THE Assessment_System SHALL identificar escenarios no cubiertos que pueden causar errores silenciosos.
4. THE Assessment_System SHALL evaluar si el tamaño del prompt (tokens) es eficiente o si puede optimizarse sin perder funcionalidad.
5. IF el Assessment_System detecta que el prompt no incluye instrucciones para manejar solicitudes ambiguas del usuario, THEN THE Assessment_System SHALL reportar el riesgo de creación de mantenimientos incorrectos.

### Requirement 10: Generación de Reporte Consolidado de Assessment

**User Story:** Como desarrollador del equipo de operaciones, quiero un reporte consolidado con todos los hallazgos del assessment, para que pueda priorizar las correcciones y mejoras del proyecto.

#### Acceptance Criteria

1. THE Assessment_System SHALL generar un reporte que clasifique cada hallazgo por categoría (seguridad, bug, duplicación, rendimiento, usabilidad) y severidad (crítico, alto, medio, bajo).
2. THE Assessment_System SHALL incluir para cada hallazgo: descripción del problema, ubicación en el código (archivo y línea), impacto estimado, y recomendación de corrección.
3. THE Assessment_System SHALL incluir una sección de "Quick Wins" con correcciones de bajo esfuerzo y alto impacto que pueden implementarse en menos de 2 horas.
4. THE Assessment_System SHALL incluir una sección de viabilidad nativa con la matriz de funcionalidades que pueden migrarse al widget.
5. WHEN el reporte está completo, THE Assessment_System SHALL presentar un resumen ejecutivo con métricas: total de hallazgos por categoría, deuda técnica estimada, y riesgo general del proyecto (1-10).
