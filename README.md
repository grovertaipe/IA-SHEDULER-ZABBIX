# AI Maintenance Assistant for Zabbix 7.2+

Sistema interactivo de mantenimientos para Zabbix 7.2+ con inteligencia
artificial. Permite crear mantenimientos únicos y rutinarios usando lenguaje
natural, con soporte para programaciones avanzadas (días, meses, ocurrencias de
semana) y gestión de tickets de cualquier nomenclatura.

El proyecto se compone de dos piezas que se **despliegan de forma independiente**:

- **[`backend/`](backend/README.md)** — servicio HTTP/Flask (Python 3.11+). La IA
  interpreta la solicitud en lenguaje natural y el backend crea el mantenimiento
  en Zabbix.
- **[`widget/aimaintenance/`](widget/aimaintenance/README.md)** — módulo de widget
  para el dashboard de Zabbix (PHP/JS), compatible con Zabbix 7.2+ (probado
  también en 7.4).

## Arquitectura

```
┌────────────────────────┐        ┌────────────────────────────┐
│  widget/aimaintenance/ │  HTTP  │         backend/           │
│  (Zabbix dashboard)    │◄──────►│    (Python / Flask API)    │
│                        │  API   │                            │
│  • UI + chat           │        │  • Interpretación por IA   │
│  • Backend API URL      │        │    (Gemini / OpenAI)       │
│  • Sin lógica de negocio│        │  • Cálculo determinista    │
│                        │        │  • Cliente Zabbix JSON-RPC │
└────────────────────────┘        └────────────────────────────┘
```

**Idea central:** la IA solo extrae datos estructurados (días/meses/ocurrencias,
horas, duración, hosts, grupos, tickets, tipo de recurrencia). El backend realiza
todos los cálculos de forma determinista y crea el mantenimiento en Zabbix vía
JSON-RPC. El widget no contiene lógica de negocio: consume la API del backend
mediante una URL configurable.

## Características

- 🤖 Chat conversacional con IA para crear mantenimientos en lenguaje natural.
  Proveedores soportados: **Google Gemini**, **OpenAI** y **Amazon Bedrock**
  (Amazon Nova Lite), con failover configurable entre ellos.
- 🔄 Mantenimientos únicos y rutinarios: diarios, semanales y mensuales (por día
  del mes o por día de la semana).
- 🎫 Detección automática de tickets de **cualquier nomenclatura**
  (`INC0012345`, `JIRA-4521`, `CHG-2024-001`, `#88213`, `100-178306`, ...): la IA
  los extrae y se incluyen en el nombre y la descripción del mantenimiento.
- 🌐 Interfaz multilenguaje (español, inglés, portugués) que sigue el idioma del
  usuario de Zabbix.
- 🔒 Seguridad: cada solicitud que actúa se autentica contra Zabbix mediante la
  **sesión** del usuario (`user.checkAuthentication`); solo quienes tienen una
  sesión válida de Zabbix pueden operar. Incluye límite de peticiones.
- 🎯 Búsqueda de hosts y grupos (exacta, flexible y por tags).
- 🩺 Observabilidad: `GET /health` y `GET /metrics` (Prometheus).

## Inicio rápido

Cada pieza se despliega por separado. Consulta su README:

- Backend (Docker, ejecución local, endpoints, pruebas): **[`backend/README.md`](backend/README.md)**
- Widget (empaquetado e instalación en Zabbix): **[`widget/aimaintenance/README.md`](widget/aimaintenance/README.md)**

Resumen del backend con Docker:

```bash
cd backend
cp .env.example .env        # Edita ZABBIX_API_URL, ZABBIX_TOKEN, la clave de IA, etc.
docker compose up --build -d
```

Esto levanta las instancias `aima1..aima5` en los puertos **5005–5009**.

## Seguridad / despliegue seguro

- **Autenticación real por sesión.** El backend autentica cada solicitud que
  actúa contra Zabbix con `user.checkAuthentication`: el widget envía el
  identificador de **sesión** del usuario logueado y el backend confía solo en
  la identidad que Zabbix verifica. Ninguna solicitud se confía en un `userid`
  provisto por el cliente; sin sesión válida la respuesta es **HTTP 401**.
- **Ejecuta el backend detrás de TLS/HTTPS.** El identificador de sesión viaja
  al backend, así que usa un proxy inverso con HTTPS y nunca lo expongas por
  HTTP plano en una red no confiable.
- **Restringe el acceso de red** para que solo el host del frontend de Zabbix
  alcance el backend (firewall / security group o interfaz interna).
- **Secretos por entorno**, nunca horneados en la imagen ni en logs.

### TLS (seguro por defecto)

Dos aspectos independientes, ambos seguros por defecto:

- **Salida a Zabbix.** El backend verifica el certificado TLS de Zabbix por
  defecto. `ZABBIX_VERIFY_TLS` (por defecto `true`) solo debe ponerse en `false`
  para un Zabbix autofirmado que no puedas confiar de otra forma; **preferible**
  usar `ZABBIX_CA_BUNDLE` (ruta a un bundle PEM de una CA privada), que tiene
  precedencia sobre el booleano.
- **Entrada desde el navegador/widget.** El `docker-compose.yml` incluye un
  proxy inverso **Caddy**. Tres modos: **autofirmado** (por defecto —
  autofirmado para tu IP/FQDN vía `AIMA_TLS_HOSTS`, generado automáticamente por
  un contenedor init; el navegador avisa una vez y aceptas la excepción, como
  Elasticsearch/Kibana), **tu propio certificado**, o **Let's Encrypt/ACME** con
  un dominio real. Con TLS activo, apunta la "Backend API URL" del widget a
  `https://<host>` (443) y expón **solo** el proxy (deja de publicar el puerto
  crudo del backend).

Detalles y guía completa en **[`backend/README.md`](backend/README.md)** →
sección "Seguridad / despliegue seguro" (subsección "TLS").

## Estructura del repositorio

```
.
├── backend/                 # Servicio Flask (desplegable de forma independiente)
│   └── README.md            # Guía de despliegue del backend
├── widget/                  # Widget de Zabbix (desplegable de forma independiente)
│   ├── aimaintenance/       # Módulo del widget
│   │   └── README.md        # Empaquetado e instalación
│   └── Makefile             # Empaquetado del zip del widget
├── .github/workflows/       # CI: publica la imagen y adjunta el zip del widget
├── docs/                    # Documentación e imágenes
├── CHANGELOG.md
└── README.md
```

## Publicación (GitHub / GHCR)

La integración continua (`.github/workflows/docker-publish.yml`) automatiza la
publicación:

- **Imagen del backend** → se construye desde `./backend` y se publica en
  **GitHub Container Registry**: `ghcr.io/grovertaipe/ia-sheduler-zabbix`.
  Se dispara en push a `main` (tag `latest`) y en tags `vX.Y.Z` (semver).
- **Zip del widget** → en cada tag `vX.Y.Z` se empaqueta `widget/aimaintenance`
  y se adjunta como asset del GitHub Release.

## Ejemplo del widget

![Widget del asistente de mantenimiento](docs/images/captura1.png)

![Formulario del widget](docs/images/captura2.png)

## Licencia y soporte

Proyecto desarrollado por **Grover T.** bajo licencia **MIT**.

- **Repositorio:** [GitHub](https://github.com/grovertaipe/IA-SHEDULER-ZABBIX)
- **Imagen Docker:** [ghcr.io/grovertaipe/ia-sheduler-zabbix](https://ghcr.io/grovertaipe/ia-sheduler-zabbix)
- **Zabbix:** 7.2+ · **Python:** 3.11+

---

**Versión:** 2.0.0 · **Autor:** Grover T.
