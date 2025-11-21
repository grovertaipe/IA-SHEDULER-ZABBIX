# Guía Completa de Instalación

Esta guía te llevará paso a paso para instalar y configurar el sistema completo de AI Maintenance para Zabbix.

## Prerrequisitos

- Zabbix 7.2+
- Docker y Docker Compose
- Acceso administrativo a Zabbix
- API Key de Google Gemini o OpenAI

## Paso 1: Configurar el Backend

### 1.1 Clonar el Repositorio

```bash
git clone https://github.com/grovertaipe/ia-scheduler-zabbix.git
cd ia-scheduler-zabbix
```

### 1.2 Configurar Variables de Entorno

```bash
cd backend
cp .env.example .env
```

Editar `.env` con tus valores:

```bash
# Configuración de Zabbix
ZABBIX_API_URL=https://your-zabbix.com/api_jsonrpc.php
ZABBIX_TOKEN=your_zabbix_token

# Configuración de IA - Gemini
AI_PROVIDER=gemini
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash

# Timezone
TZ=America/Lima
```

### 1.3 Obtener Credenciales

#### Token de Zabbix
1. Login a Zabbix → **Administration → API tokens**
2. **Create API token** con permisos de mantenimiento
3. Copiar el token generado

#### Google Gemini API Key
1. Ir a [Google AI Studio](https://aistudio.google.com/)
2. **Get API key** → Create API key
3. Habilitar Gemini API en Google Cloud Console

### 1.4 Ejecutar el Backend

```bash
docker compose up -d --build
```

### 1.5 Verificar el Backend

```bash
curl http://localhost:5005/health
```

Respuesta esperada:
```json
{
  "status": "healthy",
  "zabbix_connected": true,
  "ai_provider": "gemini",
  "version": "1.7.0"
}
```

## Paso 2: Instalar el Widget

### 2.1 Descargar el Widget

Descargar la última versión desde `widget/releases/` o usar el código fuente.

### 2.2 Instalar en Zabbix

```bash
# Extraer el widget
sudo cp -r widget/src/aimaintenance /usr/share/zabbix/ui/modules/aimaintenance

# Verificar permisos
sudo chown -R www-data:www-data /usr/share/zabbix/ui/modules/aimaintenance
```

### 2.3 Escanear Módulos en Zabbix

1. Login a Zabbix como administrador
2. Ir a **Administration → General → Modules**
3. Hacer clic en **Scan directory**
4. Verificar que "AI Maintenance Assistant" aparezca en la lista

### 2.4 Agregar Widget al Dashboard

1. Ir a **Dashboard → Edit**
2. Hacer clic en **Add widget**
3. Seleccionar **AI Maintenance Assistant**
4. Configurar:
   - **Backend URL**: `http://localhost:5005`
   - **Refresh Interval**: `30s` (opcional)
5. Hacer clic en **Add**

## Paso 3: Verificar la Instalación

### 3.1 Probar el Chat

1. Abrir el dashboard con el widget
2. Escribir en el chat: "Hola"
3. Verificar que la IA responda

### 3.2 Crear un Mantenimiento de Prueba

```
"Mantenimiento para servidor test mañana de 8 a 10 AM"
```

### 3.3 Verificar en Zabbix

1. Ir a **Configuration → Maintenance**
2. Verificar que el mantenimiento se haya creado

## Configuración Avanzada

### Múltiples Instancias del Backend

Para manejar múltiples servidores Zabbix:

```yaml
# docker-compose.yml
version: '3.8'

services:
  aima1:
    image: ghcr.io/grovertaipe/ia-sheduler-zabbix:latest
    env_file: ./env/zabbix1.env
    ports: ["5005:5005"]
    
  aima2:
    image: ghcr.io/grovertaipe/ia-sheduler-zabbix:latest
    env_file: ./env/zabbix2.env
    ports: ["5006:5005"]
```

### Configuración de Proxy

Si Zabbix está detrás de un proxy, configurar las variables:

```bash
HTTP_PROXY=http://proxy:8080
HTTPS_PROXY=http://proxy:8080
NO_PROXY=localhost,127.0.0.1
```

## Troubleshooting

### Problema: Backend no inicia

**Solución:**
```bash
# Verificar logs
docker logs aima-backend

# Verificar variables de entorno
docker exec aima-backend env | grep ZABBIX
```

### Problema: Widget no aparece

**Solución:**
1. Verificar permisos: `sudo chown -R www-data:www-data /usr/share/zabbix/ui/modules/`
2. Hacer **Scan directory** en Zabbix
3. Verificar logs de Apache/Nginx

### Problema: IA no responde

**Solución:**
1. Verificar API Key de Gemini/OpenAI
2. Comprobar límites de rate limiting
3. Revisar balance de cuenta

### Problema: No se crean mantenimientos

**Solución:**
1. Verificar permisos del token de Zabbix
2. Comprobar conectividad a la API de Zabbix
3. Revisar logs del backend

## Soporte

- **Repository**: [GitHub](https://github.com/grovertaipe/ia-scheduler-zabbix)
- **Issues**: Reportar problemas en GitHub Issues
- **Documentation**: Ver README principal del proyecto