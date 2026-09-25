# AI Maintenance Assistant — Backend (Zabbix 7.2+)

Backend HTTP/Flask del "AI Maintenance Assistant" para Zabbix 7.2+. Se despliega
de forma **independiente del widget**: el widget solo consume esta API a través
de una URL configurable.

- **Lenguaje:** Python 3.11+ / Flask (app factory).
- **Entry point WSGI:** `app:create_app()` (fábrica de la aplicación, sin lógica
  de negocio).
- **Rol:** la IA extrae **datos estructurados** (días/meses/ocurrencias, horas,
  duración, hosts, grupos, tickets, tipo de recurrencia). El backend calcula los
  **bitmasks de forma determinista** en el núcleo puro (`core/`) y crea el
  mantenimiento en Zabbix vía JSON-RPC.
- **Frontend:** se despliega por separado. Consulta
  [`../widget/aimaintenance/README.md`](../widget/aimaintenance/README.md).

## Requisitos previos

- Python **3.11 o superior** (para ejecución local) o Docker.
- Un servidor **Zabbix 7.2+** accesible y un **token de API** con permisos de
  mantenimiento.
- Una clave de API de un proveedor de IA: **Google Gemini** (por defecto) u
  **OpenAI**.

## Configuración (variables de entorno)

Toda la configuración se lee desde variables de entorno en `config.py`
(`AppConfig.from_env`). Copia el archivo de ejemplo y complétalo con tus valores:

```bash
cp .env.example .env
# Edita .env con tus valores reales
```

Consulta [`.env.example`](.env.example) para la lista completa y documentada.
Variables **base** (obligatorias para operar):

| Variable | Descripción |
|----------|-------------|
| `ZABBIX_API_URL` | Endpoint JSON-RPC de Zabbix (`.../api_jsonrpc.php`) |
| `ZABBIX_TOKEN` | Token de API de Zabbix (secreto) |
| `AI_PROVIDER` | Proveedor de IA: `gemini` u `openai` |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | Credencial y modelo de Gemini |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Credencial y modelo de OpenAI |
| `CORS_ALLOWED_ORIGINS` | Orígenes permitidos, explícitos (nunca `*`) |
| `APP_VERSION` | Versión reportada por `/health`. **Opcional**: se inyecta automáticamente al construir la imagen desde el tag de git (build-arg de Docker en CI); definirla en `.env` solo la sobreescribe |

Variables **extendidas** (con valores por defecto seguros): localización
(`SUPPORTED_LOCALES`, `DEFAULT_LOCALE`), failover de IA
(`AI_SECONDARY_PROVIDER`, `AI_FAILOVER_MAX_RETRIES`,
`AI_FAILOVER_TIMEOUT_SECONDS`), caché de usuario (`USER_CACHE_TTL_SECONDS`),
rate limiting (`RATE_LIMIT_MAX_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`) y
validación de esquema (`AI_SCHEMA_MAX_ATTEMPTS`).

> Los secretos nunca se incluyen en la imagen ni en el repositorio: `.env` está
> ignorado por git y por el contexto de build de Docker.

## Despliegue con Docker (recomendado)

El `docker-compose.yml` define cinco instancias `aima1..aima5` mapeadas a los
puertos de host **5005–5009** (cada contenedor escucha en el 5005 internamente).
Todas comparten la misma imagen (construida una sola vez) y la misma
configuración desde `.env`.

```bash
cp .env.example .env
# Edita .env
docker compose up --build -d
```

Comprobar estado y logs:

```bash
docker compose ps
docker compose logs -f aima1
```

### Instancia única

```bash
docker build -t aimaintenance-backend:latest .
docker run -d --name aima1 -p 5005:5005 --env-file .env aimaintenance-backend:latest
```

## Ejecución local (sin Docker)

```bash
python -m venv .venv
source .venv/bin/activate          # En Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # y edítalo

# Servidor de producción (WSGI) apuntando a la app factory:
gunicorn --bind 0.0.0.0:5005 --workers 2 --timeout 60 "app:create_app()"

# Alternativa para desarrollo con Flask:
export FLASK_APP="app:create_app"  # En Windows: set FLASK_APP=app:create_app
flask run --port 5005
```

## Endpoints

Principales:

- `POST /chat` — chat interactivo (extracción por IA).
- `POST /parse` — alias de `/chat` con formato de respuesta idéntico.
- `POST /create_maintenance` — crea el mantenimiento en Zabbix.
- `GET /maintenance/list` — lista mantenimientos.
- `GET /maintenance/templates` — plantillas de recurrencia.
- `POST /test/routine` — prueba una configuración rutinaria.

Utilidades:

- `POST /search_hosts` — busca hosts.
- `POST /search_groups` — busca grupos.

Operación / observabilidad:

- `GET /health` — estado del servicio: `status` (`healthy`/`degraded`),
  timestamp, conexión con Zabbix, proveedor de IA, versión y funcionalidades.
- `GET /metrics` — métricas en formato Prometheus (contadores de solicitudes,
  latencias, tasas de error, eventos de failover), sin exponer configuración
  sensible.

Ejemplo de health check:

```bash
curl http://localhost:5005/health
```

## Seguridad / despliegue seguro

- **Autenticación real por sesión de Zabbix.** El backend autentica **cada
  solicitud que actúa** (chat, creación/listado de mantenimientos, búsquedas)
  contra Zabbix mediante `user.checkAuthentication`: el widget envía el
  identificador de **sesión** del usuario logueado en el frontend de Zabbix y el
  backend le pregunta a Zabbix a quién pertenece esa sesión, confiando **solo**
  en la identidad que Zabbix verifica. Ninguna solicitud se confía en un
  `userid` provisto por el cliente. Si la sesión falta, es inválida o expiró, la
  respuesta es **HTTP 401** (fail-closed).
- **Usa TLS/HTTPS.** El identificador de sesión viaja del navegador al backend,
  por lo que el backend **debe** exponerse detrás de un proxy inverso con
  **TLS/HTTPS**. Nunca lo expongas por HTTP plano en una red no confiable: un
  observador podría capturar la sesión.
- **Restringe el acceso de red al backend (defensa en profundidad).** Limita
  quién puede alcanzar el backend para que **solo el host del frontend de
  Zabbix** pueda hacerlo (firewall / security group, o enlazándolo a una
  interfaz interna). El backend no debe ser accesible públicamente.
- **Secretos por entorno, nunca en la imagen.** El token de Zabbix y las claves
  de IA se proveen en tiempo de ejecución vía variables de entorno y nunca se
  hornean en la imagen ni se registran en logs. El identificador de sesión
  tampoco se escribe en logs.

### TLS

Hay **dos** aspectos de TLS independientes. Ambos son seguros por defecto.

**1) Salida hacia la API de Zabbix (verificación de certificado).**
El backend verifica el certificado TLS de tu Zabbix por defecto (seguro).

- `ZABBIX_VERIFY_TLS` (por defecto `true`): déjalo en `true` en producción. Solo
  ponlo en `false` si tu Zabbix usa un certificado autofirmado que no puedes
  confiar de otra forma (relaja la verificación, como
  `ssl verification_mode=none` de Elasticsearch). Al desactivarlo se registra un
  aviso una sola vez y se silencia el ruido de urllib3.
- `ZABBIX_CA_BUNDLE` (opcional): ruta absoluta (dentro del contenedor) a un
  *bundle* de CA (PEM) para verificar contra una CA privada/interna. **Tiene
  precedencia** sobre `ZABBIX_VERIFY_TLS`. Es la opción **preferida** frente a
  desactivar la verificación; monta el archivo con un volumen.

**2) Entrada desde el navegador/widget (proxy inverso Caddy con auto-HTTPS).**
El `docker-compose.yml` incluye un servicio `caddy` que termina TLS y reenvía
HTTP plano al backend por la red interna (`aima1:5005`). Tres modos (ver
`Caddyfile`):

- **Autofirmado (por defecto, sin configuración).** `tls internal` genera un
  certificado con la CA interna de Caddy: funciona **sin dominio ni certificado
  externo**. El navegador avisará una vez — abre la URL del backend
  (`https://<host>`) directamente y **acepta la excepción** del certificado,
  igual que con Elasticsearch/Kibana.
- **Trae tu propio certificado.** Sustituye `tls internal` por
  `tls /certs/fullchain.pem /certs/privkey.pem` y monta los archivos con un
  volumen.
- **Dominio real con Let's Encrypt (ACME).** Reemplaza `:443` por
  `tu.dominio.com` y quita `tls internal`: Caddy aprovisiona y renueva el
  certificado automáticamente. Requiere un FQDN público y los puertos 80/443
  accesibles.

Con TLS activo, configura la **"Backend API URL"** del widget como
`https://<host>` (puerto 443) en lugar de `http://<host>:5015`. Recuerda que
`CORS_ALLOWED_ORIGINS` debe seguir listando el origen del frontend de Zabbix.

> Expón **solo** el proxy (443). En un despliegue con TLS deja de publicar el
> puerto crudo del backend (comenta el `ports:` de `aima1` en
> `docker-compose.yml`) para que el backend solo sea accesible dentro de la red
> de Docker.

> Cambio de seguridad importante (v2): se eliminó el mecanismo previo que solo
> comprobaba que un `userid` existiera en Zabbix. Ese esquema permitía que
> cualquiera que adivinara un `userid` válido (p. ej. `1` = Admin) actuara. El
> nuevo esquema exige una sesión válida de Zabbix. Este cambio requiere
> **redesplegar backend y widget**, **reinstalar el widget** y **refrescar el
> navegador**.

## Pruebas y calidad

El proyecto usa **pytest + Hypothesis** (con `pytest-cov`), **ruff** y **mypy**,
configurados en `pyproject.toml`.

```bash
pip install -r requirements.txt

# Suite completa (unitarias, propiedad e integración con mocks)
pytest

# Con cobertura
pytest --cov

# Lint y formato
ruff check .

# Comprobación de tipos
mypy
```

## Estructura del backend

```
backend/
├── app.py            # App factory / entry point (create_app)
├── config.py         # Configuración desde entorno (AppConfig)
├── api/              # Blueprints Flask (chat, maintenance, search, health, metrics)
├── services/         # Orquestación (chat_service, maintenance_service)
├── ai/               # Abstracción de proveedores de IA + prompt externalizado
├── core/             # Núcleo puro: motor de recurrencia y utilidades de dominio
├── zabbix/           # Cliente JSON-RPC de Zabbix 7.2
├── i18n/             # Localización (es/en)
├── cache/            # Caché de validación de usuario
├── observability/    # Métricas / logging seguro
├── tests/            # unit / property / integration / fixtures
├── Dockerfile        # Imagen del backend (gunicorn → app:create_app())
├── docker-compose.yml# Instancias aima1-5 (puertos 5005-5009)
└── .env.example      # Plantilla de configuración (sin secretos)
```

---

**Autor:** Grover T. · Licencia MIT · Zabbix 7.2+ · Python 3.11+
