# Requirements Document

## Introduction

Este documento define los requisitos para **zabbix-ai-maintenance-v2**, una migración del proyecto existente "AI Maintenance Assistant for Zabbix 7.2" hacia una versión limpia construida con buenas prácticas de ingeniería.

El proyecto actual consiste en un backend monolítico en Flask (un único archivo `main.py` de más de 1600 líneas) que mezcla el cliente de la API de Zabbix, el parser de IA, los endpoints HTTP, funciones auxiliares y un prompt de IA muy extenso embebido en código, junto con un widget de Zabbix (PHP/JS). El sistema permite crear mantenimientos en Zabbix a partir de lenguaje natural, soportando mantenimientos únicos y recurrentes (diarios, semanales, mensuales por día del mes y mensuales por día de la semana) con manejo de bitmasks para días, meses y ocurrencias de semana, detección de tickets, información de usuario y dos proveedores de IA (Gemini y OpenAI).

La versión v2 persigue cuatro objetivos principales sin introducir regresiones funcionales:

1. **Arquitectura limpia**: reestructurar el backend eliminando el monolito, con separación clara de responsabilidades.
2. **Optimización de tokens de IA**: reducir el consumo de tokens del prompt, moviendo el cálculo determinista de bitmasks fuera del LLM hacia código del backend y/o externalizando y recortando el prompt, preservando el comportamiento observable.
3. **Cobertura y correctitud garantizadas** de todos los tipos de mantenimiento y todas las combinaciones de bitmasks (requisito duro, sin regresiones).
4. **Separación backend/frontend** en partes claramente distinguibles, manteniendo la compatibilidad del widget y de la API, y conservando el flujo de despliegue Docker y la migración al mismo repositorio de GitHub.

## Glossary

- **Sistema_v2**: la solución completa migrada zabbix-ai-maintenance-v2 (backend más widget frontend).
- **Backend**: el servicio HTTP en Python/Flask que expone la API REST y orquesta la lógica de negocio.
- **Frontend_Widget**: el widget de Zabbix (PHP/JS) `aimaintenance` que consume la API del Backend.
- **Cliente_Zabbix**: el componente del Backend que encapsula las llamadas a la API JSON-RPC de Zabbix 7.2.
- **Proveedor_IA**: abstracción del Backend que interactúa con un modelo de lenguaje (Gemini u OpenAI) para interpretar solicitudes.
- **Motor_Recurrencia**: el componente determinista del Backend que calcula y valida bitmasks y parámetros de periodos de mantenimiento (`timeperiods`) de Zabbix.
- **Bitmask_Dias**: entero de 1 a 127 que codifica días de la semana (Lunes=1, Martes=2, Miércoles=4, Jueves=8, Viernes=16, Sábado=32, Domingo=64).
- **Bitmask_Meses**: entero de 1 a 4095 que codifica meses (Enero=1, Febrero=2, ..., Diciembre=2048; todos=4095).
- **Ocurrencia_Semana**: valor del campo `every` en mantenimientos mensuales por día de semana (1=primera, 2=segunda, 3=tercera, 4=cuarta, 5=última), admitiendo combinaciones.
- **Tipo_Recurrencia**: uno de `once`, `daily`, `weekly`, `monthly`.
- **Numero_Ticket**: identificador con formato `XXX-XXXXXX` (tres dígitos, guion, tres a seis dígitos).
- **Info_Usuario**: datos del usuario autenticado de Zabbix (userid, username, name, surname).
- **timeperiod_type**: código de Zabbix para el tipo de periodo (0=único, 2=diario, 3=semanal, 4=mensual).
- **Prompt_IA**: instrucción enviada al Proveedor_IA para interpretar el mensaje del usuario.
- **Contrato_API**: el conjunto de rutas, formatos de petición y formatos de respuesta que el Frontend_Widget y clientes existentes esperan del Backend.
- **Locale**: identificador de idioma/región (por ejemplo `es`, `en`, `es-PE`) usado para seleccionar el idioma de las respuestas y textos de interfaz. El valor por defecto es `es`.
- **Failover**: mecanismo del Backend que conmuta del Proveedor_IA primario a un Proveedor_IA secundario cuando el primario falla o excede su tiempo límite.
- **TTL_Cache**: tiempo de vida (en segundos) durante el cual una entrada cacheada (por ejemplo una validación de Info_Usuario) se considera válida antes de expirar.
- **Rate_Limit**: límite configurable de número de solicitudes permitidas por cliente dentro de una ventana de tiempo, usado para prevenir abuso y costo de IA descontrolado.
- **Esquema_JSON**: definición formal (JSON Schema) que describe la estructura, tipos y campos obligatorios esperados de la respuesta estructurada del Proveedor_IA.
- **Metricas**: conjunto de indicadores operativos del Backend (contadores, latencias, tasas de error) expuestos en un formato compatible con Prometheus.
- **Log_Seguro**: registro estructurado del Backend que enmascara campos sensibles (tokens, claves de API, credenciales) antes de escribirlos.
- **maintenance_type**: código de Zabbix para el tipo de mantenimiento (0 = con recolección de datos, 1 = sin recolección de datos).
- **Tags_Evaltype**: método de evaluación de los tags de problemas de un mantenimiento de Zabbix (0 = And/Or, valor por defecto; 2 = Or).
- **Operador_Tag**: operador de comparación de un tag de problema de Zabbix (0 = Equals; 2 = Contains, valor por defecto).
- **Rango_Period**: rango válido del campo `period` (duración del mantenimiento en segundos) admitido por Zabbix, de 300 a 86399940 segundos, ambos inclusive.

## Requirements

### Requisito 1: Arquitectura limpia y separación de responsabilidades del backend

**Historia de Usuario:** Como desarrollador que mantiene el proyecto, quiero un backend modular con responsabilidades separadas, para poder mantener, probar y extender el código sin trabajar sobre un archivo monolítico.

#### Criterios de Aceptación

1. THE Backend SHALL organizar el código en módulos separados por responsabilidad, incluyendo como mínimo: cliente de Zabbix, proveedor de IA, motor de recurrencia, capa de endpoints HTTP y utilidades de dominio.
2. THE Backend SHALL evitar que el punto de entrada de la aplicación contenga la lógica de negocio de cálculo de recurrencia, integración con IA e integración con Zabbix.
3. THE Backend SHALL cargar la configuración (URL y token de Zabbix, proveedor y claves de IA, modelos) desde variables de entorno mediante un único módulo de configuración.
4. THE Backend SHALL exponer la lógica del Motor_Recurrencia como funciones puras invocables de forma independiente de Flask y del Proveedor_IA.
5. WHERE exista lógica compartida entre endpoints, THE Backend SHALL ubicarla en módulos reutilizables en lugar de duplicarla.
6. THE Backend SHALL incluir un archivo de dependencias con versiones fijadas para las bibliotecas utilizadas.

### Requisito 2: Cálculo determinista de bitmasks en el backend

**Historia de Usuario:** Como responsable del sistema, quiero que los bitmasks de días, meses y ocurrencias de semana se calculen de forma determinista en el backend, para que los mantenimientos sean correctos independientemente de errores aritméticos del modelo de IA.

#### Criterios de Aceptación

1. THE Motor_Recurrencia SHALL calcular el Bitmask_Dias (entero de 1 a 127) a partir de un conjunto no vacío de días de la semana usando los valores Lunes=1, Martes=2, Miércoles=4, Jueves=8, Viernes=16, Sábado=32, Domingo=64, sumando los valores de los días seleccionados.
2. THE Motor_Recurrencia SHALL calcular el Bitmask_Meses (entero de 1 a 4095) a partir de un conjunto no vacío de meses usando los valores Enero=1, Febrero=2, Marzo=4, Abril=8, Mayo=16, Junio=32, Julio=64, Agosto=128, Septiembre=256, Octubre=512, Noviembre=1024, Diciembre=2048, con el valor 4095 representando todos los meses.
3. THE Motor_Recurrencia SHALL calcular el valor de Ocurrencia_Semana a partir de una o varias ocurrencias (primera=1, segunda=2, tercera=3, cuarta=4, última=5), sumando los valores cuando se especifican múltiples ocurrencias.
4. THE Motor_Recurrencia SHALL convertir una hora de inicio expresada en horas (0 a 23) a segundos desde medianoche multiplicando las horas por 3600.
5. THE Motor_Recurrencia SHALL convertir una duración expresada en horas (mayor que 0) a segundos multiplicando las horas por 3600.
6. WHEN el Proveedor_IA devuelve un conjunto estructurado de días, meses u ocurrencias de semana en lugar de un bitmask precalculado, THE Motor_Recurrencia SHALL calcular el bitmask correspondiente en el Backend.
7. IF el Proveedor_IA devuelve un Bitmask_Dias precalculado fuera del rango 1 a 127, un Bitmask_Meses fuera del rango 1 a 4095 o una Ocurrencia_Semana fuera del rango 1 a 5, THEN THE Motor_Recurrencia SHALL rechazar la solicitud con un mensaje de bitmask inválido.
8. IF el conjunto de días o de meses recibido está vacío, THEN THE Motor_Recurrencia SHALL rechazar la solicitud indicando el dato faltante.
9. IF la hora de inicio está fuera del rango 0 a 23 o la duración no es mayor que 0, THEN THE Motor_Recurrencia SHALL rechazar la solicitud con un mensaje de error de tiempo inválido.

### Requisito 3: Optimización de tokens del prompt de IA

**Historia de Usuario:** Como responsable de costos operativos, quiero reducir el consumo de tokens de la IA, para que cada solicitud sea más económica y rápida sin perder funcionalidad.

#### Criterios de Aceptación

1. THE Backend SHALL trasladar el cálculo de bitmasks de días, meses y ocurrencias de semana desde el Prompt_IA hacia el Motor_Recurrencia, de modo que ninguna operación aritmética de bitmask permanezca en el Prompt_IA.
2. THE Prompt_IA SHALL solicitar al Proveedor_IA la extracción de datos estructurados (días, meses, ocurrencias, horas, duración, hosts, grupos, tickets, tipo de recurrencia) sin exigir el cálculo aritmético de bitmasks.
3. THE Backend SHALL definir el Prompt_IA en un recurso externalizado o en un módulo dedicado, separado de la lógica de endpoints.
4. THE Backend SHALL reducir el número de tokens del Prompt_IA en al menos un 30% respecto de la versión monolítica actual, eliminando la totalidad de los ejemplos de cálculo aritmético de bitmasks.
5. WHERE se requieran ejemplos para guiar al Proveedor_IA, THE Prompt_IA SHALL incluir como máximo 5 ejemplos, seleccionados para cubrir cada tipo de recurrencia soportado al menos una vez.
6. WHEN el Backend construye el Prompt_IA para una solicitud, THE Backend SHALL incluir la fecha actual y la fecha de mañana en formato ISO 8601 (AAAA-MM-DD) como contexto para la interpretación de expresiones temporales relativas ("hoy", "mañana").
7. WHEN el Motor_Recurrencia calcula los bitmasks a partir de los datos estructurados extraídos, THE Motor_Recurrencia SHALL producir bitmasks idénticos a los que generaba la versión monolítica del Prompt_IA para la misma solicitud de entrada.
8. IF el Proveedor_IA devuelve datos estructurados incompletos o con un formato no interpretable, THEN THE Backend SHALL rechazar la solicitud sin invocar el cálculo de bitmasks y SHALL devolver una indicación de error que identifique los campos faltantes o inválidos, preservando la solicitud original sin modificaciones.

### Requisito 4: Mantenimiento único (once)

**Historia de Usuario:** Como operador de Zabbix, quiero crear un mantenimiento único con fecha y hora de inicio y fin, para poder programar una ventana puntual de mantenimiento.

#### Criterios de Aceptación

1. WHEN se solicita un mantenimiento con Tipo_Recurrencia `once`, THE Cliente_Zabbix SHALL crear un periodo con `timeperiod_type` igual a 0.
2. WHEN se crea un mantenimiento `once`, THE Backend SHALL establecer `start_date` igual al timestamp de inicio y `period` igual a la diferencia entre el timestamp de fin y el de inicio.
3. IF el timestamp de fin es menor o igual al timestamp de inicio, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error.
4. WHEN se crea un mantenimiento `once`, THE Backend SHALL establecer `active_since` y `active_till` con los timestamps de inicio y fin de la ventana.

### Requisito 5: Mantenimiento diario (daily)

**Historia de Usuario:** Como operador de Zabbix, quiero programar mantenimientos diarios, para poder repetir una ventana cada cierto número de días.

#### Criterios de Aceptación

1. WHEN se solicita un mantenimiento con Tipo_Recurrencia `daily`, THE Cliente_Zabbix SHALL crear un periodo con `timeperiod_type` igual a 2.
2. WHEN se crea un mantenimiento `daily`, THE Backend SHALL establecer `start_time` en segundos desde medianoche, `period` igual a la duración en segundos y `every` igual al número de días de intervalo.
3. IF la configuración de recurrencia está ausente para un mantenimiento `daily`, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error.
4. WHERE no se especifique el intervalo `every`, THE Backend SHALL usar el valor 1 por defecto.

### Requisito 6: Mantenimiento semanal (weekly)

**Historia de Usuario:** Como operador de Zabbix, quiero programar mantenimientos semanales en uno o varios días de la semana, para poder repetir ventanas en días específicos.

#### Criterios de Aceptación

1. WHEN se solicita un mantenimiento con Tipo_Recurrencia `weekly`, THE Cliente_Zabbix SHALL crear un periodo con `timeperiod_type` igual a 3.
2. WHEN se crea un mantenimiento `weekly`, THE Backend SHALL establecer `start_time` en segundos desde medianoche, `period` igual a la duración en segundos, `dayofweek` igual al Bitmask_Dias y `every` igual al número de semanas de intervalo.
3. THE Backend SHALL soportar cualquier combinación de días de la semana codificada como Bitmask_Dias en el rango de 1 a 127.
4. IF el Bitmask_Dias está ausente en la configuración semanal, THEN THE Backend SHALL rechazar la solicitud con un mensaje que indique que falta el día de la semana.
5. IF el Bitmask_Dias no es un entero en el rango de 1 a 127, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error de bitmask inválido.
6. WHERE no se especifique el intervalo `every`, THE Backend SHALL usar el valor 1 por defecto.

### Requisito 7: Mantenimiento mensual por día del mes (monthly - day of month)

**Historia de Usuario:** Como operador de Zabbix, quiero programar mantenimientos mensuales en un día específico del mes, para poder repetir ventanas en una fecha fija del mes.

#### Criterios de Aceptación

1. WHEN se solicita un mantenimiento `monthly` que especifica un día del mes, THE Cliente_Zabbix SHALL crear un periodo con `timeperiod_type` igual a 4 y el campo `day` igual al día del mes.
2. WHEN se crea un mantenimiento mensual por día del mes, THE Backend SHALL establecer `start_time`, `period`, `day`, `every` (cada X meses) y `month` igual al Bitmask_Meses.
3. IF el día del mes no está en el rango de 1 a 31, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error.
4. WHERE no se especifique el Bitmask_Meses, THE Backend SHALL usar el valor 4095 (todos los meses) por defecto.
5. IF el Bitmask_Meses no es un entero en el rango de 1 a 4095, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error de bitmask de meses inválido.

### Requisito 8: Mantenimiento mensual por día de la semana (monthly - day of week)

**Historia de Usuario:** Como operador de Zabbix, quiero programar mantenimientos mensuales en una ocurrencia de semana y día de la semana (por ejemplo, primer lunes), para poder repetir ventanas relativas a la posición dentro del mes.

#### Criterios de Aceptación

1. WHEN se solicita un mantenimiento `monthly` que especifica día de la semana, THE Cliente_Zabbix SHALL crear un periodo con `timeperiod_type` igual a 4, el campo `dayofweek` igual al Bitmask_Dias y `every` igual a la Ocurrencia_Semana.
2. THE Backend SHALL soportar las ocurrencias de semana primera (1), segunda (2), tercera (3), cuarta (4) y última (5), así como combinaciones de ellas.
3. WHEN se crea un mantenimiento mensual por día de la semana, THE Backend SHALL establecer `start_time`, `period`, `dayofweek`, `every` y `month` igual al Bitmask_Meses.
4. IF se especifican simultáneamente día del mes y día de la semana en la misma configuración mensual, THEN THE Backend SHALL rechazar la solicitud indicando que solo se permite uno de los dos.
5. IF no se especifica ni día del mes ni día de la semana en una configuración mensual, THEN THE Backend SHALL rechazar la solicitud solicitando el dato faltante.
6. WHERE no se especifique la Ocurrencia_Semana, THE Backend SHALL usar el valor 1 (primera semana) por defecto.

### Requisito 9: Validación de parámetros de recurrencia

**Historia de Usuario:** Como operador de Zabbix, quiero que el sistema valide los parámetros de recurrencia antes de crear el mantenimiento, para evitar la creación de mantenimientos incorrectos en Zabbix.

#### Criterios de Aceptación

1. IF el Tipo_Recurrencia no es uno de `once`, `daily`, `weekly` o `monthly`, THEN THE Backend SHALL rechazar la solicitud con un mensaje de tipo de recurrencia no válido.
2. IF el Tipo_Recurrencia es distinto de `once` y falta la configuración de recurrencia, THEN THE Backend SHALL rechazar la solicitud con un mensaje que solicite los detalles.
3. IF falta `start_time` en la configuración de un mantenimiento recurrente, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error.
4. IF falta `duration` en la configuración de un mantenimiento recurrente, THEN THE Backend SHALL rechazar la solicitud con un mensaje de error.
5. WHEN todos los parámetros de recurrencia son válidos, THE Backend SHALL invocar al Cliente_Zabbix para crear el mantenimiento.

### Requisito 10: Detección y gestión de tickets

**Historia de Usuario:** Como operador de Zabbix, quiero que el sistema detecte números de ticket en mi solicitud, para que los mantenimientos queden asociados al ticket correspondiente.

#### Criterios de Aceptación

1. WHEN el mensaje del usuario contiene un identificador con formato `XXX-XXXXXX` (tres dígitos, guion, tres a seis dígitos), THE Backend SHALL extraer el Numero_Ticket.
2. THE Backend SHALL reconocer los formatos de ticket con prefijos `ticket:` y `#` además del formato base.
3. IF el Proveedor_IA no incluye el Numero_Ticket pero el Backend lo detecta localmente, THEN THE Backend SHALL incorporar el Numero_Ticket detectado a la solicitud.
4. WHEN existe un Numero_Ticket, THE Backend SHALL usarlo como componente principal del nombre del mantenimiento.
5. WHEN existe un Numero_Ticket, THE Backend SHALL incluirlo en la descripción del mantenimiento en una línea propia sin duplicarlo en el texto.

### Requisito 11: Autenticación de usuario de Zabbix

**Historia de Usuario:** Como administrador de seguridad, quiero que solo los usuarios autenticados en Zabbix puedan crear mantenimientos, para impedir accesos no autorizados.

#### Criterios de Aceptación

1. WHEN se recibe una solicitud en un endpoint que ejecuta acciones sobre Zabbix, THE Backend SHALL validar la Info_Usuario antes de ejecutar la acción.
2. THE Backend SHALL validar la Info_Usuario consultando la existencia del userid mediante la API de Zabbix.
3. IF la Info_Usuario está ausente o no contiene un userid válido, THEN THE Backend SHALL rechazar la solicitud con un código de estado 401 y un mensaje de acceso no autorizado.
4. WHEN la Info_Usuario es válida, THE Backend SHALL incluir los datos del usuario en la descripción del mantenimiento y en el mensaje de confirmación.

### Requisito 12: Abstracción de proveedores de IA (Gemini y OpenAI)

**Historia de Usuario:** Como responsable técnico, quiero poder seleccionar entre Gemini y OpenAI mediante configuración, para elegir el proveedor de IA según costo y disponibilidad.

#### Criterios de Aceptación

1. THE Backend SHALL seleccionar el Proveedor_IA a partir de una variable de entorno que admita los valores `gemini` y `openai`.
2. WHERE el proveedor configurado es `openai`, THE Backend SHALL usar la clave de API y el modelo de OpenAI definidos por configuración.
3. WHERE el proveedor configurado es `gemini`, THE Backend SHALL usar la clave de API y el modelo de Gemini definidos por configuración.
4. THE Backend SHALL exponer una interfaz común de invocación al Proveedor_IA independiente del proveedor concreto seleccionado.
5. IF el Proveedor_IA seleccionado no está configurado correctamente o no está disponible, THEN THE Backend SHALL responder con un mensaje indicando que el asistente de IA no está disponible.
6. IF el valor de la variable de proveedor no está soportado, THEN THE Backend SHALL registrar un error de proveedor no soportado.

### Requisito 13: Interpretación conversacional de solicitudes

**Historia de Usuario:** Como operador de Zabbix, quiero describir mantenimientos en lenguaje natural y recibir respuestas conversacionales, para no tener que aprender un formato rígido.

#### Criterios de Aceptación

1. WHEN el usuario solicita crear un mantenimiento con datos suficientes, THE Backend SHALL devolver una respuesta de tipo solicitud de mantenimiento con los datos estructurados interpretados.
2. WHEN el usuario pide ejemplos o ayuda, THE Backend SHALL devolver una respuesta de tipo ayuda con ejemplos de uso.
3. WHEN el usuario envía una consulta no relacionada con la creación de mantenimientos, THE Backend SHALL devolver una respuesta de tipo fuera de tema orientando al usuario.
4. IF la solicitud es sobre mantenimiento pero faltan datos, THEN THE Backend SHALL devolver una respuesta de tipo aclaración indicando qué información falta.
5. THE Backend SHALL reconocer terminología de infraestructura (CIs, servidores, equipos, routers, switches, nodos, instancias, appliances) como referencias a hosts.
6. WHEN el usuario emplea expresiones temporales relativas ("hoy", "mañana"), THE Backend SHALL resolverlas usando la fecha actual y la fecha del día siguiente.

### Requisito 14: Búsqueda y resolución de hosts y grupos

**Historia de Usuario:** Como operador de Zabbix, quiero que el sistema encuentre los hosts y grupos mencionados aunque no use nombres exactos, para no tener que conocer el nombre exacto de cada recurso.

#### Criterios de Aceptación

1. WHEN se solicita un mantenimiento con nombres de hosts, THE Backend SHALL buscar primero coincidencias exactas de host mediante el Cliente_Zabbix.
2. WHEN un host no se encuentra por coincidencia exacta, THE Backend SHALL realizar una búsqueda flexible por término para ese host.
3. WHEN se solicita un mantenimiento con nombres de grupos, THE Backend SHALL buscar coincidencias exactas y, si no las hay, realizar una búsqueda flexible por término.
4. WHERE la solicitud incluye trigger tags, THE Backend SHALL obtener los hosts que coincidan con esos tags.
5. THE Backend SHALL eliminar hosts duplicados por identificador antes de crear el mantenimiento.
6. IF no se encuentra ningún host ni grupo válido, THEN THE Backend SHALL devolver una respuesta de aclaración solicitando verificar los nombres.
7. WHEN existen recursos solicitados que no se encontraron, THE Backend SHALL informar cuáles hosts y grupos faltan junto con los encontrados.

### Requisito 15: Compatibilidad del contrato de API y del widget

**Historia de Usuario:** Como usuario del widget de Zabbix ya instalado, quiero que la v2 funcione con el widget existente, para no tener que rehacer la integración del frontend.

#### Criterios de Aceptación

1. THE Backend SHALL exponer los endpoints `POST /chat`, `POST /parse`, `POST /create_maintenance`, `GET /health`, `POST /search_hosts`, `POST /search_groups`, `GET /maintenance/list`, `GET /maintenance/templates` y `POST /test/routine`.
2. THE Backend SHALL responder a `POST /parse` con el mismo formato de petición y respuesta que `POST /chat`.
3. THE Backend SHALL preservar los campos de respuesta que el Frontend_Widget consume actualmente para cada endpoint, sin eliminarlos, sin cambiar sus tipos de dato y sin renombrarlos.
4. WHEN el Frontend_Widget envía una solicitud con el formato actual, THE Backend SHALL responder con la misma estructura de campos y tipos de dato que la versión previa.
5. THE Backend SHALL habilitar CORS respondiendo a las solicitudes preflight y emitiendo las cabeceras de origen permitido para el consumo desde el Frontend_Widget.
6. THE Frontend_Widget SHALL conservar su identificador, namespace y estructura de widget compatibles con Zabbix 7.2 o superior.
7. IF una solicitud a un endpoint llega con campos requeridos ausentes o inválidos, THEN THE Backend SHALL devolver una indicación de error sin alterar el estado del sistema.
8. WHERE una solicitud incluye los campos opcionales `tags_evaltype` y el `operator` de los tags de problemas, THE Backend SHALL aceptarlos como campos adicionales del Contrato_API sin romper la compatibilidad de los campos existentes ni alterar el formato de respuesta previo.

### Requisito 16: Endpoint de salud (health)

**Historia de Usuario:** Como operador del despliegue, quiero un endpoint de salud, para verificar el estado del servicio y su conectividad con Zabbix.

#### Criterios de Aceptación

1. WHEN se consulta el endpoint de salud, THE Backend SHALL devolver el estado del servicio, la marca de tiempo, el estado de conexión con Zabbix, el proveedor de IA activo y la versión.
2. WHILE la conexión con Zabbix está disponible, THE Backend SHALL reportar el estado como saludable.
3. IF la conexión con Zabbix no está disponible, THEN THE Backend SHALL reportar el estado como degradado.
4. THE Backend SHALL listar las funcionalidades soportadas en la respuesta del endpoint de salud.

### Requisito 17: Separación de backend y frontend

**Historia de Usuario:** Como desarrollador del proyecto, quiero que el backend y el frontend estén en partes claramente distinguibles, para poder versionarlos y desplegarlos de forma independiente.

#### Criterios de Aceptación

1. THE Sistema_v2 SHALL ubicar el código del Backend y el del Frontend_Widget en carpetas de nivel superior separadas y claramente identificables.
2. THE Backend SHALL poder construirse y ejecutarse sin depender de archivos del Frontend_Widget.
3. THE Frontend_Widget SHALL poder empaquetarse e instalarse en Zabbix sin depender del código fuente del Backend.
4. THE Sistema_v2 SHALL documentar de forma separada las instrucciones de despliegue del Backend y del Frontend_Widget.

### Requisito 18: Despliegue con Docker

**Historia de Usuario:** Como operador del despliegue, quiero desplegar el backend con Docker igual que en la versión anterior, para mantener el mismo flujo de operación.

#### Criterios de Aceptación

1. THE Backend SHALL incluir un Dockerfile que construya una imagen ejecutable del servicio.
2. THE Backend SHALL incluir una definición de docker-compose para ejecutar el servicio localmente.
3. THE Backend SHALL incluir un archivo de ejemplo de variables de entorno que documente las variables requeridas (URL y token de Zabbix, proveedor y claves de IA, modelos).
4. WHEN el contenedor se inicia sin las variables de entorno requeridas para la IA, THE Backend SHALL registrar el error correspondiente sin exponer valores secretos.
5. THE Backend SHALL leer toda la configuración sensible desde variables de entorno y no incluir secretos en el código ni en la imagen.

### Requisito 19: Migración al repositorio de GitHub existente

**Historia de Usuario:** Como responsable del proyecto, quiero publicar la v2 en el mismo repositorio de GitHub del proyecto actual, para mantener la continuidad del historial y del flujo de publicación.

#### Criterios de Aceptación

1. THE Sistema_v2 SHALL conservar la compatibilidad con el flujo de publicación al repositorio de GitHub existente del proyecto.
2. THE Sistema_v2 SHALL mantener la estructura necesaria para la publicación de la imagen de contenedor en el registro utilizado actualmente.
3. THE Sistema_v2 SHALL incluir documentación de instalación y uso actualizada en el repositorio.
4. WHERE existan flujos de trabajo de integración continua en el repositorio, THE Sistema_v2 SHALL mantener la compatibilidad con la estructura de carpetas esperada por dichos flujos.

### Requisito 20: Paridad funcional y ausencia de regresiones

**Historia de Usuario:** Como responsable del proyecto, quiero garantizar que la v2 reproduce exactamente el comportamiento de creación de mantenimientos de la versión actual, para no perder ninguna capacidad existente.

#### Criterios de Aceptación

1. THE Sistema_v2 SHALL producir, para cada Tipo_Recurrencia y combinación de bitmasks equivalente, los mismos parámetros de `timeperiods` de Zabbix que la versión actual, con igualdad exacta campo por campo.
2. FOR ALL combinaciones válidas de Bitmask_Dias en el rango 1 a 127 (127 casos), THE Motor_Recurrencia SHALL producir el mismo valor `dayofweek` que el cálculo de la versión actual.
3. FOR ALL combinaciones válidas de Bitmask_Meses en el rango 1 a 4095 (4095 casos), THE Motor_Recurrencia SHALL producir el mismo valor `month` que el cálculo de la versión actual.
4. FOR ALL combinaciones válidas de Ocurrencia_Semana en el rango 1 a 5, THE Motor_Recurrencia SHALL producir el mismo valor `every` que el cálculo de la versión actual.
5. THE Sistema_v2 SHALL incluir pruebas automatizadas que verifiquen la generación correcta de parámetros para los tipos `once`, `daily`, `weekly`, `monthly` por día del mes y `monthly` por día de la semana, con al menos un caso por tipo.
6. THE Sistema_v2 SHALL incluir pruebas que verifiquen la decodificación de los 7 días de la semana y los 12 meses a nombres legibles usados en los mensajes de confirmación.
7. IF una prueba de paridad detecta una diferencia entre el valor generado por el Sistema_v2 y el valor esperado de la versión actual, THEN la prueba SHALL fallar reportando la entrada, el valor esperado y el valor obtenido.

### Requisito 21: Soporte de idiomas (i18n)

**Historia de Usuario:** Como usuario de Zabbix en un entorno multilingüe, quiero que el asistente muestre sus textos y responda en mi idioma, para poder usar el sistema en el idioma configurado sin depender de un único idioma fijo.

#### Criterios de Aceptación

1. THE Frontend_Widget SHALL usar el mecanismo de traducción de Zabbix para todos sus textos de interfaz, de modo que dichos textos sean traducibles.
2. THE Frontend_Widget SHALL externalizar sus cadenas de texto de interfaz como claves traducibles, sin incrustar textos de interfaz literales en la lógica del widget.
3. WHEN el Frontend_Widget envía una solicitud al Backend, THE Frontend_Widget SHALL incluir un parámetro Locale que identifique el idioma solicitado.
4. WHEN una solicitud incluye un parámetro Locale soportado, THE Backend SHALL generar los mensajes conversacionales, confirmaciones y errores en el idioma indicado por ese Locale.
5. IF una solicitud no incluye el parámetro Locale, THEN THE Backend SHALL resolver el Locale al valor por defecto `es`.
6. IF una solicitud incluye un Locale no soportado, THEN THE Backend SHALL resolver el Locale al valor por defecto `es`.
7. THE Backend SHALL exponer la resolución del Locale como una función pura que, dado un Locale de entrada opcional y el conjunto de locales soportados, devuelve el Locale efectivo aplicando las reglas de valor por defecto de forma determinista.
8. THE Frontend_Widget SHALL usar el mecanismo nativo de traducción de Zabbix como implementación concreta de la traducción de textos de interfaz, empleando `_()` en PHP y `t()` en JavaScript, y registrando las cadenas de JavaScript mediante `getTranslationStrings()` en la clase del widget.

### Requisito 22: Modularización de la lógica JavaScript del widget

**Historia de Usuario:** Como desarrollador que mantiene el widget, quiero que la lógica JavaScript esté separada por responsabilidades, para poder mantener y probar cada parte sin trabajar sobre una única clase que mezcla todas las funciones.

#### Criterios de Aceptación

1. THE Frontend_Widget SHALL separar su lógica JavaScript en módulos distintos por responsabilidad, incluyendo como mínimo: renderizado de interfaz, cliente HTTP y formateo de mensajes.
2. THE Frontend_Widget SHALL evitar que un único módulo o clase concentre simultáneamente el renderizado de interfaz, la comunicación HTTP y el formateo de mensajes.
3. THE Frontend_Widget SHALL aislar la comunicación con el Backend en un módulo de cliente HTTP reutilizable, independiente de la lógica de renderizado.
4. WHERE exista lógica de formateo de mensajes compartida entre vistas del widget, THE Frontend_Widget SHALL ubicarla en un módulo reutilizable en lugar de duplicarla.

### Requisito 23: Accesibilidad del widget (WCAG 2.1 AA)

**Historia de Usuario:** Como usuario que utiliza tecnologías de asistencia o navegación por teclado, quiero que el widget sea accesible, para poder operarlo sin depender exclusivamente del ratón ni de la percepción visual del color.

#### Criterios de Aceptación

1. THE Frontend_Widget SHALL asignar roles y etiquetas ARIA apropiados a sus elementos interactivos.
2. THE Frontend_Widget SHALL presentar el texto normal con una relación de contraste mínima de 4.5:1 respecto de su fondo.
3. THE Frontend_Widget SHALL presentar el texto grande con una relación de contraste mínima de 3:1 respecto de su fondo.
4. THE Frontend_Widget SHALL permitir operar todos sus controles mediante teclado usando las teclas Tab, Enter y Escape.
5. WHEN un control del Frontend_Widget recibe el foco por teclado, THE Frontend_Widget SHALL mostrar un indicador de foco visible.

### Requisito 24: Mejoras de experiencia de usuario del chat

**Historia de Usuario:** Como operador que conversa con el asistente, quiero indicadores claros del estado del sistema y una vista previa comprensible del mantenimiento, para saber qué ocurre y confirmar la acción antes de crearla.

#### Criterios de Aceptación

1. WHILE el Frontend_Widget espera la respuesta del Backend, THE Frontend_Widget SHALL mostrar un indicador de escritura o procesamiento.
2. THE Frontend_Widget SHALL conservar el historial de la conversación durante la sesión activa.
3. IF una solicitud al Backend falla, THEN THE Frontend_Widget SHALL mostrar una acción de reintento manual visible.
4. WHEN el Backend interpreta una solicitud de mantenimiento con datos suficientes, THE Frontend_Widget SHALL mostrar una vista previa legible del mantenimiento antes de su creación, decodificando los días y meses seleccionados a lenguaje natural.
5. THE Backend SHALL exponer la decodificación de Bitmask_Dias y Bitmask_Meses a nombres legibles como funciones puras que, dado un bitmask válido, devuelven la lista de nombres correspondientes de forma determinista.

### Requisito 25: Soporte de tema claro y oscuro

**Historia de Usuario:** Como usuario de Zabbix, quiero que el widget respete el tema activo de la interfaz, para tener una apariencia consistente con el resto de mi entorno.

#### Criterios de Aceptación

1. THE Frontend_Widget SHALL adaptar sus estilos al tema activo de Zabbix, admitiendo al menos tema claro y tema oscuro.
2. WHEN el tema activo de Zabbix es oscuro, THE Frontend_Widget SHALL aplicar los estilos correspondientes al tema oscuro.
3. WHEN el tema activo de Zabbix es claro, THE Frontend_Widget SHALL aplicar los estilos correspondientes al tema claro.
4. THE Frontend_Widget SHALL evitar el uso de estilos de color fijos que ignoren el tema activo de Zabbix.

### Requisito 26: Failover entre proveedores de IA

**Historia de Usuario:** Como responsable de disponibilidad, quiero que el sistema conmute a un proveedor de IA secundario cuando el primario falle, para reducir las interrupciones del servicio.

#### Criterios de Aceptación

1. WHERE se configura un Proveedor_IA secundario, IF el Proveedor_IA primario falla o excede su tiempo límite, THEN THE Backend SHALL realizar un Failover al Proveedor_IA secundario.
2. THE Backend SHALL acotar el Failover mediante un número máximo de reintentos y un tiempo límite configurables.
3. IF todos los Proveedor_IA configurados fallan, THEN THE Backend SHALL degradar de forma controlada devolviendo un mensaje explícito de indisponibilidad del asistente de IA.
4. WHERE no se configura un Proveedor_IA secundario, IF el Proveedor_IA primario falla, THEN THE Backend SHALL degradar de forma controlada devolviendo un mensaje explícito de indisponibilidad del asistente de IA.
5. WHEN se produce un Failover, THE Backend SHALL registrar el evento en el Log_Seguro sin exponer valores secretos.

### Requisito 27: Caché de validación de usuario

**Historia de Usuario:** Como responsable de rendimiento, quiero cachear las validaciones de usuario exitosas, para evitar consultar la API de Zabbix en cada solicitud y reducir la latencia.

#### Criterios de Aceptación

1. WHEN una validación de Info_Usuario resulta exitosa, THE Backend SHALL almacenar el resultado en caché con un TTL_Cache configurable.
2. WHILE existe una entrada de caché de Info_Usuario vigente para un usuario, THE Backend SHALL usar la entrada cacheada en lugar de consultar la API de Zabbix.
3. IF la entrada de caché de Info_Usuario está ausente o ha expirado según su TTL_Cache, THEN THE Backend SHALL revalidar la Info_Usuario consultando la API de Zabbix.
4. THE Backend SHALL determinar la expiración de una entrada de caché mediante una función pura que, dados la marca de tiempo de creación de la entrada, el TTL_Cache y la marca de tiempo actual, devuelve de forma determinista si la entrada está vigente o expirada.

### Requisito 28: Limitación de tasa de solicitudes (rate limiting)

**Historia de Usuario:** Como administrador del servicio, quiero limitar la tasa de solicitudes por cliente, para prevenir el abuso y el costo descontrolado de la IA.

#### Criterios de Aceptación

1. THE Backend SHALL aplicar un Rate_Limit configurable de solicitudes por cliente sobre sus endpoints.
2. WHEN un cliente realiza una solicitud dentro de su Rate_Limit permitido, THE Backend SHALL procesar la solicitud normalmente.
3. IF un cliente excede su Rate_Limit dentro de la ventana de tiempo configurada, THEN THE Backend SHALL rechazar la solicitud devolviendo una indicación de límite de tasa excedido con el código de estado 429.
4. THE Backend SHALL determinar si una solicitud excede el Rate_Limit mediante una función pura que, dados el contador de solicitudes del cliente en la ventana actual y el límite configurado, devuelve de forma determinista si la solicitud se permite o se rechaza.

### Requisito 29: Validación de la respuesta de IA con JSON Schema

**Historia de Usuario:** Como responsable de correctitud, quiero validar la respuesta estructurada de la IA contra un esquema formal, para descartar respuestas malformadas antes de procesarlas.

#### Criterios de Aceptación

1. WHEN el Proveedor_IA devuelve una respuesta estructurada, THE Backend SHALL validarla contra el Esquema_JSON antes de procesarla.
2. IF la respuesta estructurada del Proveedor_IA no cumple el Esquema_JSON, THEN THE Backend SHALL descartarla y reintentar la solicitud al Proveedor_IA hasta un número máximo de intentos configurable.
3. IF se alcanza el número máximo de intentos sin obtener una respuesta que cumpla el Esquema_JSON, THEN THE Backend SHALL reportar un error de respuesta de IA inválida sin invocar el cálculo de bitmasks.
4. THE Backend SHALL exponer la validación contra el Esquema_JSON como una función pura que, dada una respuesta estructurada y el Esquema_JSON, devuelve de forma determinista si la respuesta es válida junto con la lista de campos que incumplen el esquema.

### Requisito 30: Observabilidad y registro seguro

**Historia de Usuario:** Como operador del despliegue, quiero métricas de la aplicación y registros que no expongan secretos, para supervisar el servicio de forma segura.

#### Criterios de Aceptación

1. THE Backend SHALL exponer un endpoint de Metricas de la aplicación en un formato compatible con Prometheus.
2. THE Backend SHALL usar registro estructurado (Log_Seguro) para sus eventos operativos.
3. WHEN el Backend registra un evento que contiene campos sensibles (tokens, claves de API, credenciales), THE Backend SHALL enmascarar dichos campos de modo que sus valores no aparezcan en los registros.
4. THE Backend SHALL exponer el enmascaramiento de campos sensibles como una función pura que, dado un registro con campos sensibles, devuelve de forma determinista una copia del registro con los valores de dichos campos enmascarados y los valores no sensibles intactos.

### Requisito 31: Validación del rango de duración y redondeo a minutos

**Historia de Usuario:** Como operador de Zabbix, quiero que el sistema valide la duración del mantenimiento dentro del rango admitido por Zabbix y sea coherente con el redondeo a minutos, para evitar que Zabbix rechace o altere de forma inesperada los periodos creados.

#### Criterios de Aceptación

1. WHEN el Backend construye un periodo de mantenimiento, THE Backend SHALL validar que la duración `period` en segundos esté dentro del Rango_Period (300 a 86399940 segundos, ambos inclusive).
2. IF la duración `period` en segundos es menor que 300 o mayor que 86399940, THEN THE Backend SHALL rechazar la solicitud con un mensaje de duración fuera de rango.
3. THE Backend SHALL calcular los campos `active_since`, `active_till`, `period`, `start_date` y `start_time` de forma coherente con el redondeo hacia abajo a minutos que aplica Zabbix, sin depender de precisión de segundos.
4. THE Backend SHALL exponer la validación del Rango_Period como una función pura que, dada una duración en segundos, devuelve de forma determinista si la duración es válida, tratando 299 como inválida, 300 como válida, 86399940 como válida y 86400000 como inválida.

### Requisito 32: Tags de problemas y método de evaluación

**Historia de Usuario:** Como operador de Zabbix, quiero limitar la supresión de problemas de un mantenimiento a los que coincidan con ciertos tags, para suprimir solo los problemas relevantes durante la ventana de mantenimiento.

#### Criterios de Aceptación

1. THE Backend SHALL soportar el campo Tags_Evaltype con los valores 0 (And/Or, valor por defecto) y 2 (Or).
2. THE Backend SHALL modelar cada tag de problema con los campos `tag`, `operator` (Operador_Tag: 0 = Equals, 2 = Contains por defecto) y `value`.
3. IF se especifican tags de problemas Y `maintenance_type` es 1 (sin recolección de datos), THEN THE Backend SHALL rechazar la solicitud indicando que los tags de problemas solo se permiten cuando `maintenance_type` es 0.
4. WHERE no se especifican tags de problemas, THE Backend SHALL permitir que se supriman todos los problemas de los hosts en mantenimiento, conforme al comportamiento por defecto de Zabbix.
5. IF el valor de Tags_Evaltype no es 0 ni 2, THEN THE Backend SHALL rechazar la solicitud con un mensaje de método de evaluación de tags no válido.
6. IF el valor de Operador_Tag no es 0 ni 2, THEN THE Backend SHALL rechazar la solicitud con un mensaje de operador de tag no válido.

### Requisito 33: Compatibilidad del módulo de widget con la versión actual de Zabbix

**Historia de Usuario:** Como usuario del widget en la versión actual de Zabbix (7.4), quiero que el módulo de widget siga la estructura y los mecanismos nativos vigentes, para que se instale y funcione correctamente en dicha versión.

#### Criterios de Aceptación

1. THE Frontend_Widget SHALL declarar `manifest_version` como el valor numérico 2.0 (no como cadena de texto) en el archivo `manifest.json`.
2. THE Frontend_Widget SHALL usar el mecanismo nativo de traducción de Zabbix para las cadenas traducibles, empleando `_()` en PHP y `t()` en JavaScript, y registrando las cadenas de JavaScript mediante `getTranslationStrings()` en la clase del widget, complementando el Requisito 21 sin reemplazarlo.
3. THE Frontend_Widget SHALL seguir la estructura de módulo de widget de la versión actual, con una clase que extiende CWidget, un controlador que extiende CControllerDashboardWidgetView, un formulario basado en CWidgetForm y CWidgetField, y las vistas `widget.view` y `widget.edit`, preservando su identificador y namespace.
4. WHERE el formulario de configuración del widget lo permita, THE Frontend_Widget SHALL aprovechar la validación inline de formularios y el selector de color con paletas disponibles en la versión actual de Zabbix.
