# AI Maintenance Backend

API Flask para crear y gestionar mantenimientos en Zabbix 7.2 con inteligencia artificial.

## Instalación

### Con Docker (Recomendado)

#### Instancia Única
```bash
# Clonar repositorio
git clone https://github.com/grovertaipe/ia-scheduler-zabbix.git
cd ia-scheduler-zabbix/backend

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores

# Ejecutar
docker compose up -d --build
```

#### Múltiples Instancias

Para manejar múltiples servidores Zabbix:

```yaml
# docker-compose-multi.yml
version: '3.8'

x-aima: &aima_base
  image: ghcr.io/grovertaipe/ia-sheduler-zabbix:latest
  restart: unless-stopped
  extra_hosts:
    - "host.docker.internal:host-gateway"
  networks:
    - aimaintenance_net

services:
  aima1:
    <<: *aima_base
    container_name: aima1
    env_file: [ ./env/aima1.env ]
    environment:
      TZ: "America/Lima"
    ports: [ "5005:5005" ]
    
  aima2:
    <<: *aima_base
    container_name: aima2
    env_file: [ ./env/aima2.env ]
    environment:
      TZ: "America/Lima"
    ports: [ "5006:5005" ]

networks:
  aimaintenance_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.31.10.0/24
```

**Archivos de configuración por instancia:**

```bash
# env/aima1.env
ZABBIX_API_URL=https://zabbix1.example.com/api_jsonrpc.php
ZABBIX_TOKEN=your_zabbix_token_1
AI_PROVIDER=gemini
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash
TZ=America/Lima

# env/aima2.env
ZABBIX_API_URL=https://zabbix2.example.com/api_jsonrpc.php
ZABBIX_TOKEN=your_zabbix_token_2
AI_PROVIDER=gemini
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-1.5-flash
TZ=America/Lima
```

#### Docker Run (Instancia Única)
```bash
docker run -d \
  --name aima-backend \
  --restart unless-stopped \
  -p 5005:5005 \
  -e ZABBIX_API_URL="https://your-zabbix.com/api_jsonrpc.php" \
  -e ZABBIX_TOKEN="your_api_token" \
  -e AI_PROVIDER="gemini" \
  -e GOOGLE_API_KEY="your_gemini_key" \
  -e GEMINI_MODEL="gemini-2.0-flash" \
  -e TZ="America/Lima" \
  ghcr.io/grovertaipe/ia-sheduler-zabbix:latest
```

### Instalación Local

```bash
cd backend
pip install -r requirements.txt
python src/main.py
```

## Configuración

### Variables de Entorno Requeridas

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `ZABBIX_API_URL` | URL de la API de Zabbix | `https://zabbix.com/api_jsonrpc.php` |
| `ZABBIX_TOKEN` | Token de API de Zabbix 7.2 | `abc123...` |
| `AI_PROVIDER` | Proveedor de IA (`gemini` o `openai`) | `gemini` |
| `GOOGLE_API_KEY` | API Key de Google Gemini | `AIza...` |
| `GEMINI_MODEL` | Modelo de Gemini | `gemini-2.0-flash` |
| `TZ` | Timezone | `America/Lima` |

### Ejemplo .env

```bash
ZABBIX_API_URL=https://your-zabbix.com/api_jsonrpc.php
ZABBIX_TOKEN=your_api_token
AI_PROVIDER=gemini
GOOGLE_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.0-flash
TZ=America/Lima
```

## API Endpoints

### Principales
- `POST /chat` - Chat interactivo principal
- `POST /create_maintenance` - Crear mantenimiento
- `GET /health` - Estado del sistema

### Utilidades
- `POST /search_hosts` - Buscar hosts
- `POST /search_groups` - Buscar grupos
- `GET /maintenance/list` - Listar mantenimientos
- `GET /maintenance/templates` - Plantillas rutinarias
- `POST /test/routine` - Probar configuraciones

### Ejemplo de Respuesta
```json
{
  "type": "maintenance_request",
  "hosts": ["srv-web01"],
  "start_time": "2025-08-24 10:00",
  "end_time": "2025-08-24 16:00",
  "recurrence_type": "weekly",
  "recurrence_config": {
    "start_time": 18000,
    "duration": 7200,
    "dayofweek": 24,
    "every": 1
  },
  "ticket_number": "100-178306",
  "confidence": 95
}
```

## Health Check

```bash
curl http://localhost:5005/health
```

## Logs

```bash
# Docker
docker logs aima-backend

# Local
python src/main.py
```

## Troubleshooting

### Backend no inicia
```bash
# Verificar variables de entorno
docker exec aima-backend env | grep -E "(ZABBIX|AI_|GOOGLE)"

# Verificar conectividad a Zabbix
curl -X POST https://your-zabbix.com/api_jsonrpc.php \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_token" \
  -d '{"jsonrpc":"2.0","method":"user.get","params":{"limit":1},"id":1}'
```