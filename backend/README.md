# AI Maintenance for Zabbix 7.2 (API)

Servicio Flask para crear y gestionar mantenimientos (únicos y rutinarios) en Zabbix 7.2 con ayuda de IA (Gemini u OpenAI). Soporta detección de tickets en el nombre del mantenimiento.

## 🚀 Ejecución rápida con Docker
```bash
cp .env.example .env
# Edita .env con tus valores (ZABBIX_API_URL, ZABBIX_TOKEN, IA, etc.)
docker compose up -d --build
