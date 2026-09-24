# AI Maintenance Assistant for Zabbix 7.2+

**Desarrollado por: Grover T.**

Sistema interactivo de mantenimientos para Zabbix 7.2+ con inteligencia
artificial. Permite crear mantenimientos únicos y rutinarios usando lenguaje
natural, con soporte para bitmasks avanzados (días, meses, ocurrencias de
semana) y gestión de tickets.

Esta es la **versión 2 (estructura limpia)**: el proyecto se separa en dos
artefactos de nivel superior que se **despliegan de forma independiente**
(Req 17.1, 17.4):

- **[`backend/`](backend/README.md)** — servicio HTTP/Flask (Python 3.11+). La
  IA extrae datos estructurados y el backend calcula los bitmasks de forma
  determinista.
- **[`widget/aimaintenance/`](widget/aimaintenance/README.md)** — módulo de
  widget para el dashboard de Zabbix (PHP/JS), compatible con Zabbix 7.2+
  (probado también en 7.4).

## Arquitectura

```
┌────────────────────────┐        ┌────────────────────────────┐
│  widget/aimaintenance/ │  HTTP  │        backend/            │
│  (Zabbix dashboard)    │◄──────►│    (Python / Flask API)    │
│                        │  API   │                            │
│  • UI + chat           │        │  • Extracción por IA       │
│  • Backend API URL      │        │    (Gemini / OpenAI)       │
│  • Sin lógica de negocio│        │  • Núcleo puro determinista│
│                        │        │  • Cliente Zabbix JSON-RPC │
└────────────────────────┘        └────────────────────────────┘
```

Idea central: **la IA solo extrae datos estructurados** (conjuntos de
días/meses/ocurrencias, horas, duración, hosts, grupos, tickets, tipo de
recurrencia). **El backend calcula los bitmasks de forma determinista** en un
núcleo puro verificado con pruebas basadas en propiedades y de paridad, sin
aritmética de bitmasks en el prompt de IA. El widget no contiene lógica de
negocio: consume la API del backend mediante una URL configurable.

## Características

- 🤖 Chat conversacional con IA (Google Gemini u OpenAI) para crear
  mantenimientos en lenguaje natural.
- 🔄 Mantenimientos únicos y rutinarios (diarios, semanales, mensuales por día
  del mes o por día de la semana) con bitmasks.
- 🎫 Detección automática de tickets de **cualquier nomenclatura**
  (`INC0012345`, `JIRA-4521`, `CHG-2024-001`, `#88213`, `100-178306`, ...): la IA
  los extrae y se incluyen en el nombre y la descripción del mantenimiento.
- 🎯 Búsqueda de hosts y grupos (exacta, flexible y por tags).
- 🩺 Observabilidad: `GET /health` y `GET /metrics` (Prometheus).

## Inicio rápido

Cada artefacto se despliega por separado. Consulta su README:

- Backend (Docker, ejecución local, endpoints, pruebas): **[`backend/README.md`](backend/README.md)**
- Widget (empaquetado e instalación en Zabbix): **[`widget/aimaintenance/README.md`](widget/aimaintenance/README.md)**

Resumen del backend con Docker:

```bash
cd backend
cp .env.example .env        # Edita ZABBIX_API_URL, ZABBIX_TOKEN, IA, etc.
docker compose up --build -d
```

Esto levanta las instancias `aima1..aima5` en los puertos **5005–5009**.

## Estructura del repositorio

```
.
├── backend/                 # Artefacto 1: servicio Flask (desplegable aparte)
│   └── README.md            # Guía de despliegue del backend
├── widget/                  # Artefacto 2: widget de Zabbix (desplegable aparte)
│   ├── aimaintenance/       # Módulo del widget (id/namespace preservados)
│   │   └── README.md        # Empaquetado e instalación
│   └── Makefile             # Empaquetado del zip del widget
├── .github/workflows/       # CI: publica imagen y adjunta el zip del widget
└── docs/                    # Documentación e imágenes
```

## Publicación (GitHub / GHCR)

El flujo de integración continua (`.github/workflows/docker-publish.yml`) se
mantiene compatible con el repositorio de GitHub y el registro de contenedores
existentes (Req 19.1, 19.2, 19.4):

- **Imagen del backend** → se construye desde `./backend` y se publica en
  **GitHub Container Registry**: `ghcr.io/grovertaipe/ia-sheduler-zabbix`.
  Se dispara en push a `main` (tag `latest`) y en tags `vX.Y.Z` (semver).
- **Zip del widget** → en cada tag `vX.Y.Z` se empaqueta `widget/aimaintenance`
  y se adjunta como asset del GitHub Release.

## Ejemplo del widget

![Widget mostrando hosts en mantenimiento](docs/images/captura1.png)

![Formulario del widget](docs/images/captura2.png)

## Licencia y soporte

Proyecto desarrollado por **Grover T.** bajo licencia **MIT**.

- **Repository:** [GitHub](https://github.com/grovertaipe/ia-scheduler-zabbix)
- **Docker Image:** [ghcr.io/grovertaipe/ia-sheduler-zabbix](https://ghcr.io/grovertaipe/ia-sheduler-zabbix)
- **Zabbix:** 7.2+ · **Python:** 3.11+

---

**Versión:** 2.0.0 · **Autor:** Grover T.
