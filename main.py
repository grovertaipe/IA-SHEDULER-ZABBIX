from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import datetime
import json
import re
import logging
from typing import List

# ----- Configuración de Logging -----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ----- Configuración de Variables -----
ZABBIX_API_URL = os.getenv("ZABBIX_API_URL", "")
ZABBIX_TOKEN = os.getenv("ZABBIX_TOKEN", "")
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()  # "gemini" | "openai"

# Configuración para OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")

# Configuración para Gemini
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")

# ----- Inicialización de la IA -----
openai_client = None
gemini_model = None
loaded_provider = None

if AI_PROVIDER == "openai":
    try:
        from openai import OpenAI
        if OPENAI_API_KEY:
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            loaded_provider = "openai"
            logger.info(f"OpenAI configurado. Modelo: {OPENAI_MODEL}")
        else:
            logger.error("Falta OPENAI_API_KEY para usar OpenAI")
    except Exception as e:
        logger.error(f"Error inicializando OpenAI: {e}")

elif AI_PROVIDER == "gemini":
    try:
        import google.generativeai as genai
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            gemini_model = genai.GenerativeModel(GEMINI_MODEL)
            loaded_provider = "gemini"
            logger.info(f"Gemini configurado. Modelo: {GEMINI_MODEL}")
        else:
            logger.error("Falta GOOGLE_API_KEY para usar Gemini")
    except Exception as e:
        logger.error(f"Error inicializando Gemini: {e}")
else:
    logger.error(f"Proveedor de IA no soportado: {AI_PROVIDER}")

app = Flask(__name__)
CORS(app)

# ----- Clase para la API de Zabbix (7.2) -----
class ZabbixAPI:
    """Clase para interactuar con la API de Zabbix 7.2"""
    
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
    
    def _make_request(self, method: str, params: dict) -> dict:
        """Método base para llamadas a la API"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        try:
            logger.info(f"Llamada API: {method} con parámetros: {params}")
            
            response = requests.post(
                self.url, 
                json=payload, 
                headers=self.headers, 
                timeout=30
            )
            
            logger.info(f"Status: {response.status_code}")
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Respuesta: {result}")
            
            if "error" in result:
                logger.error(f"Error en API Zabbix: {result['error']}")
                return {"error": result["error"]}
            
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en la solicitud a Zabbix API: {str(e)}")
            return {"error": f"Error de conexión: {str(e)}"}
        except json.JSONDecodeError as e:
            logger.error(f"Error decodificando respuesta JSON: {str(e)}")
            return {"error": f"Respuesta inválida del servidor: {str(e)}"}
    
    def get_hosts(self, host_names: List[str]) -> List[dict]:
        """Obtener información de hosts por nombre"""
        if not host_names:
            return []
            
        params = {
            "output": ["hostid", "host", "name", "status"],
            "filter": {"host": host_names}
        }
        
        result = self._make_request("host.get", params)
        
        if "error" in result:
            logger.error(f"Error obteniendo hosts: {result['error']}")
            return []
        
        hosts = result.get("result", [])
        logger.info(f"Hosts encontrados: {len(hosts)}")
        return hosts
    
    def search_hosts(self, search_term: str) -> List[dict]:
        """Buscar hosts que contengan el término de búsqueda"""
        params = {
            "output": ["hostid", "host", "name", "status"],
            "search": {"host": search_term, "name": search_term},
            "searchWildcardsEnabled": True,
            "limit": 20
        }
        
        result = self._make_request("host.get", params)
        
        if "error" in result:
            logger.error(f"Error buscando hosts: {result['error']}")
            return []
            
        return result.get("result", [])
    
    def get_hosts_by_tags(self, tags: List[dict]) -> List[dict]:
        """Obtener hosts que coincidan con los tags especificados"""
        if not tags:
            return []
            
        params = {
            "output": ["hostid", "host", "name", "status"],
            "evaltype": 0,  # AND/OR
            "tags": tags
        }
        
        result = self._make_request("host.get", params)
        
        if "error" in result:
            logger.error(f"Error obteniendo hosts por tags: {result['error']}")
            return []
            
        return result.get("result", [])
    
    def get_hostgroups(self, group_names: List[str]) -> List[dict]:
        """Obtener información de grupos por nombre"""
        if not group_names:
            return []
            
        params = {
            "output": ["groupid", "name"],
            "filter": {"name": group_names}
        }
        
        result = self._make_request("hostgroup.get", params)
        
        if "error" in result:
            logger.error(f"Error obteniendo grupos: {result['error']}")
            return []
            
        return result.get("result", [])
    
    def search_hostgroups(self, search_term: str) -> List[dict]:
        """Buscar grupos que contengan el término de búsqueda"""
        params = {
            "output": ["groupid", "name"],
            "search": {"name": search_term},
            "searchWildcardsEnabled": True,
            "limit": 20
        }
        
        result = self._make_request("hostgroup.get", params)
        
        if "error" in result:
            logger.error(f"Error buscando grupos: {result['error']}")
            return []
            
        return result.get("result", [])
    
    def get_hosts_by_groups(self, group_names: List[str]) -> List[dict]:
        """Obtener hosts pertenecientes a los grupos especificados"""
        if not group_names:
            return []
            
        # Primero obtener los IDs de los grupos
        groups_result = self._make_request("hostgroup.get", {
            "output": ["groupid", "name"],
            "filter": {"name": group_names}
        })
        
        if "error" in groups_result:
            logger.error(f"Error obteniendo grupos: {groups_result['error']}")
            return []
        
        groups = groups_result.get("result", [])
        if not groups:
            logger.warning(f"No se encontraron grupos: {group_names}")
            return []
        
        group_ids = [g["groupid"] for g in groups]
        
        # Obtener hosts de esos grupos
        params = {
            "output": ["hostid", "host", "name", "status"],
            "groupids": group_ids
        }
        
        result = self._make_request("host.get", params)
        
        if "error" in result:
            logger.error(f"Error obteniendo hosts por grupos: {result['error']}")
            return []
            
        return result.get("result", [])
    
    def create_maintenance(self, name: str, host_ids: List[str] = None, 
                         group_ids: List[str] = None, start_time: int = None, 
                         end_time: int = None, description: str = "", 
                         tags: List[dict] = None, recurrence_type: str = "once",
                         recurrence_config: dict = None) -> dict:
        """
        Crear un periodo de mantenimiento en Zabbix 7.2
        Soporta mantenimientos únicos y recurrentes
        
        recurrence_type: "once", "daily", "weekly", "monthly"
        recurrence_config: configuración específica para recurrencia
        """
        params = {
            "name": name,
            "active_since": start_time,
            "active_till": end_time,
            "description": description,
            "maintenance_type": 0,  # con recolección de datos
        }
        
        # Configurar períodos de tiempo según el tipo de recurrencia
        if recurrence_type == "once":
            # Mantenimiento único
            params["timeperiods"] = [{
                "timeperiod_type": 0,  # período único
                "start_date": start_time,
                "period": end_time - start_time
            }]
        elif recurrence_type == "daily":
            # Mantenimiento diario
            params["timeperiods"] = [{
                "timeperiod_type": 2,  # diario
                "start_time": recurrence_config.get("start_time", 0),  # hora en segundos desde medianoche
                "period": recurrence_config.get("duration", 3600),  # duración en segundos
                "every": recurrence_config.get("every", 1)  # cada X días
            }]
        elif recurrence_type == "weekly":
            # Mantenimiento semanal
            params["timeperiods"] = [{
                "timeperiod_type": 3,  # semanal
                "start_time": recurrence_config.get("start_time", 0),
                "period": recurrence_config.get("duration", 3600),
                "dayofweek": recurrence_config.get("dayofweek", 1),  # 1=lunes, 2=martes, etc.
                "every": recurrence_config.get("every", 1)  # cada X semanas
            }]
        elif recurrence_type == "monthly":
            # Mantenimiento mensual
            params["timeperiods"] = [{
                "timeperiod_type": 4,  # mensual
                "start_time": recurrence_config.get("start_time", 0),
                "period": recurrence_config.get("duration", 3600),
                "month": recurrence_config.get("month", 0),  # 0=todos los meses
                "dayofmonth": recurrence_config.get("dayofmonth", 1),  # día del mes
                "every": recurrence_config.get("every", 1)  # cada X meses
            }]
        
        # Agregar hosts específicos si se proporcionan
        if host_ids:
            params["hosts"] = [{"hostid": hid} for hid in host_ids]
        
        # Agregar grupos si se proporcionan
        if group_ids:
            params["groups"] = [{"groupid": gid} for gid in group_ids]
        
        # Agregar tags específicos para el mantenimiento si se proporcionan
        if tags:
            params["tags"] = tags
            
        return self._make_request("maintenance.create", params)

    def test_connection(self) -> dict:
        """Probar la conexión a la API"""
        result = self._make_request("user.get", {
            "output": ["userid", "username"],
            "limit": 1
        })
        return result

# ----- Clase para el Parser de IA (Ahora Interactivo) -----
class AIParser:
    """Clase para analizar solicitudes de mantenimiento usando IA de forma interactiva"""
    
    @staticmethod
    def _extract_ticket_number(text: str) -> str:
        """Extrae el número de ticket del texto del usuario"""
        # Patrones para diferentes formatos de ticket: 100-178306, 200-8341, 500-43116
        ticket_patterns = [
            r'\b\d{3}-\d{3,6}\b',  # Formato XXX-XXXXXX
            r'\bticket\s*:?\s*(\d{3}-\d{3,6})\b',  # "ticket: XXX-XXXXXX"
            r'\b#(\d{3}-\d{3,6})\b',  # "#XXX-XXXXXX"
        ]
        
        for pattern in ticket_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Si el patrón tiene grupos, tomar el grupo 1, sino tomar el match completo
                ticket = match.group(1) if match.groups() else match.group(0)
                logger.info(f"Ticket encontrado: {ticket}")
                return ticket
        
        logger.info("No se encontró número de ticket en el texto")
        return ""
    
    @staticmethod
    def _build_interactive_prompt(user_text: str) -> str:
        """Construye el prompt interactivo para la IA"""
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        tomorrow_date = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
        return f"""
Eres un asistente especializado en Zabbix que ayuda a crear mantenimientos. Eres amigable, útil y conversacional.

FECHA ACTUAL: {current_date}
FECHA MAÑANA: {tomorrow_date}

MENSAJE DEL USUARIO: "{user_text}"

ANÁLISIS DEL MENSAJE:
Determina qué tipo de mensaje es y responde apropiadamente:

1. **SOLICITUD DE MANTENIMIENTO VÁLIDA**: Si el usuario pide crear un mantenimiento, responde con JSON:
```json
{{
  "type": "maintenance_request",
  "hosts": ["servidor1", "servidor2"],  // array de strings con nombres de servidores específicos (opcional)
  "groups": ["grupo1", "grupo2"],       // array de strings con nombres de grupos (opcional) 
  "trigger_tags": [{{"tag": "component", "value": "cpu"}}], // array de objetos tag para triggers específicos (opcional)
  "start_time": "YYYY-MM-DD HH:MM",     // string en formato para inicio
  "end_time": "YYYY-MM-DD HH:MM",       // string en formato para fin
  "description": "Descripción del mantenimiento",
  "recurrence_type": "once",            // "once" | "daily" | "weekly" | "monthly"
  "recurrence_config": {{}},            // objeto con configuración de recurrencia (solo si no es "once")
  "ticket_number": "100-178306",        // string con número de ticket si se menciona
  "confidence": 95,                     // número 0-100 de confianza
  "message": "¡Perfecto! He preparado tu mantenimiento. Revisa los detalles y confirma si todo está correcto."
}}
```

2. **SOLICITUD DE EJEMPLO**: Si pide ejemplos, ayuda o no sabe cómo formular una solicitud:
```json
{{
  "type": "help_request",
  "message": "¡Por supuesto! Te ayudo con algunos ejemplos de cómo solicitar mantenimientos:\\n\\n📝 **Ejemplos Básicos:**\\n- \\"Mantenimiento para srv-web01 mañana de 8 a 10 con ticket 100-178306\\"\\n- \\"Poner srv-db01 en mantenimiento hoy de 14 a 16 horas\\"\\n- \\"Mantenimiento del grupo web-servers el domingo de 2 a 4 AM\\"\\n\\n🔄 **Mantenimientos Rutinarios:**\\n- \\"Backup diario para srv-backup de 2 a 4 AM con ticket 200-8341\\"\\n- \\"Mantenimiento semanal domingos para grupo database\\"\\n- \\"Limpieza mensual primer día del mes para todos los web-servers\\"\\n\\n🎫 **Con Tickets:**\\nSiempre puedes incluir números de ticket como: 100-178306, 200-8341, 500-43116\\n\\n¿Qué tipo de mantenimiento necesitas crear?",
  "examples": [
    {{
      "title": "Mantenimiento Simple",
      "example": "Mantenimiento para srv-web01 mañana de 8 a 10 con ticket 100-178306"
    }},
    {{
      "title": "Mantenimiento de Grupo", 
      "example": "Mantenimiento del grupo database el domingo de 2 a 4 AM ticket 200-8341"
    }},
    {{
      "title": "Mantenimiento Rutinario",
      "example": "Backup diario para srv-backup de 2 a 4 AM durante enero con ticket 500-43116"
    }}
  ]
}}
```

3. **CONSULTA NO RELACIONADA**: Si pregunta sobre otras cosas (estado, configuración, etc.):
```json
{{
  "type": "off_topic",
  "message": "¡Hola! Soy tu asistente especializado en **crear mantenimientos** en Zabbix. 🔧\\n\\nSolo puedo ayudarte con:\\n✅ Crear mantenimientos únicos\\n✅ Programar mantenimientos rutinarios (diarios, semanales, mensuales)\\n✅ Mantenimientos con tickets\\n\\n💡 **¿Necesitas crear un mantenimiento?** \\nDime algo como: \\"Mantenimiento para srv-web01 mañana de 8 a 10 con ticket 100-178306\\"\\n\\n❓ **¿Necesitas ejemplos?** \\nEscribe \\"ejemplos\\" o \\"ayuda\\" y te muestro cómo hacerlo.\\n\\nPara otras consultas de Zabbix, usa las herramientas principales del sistema. ¿Qué mantenimiento quieres crear?"
}}
```

4. **SOLICITUD INCOMPLETA O CONFUSA**: Si es sobre mantenimiento pero faltan datos:
```json
{{
  "type": "clarification_needed",
  "message": "Entiendo que quieres crear un mantenimiento, pero me faltan algunos detalles. 🤔\\n\\n**He detectado:** [explicar qué detectaste]\\n\\n**Necesito saber:**\\n- 🖥️ ¿Qué servidores o grupos?\\n- ⏰ ¿Cuándo? (fecha y hora)\\n- ⏱️ ¿Por cuánto tiempo?\\n- 🎫 ¿Tienes un número de ticket?\\n\\n**Ejemplo completo:**\\n\\"Mantenimiento para srv-web01 mañana de 8 a 10 con ticket 100-178306\\"\\n\\n¿Podrías darme más detalles?",
  "missing_info": ["hosts_or_groups", "timing", "duration"],
  "detected_info": {{}}
}}
```

DETECCIÓN DE TICKETS:
- Buscar patrones como: "100-178306", "200-8341", "500-43116"  
- Buscar frases como: "con ticket XXX-XXX", "ticket: XXX-XXX", "#XXX-XXX"

CONFIGURACIÓN DE RECURRENCIA:
Para "daily": {{"start_time": segundos_desde_medianoche, "duration": duración_en_segundos, "every": cada_x_días}}
Para "weekly": {{"start_time": segundos_desde_medianoche, "duration": duración_en_segundos, "dayofweek": día_semana, "every": cada_x_semanas}}  
Para "monthly": {{"start_time": segundos_desde_medianoche, "duration": duración_en_segundos, "dayofmonth": día_del_mes, "every": cada_x_meses}}

REGLAS IMPORTANTES:
- Sé conversacional y amigable en todos los mensajes
- Usa emojis moderadamente para hacer más amigable la experiencia
- Si detectas "mañana" usar {tomorrow_date}, si detectas "hoy" usar {current_date}
- Para horarios, usar formato 24h
- Si no se especifica hora, sugerir horario de mantenimiento típico (madrugada)
- Siempre ofrecer ayuda adicional al final de las respuestas

**RESPONDE ÚNICAMENTE CON EL JSON CORRESPONDIENTE AL TIPO DE MENSAJE DETECTADO.**

EJEMPLOS VÁLIDOS:

Usuario: "Mantenimiento para srv-web01 mañana de 8 a 10 con ticket 100-178306"
Respuesta: {{
  "hosts": ["srv-web01"],
  "groups": [],
  "trigger_tags": [],
  "start_time": "{tomorrow_date} 08:00",
  "end_time": "{tomorrow_date} 10:00",
  "description": "Mantenimiento programado para srv-web01 - Ticket: 100-178306",
  "recurrence_type": "once",
  "ticket_number": "100-178306",
  "confidence": 95
}}

Usuario: "Mantenimiento diario para grupo web-servers de 2 AM a 4 AM durante enero ticket 200-8341"
Respuesta: {{
  "hosts": [],
  "groups": ["web-servers"],
  "trigger_tags": [],
  "start_time": "2025-01-01 02:00",
  "end_time": "2025-01-31 04:00",
  "description": "Mantenimiento diario para grupo web-servers - Ticket: 200-8341",
  "recurrence_type": "daily",
  "recurrence_config": {{"start_time": 7200, "duration": 7200, "every": 1}},
  "ticket_number": "200-8341",
  "confidence": 90
}}

Usuario: "Poner srv-db01 en mantenimiento hoy de 14 a 16 horas"
Respuesta: {{
  "hosts": ["srv-db01"],
  "groups": [],
  "trigger_tags": [],
  "start_time": "{current_date} 14:00",
  "end_time": "{current_date} 16:00",
  "description": "Mantenimiento programado para srv-db01",
  "recurrence_type": "once",
  "ticket_number": "",
  "confidence": 90
}}
"""
    
    @staticmethod
    def _call_openai(prompt: str) -> str:
        """Llama a la API de OpenAI"""
        if not openai_client:
            raise RuntimeError("OpenAI no está configurado correctamente")
        
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Eres un asistente amigable especializado en crear mantenimientos para Zabbix. Respondes de forma conversacional y útil."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1200
        )
        return response.choices[0].message.content if response.choices else ""
    
    @staticmethod
    def _call_gemini(prompt: str) -> str:
        """Llama a la API de Gemini"""
        if not gemini_model:
            raise RuntimeError("Gemini no está configurado correctamente")
        
        response = gemini_model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 1200
            }
        )
        return response.text if hasattr(response, "text") else ""
    
    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extrae el JSON de la respuesta de la IA"""
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if not json_match:
                return {"error": "No se encontró JSON en la respuesta"}
            return json.loads(json_match.group())
        except json.JSONDecodeError as e:
            return {"error": f"Error decodificando JSON: {str(e)}"}
    
    @classmethod
    def parse_interactive_request(cls, user_text: str) -> dict:
        """Analiza cualquier solicitud del usuario de forma interactiva"""
        # Extracción del ticket como respaldo
        ticket_number = cls._extract_ticket_number(user_text)
        
        prompt = cls._build_interactive_prompt(user_text)
        
        try:
            if loaded_provider == "openai":
                content = cls._call_openai(prompt)
            elif loaded_provider == "gemini":
                content = cls._call_gemini(prompt)
            else:
                return {
                    "type": "error", 
                    "message": "❌ El asistente de IA no está disponible en este momento. Por favor, inténtalo más tarde."
                }
            
            if not content:
                return {
                    "type": "error",
                    "message": "😔 No pude procesar tu solicitud. ¿Podrías intentar de nuevo con más detalles?"
                }
            
            parsed_data = cls._extract_json(content)
            if "error" in parsed_data:
                return {
                    "type": "error",
                    "message": f"⚠️ Hubo un problema procesando tu mensaje: {parsed_data['error']}"
                }
            
            # Si es una solicitud de mantenimiento, hacer validaciones adicionales
            if parsed_data.get("type") == "maintenance_request":
                # Si la IA no detectó el ticket pero nosotros sí, agregarlo
                if not parsed_data.get("ticket_number") and ticket_number:
                    parsed_data["ticket_number"] = ticket_number
                    logger.info(f"Ticket agregado por detección local: {ticket_number}")
                
                # Validación básica de los campos requeridos para mantenimientos
                required_fields = ["start_time", "end_time", "recurrence_type"]
                for field in required_fields:
                    if field not in parsed_data:
                        return {
                            "type": "error",
                            "message": f"⚠️ Información incompleta: falta {field}. ¿Podrías proporcionar más detalles?"
                        }
                
                # Validar recurrence_type
                valid_recurrence = ["once", "daily", "weekly", "monthly"]
                if parsed_data["recurrence_type"] not in valid_recurrence:
                    return {
                        "type": "error", 
                        "message": f"⚠️ Tipo de recurrencia no válido. Usa: once, daily, weekly o monthly."
                    }
                
                # Si no es "once", debe tener recurrence_config
                if parsed_data["recurrence_type"] != "once" and "recurrence_config" not in parsed_data:
                    return {
                        "type": "error",
                        "message": "⚠️ Falta configuración para el mantenimiento rutinario. ¿Podrías especificar más detalles?"
                    }
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"Error en el parser interactivo de IA: {str(e)}")
            return {
                "type": "error",
                "message": f"😔 Ocurrió un error inesperado: {str(e)}. ¿Podrías intentar de nuevo?"
            }

# ----- Función para generar nombre del mantenimiento -----
def generate_maintenance_name(parsed_data: dict, host_names: list = None, group_names: list = None) -> str:
    """
    Genera el nombre del mantenimiento basado en el ticket y tipo de recurrencia
    """
    ticket_number = parsed_data.get("ticket_number", "").strip()
    recurrence_type = parsed_data.get("recurrence_type", "once")
    
    # Prefijo base según tipo de mantenimiento
    if recurrence_type == "once":
        base_prefix = "AI Maintenance"
    else:
        base_prefix = "AI Maintenance Rutinario"
    
    # Si hay ticket, usarlo como nombre principal
    if ticket_number:
        return f"{base_prefix}: {ticket_number}"
    
    # Si no hay ticket, usar el sistema actual (nombres de recursos)
    maintenance_name_parts = []
    
    if host_names:
        maintenance_name_parts.extend(host_names[:3])
        if len(host_names) > 3:
            maintenance_name_parts.append(f"y {len(host_names)-3} hosts más")
    
    if group_names:
        maintenance_name_parts.extend([f"Grupo {name}" for name in group_names[:2]])
        if len(group_names) > 2:
            maintenance_name_parts.append(f"y {len(group_names)-2} grupos más")
    
    if maintenance_name_parts:
        return f"{base_prefix}: {', '.join(maintenance_name_parts)}"
    else:
        return f"{base_prefix}: Recursos varios"

# ----- Inicialización de servicios -----
zabbix_api = ZabbixAPI(ZABBIX_API_URL, ZABBIX_TOKEN)

# ----- Endpoints de la API -----
@app.route("/health", methods=["GET"])
def health_check():
    """Endpoint para verificar el estado del servicio"""
    zabbix_status = zabbix_api.test_connection()
    zabbix_ok = "result" in zabbix_status and not ("error" in zabbix_status)
    
    return jsonify({
        "status": "healthy" if zabbix_ok else "degraded",
        "timestamp": datetime.datetime.now().isoformat(),
        "zabbix_connected": zabbix_ok,
        "zabbix_version": zabbix_status.get("result", "unknown") if zabbix_ok else "error",
        "ai_provider": loaded_provider or AI_PROVIDER,
        "version": "1.5.0",
        "features": ["interactive_chat", "routine_maintenance", "daily", "weekly", "monthly", "ticket_support"]
    })

@app.route("/chat", methods=["POST"])
def chat_endpoint():
    """Endpoint principal para chat interactivo"""
    try:
        data = request.json
        if not data or "message" not in data:
            return jsonify({
                "type": "error",
                "message": "😅 Parece que tu mensaje llegó vacío. ¿Podrías escribir tu solicitud de mantenimiento?"
            }), 400
        
        user_text = data["message"].strip()
        if not user_text:
            return jsonify({
                "type": "error", 
                "message": "😅 No recibí ningún mensaje. ¿Qué mantenimiento necesitas crear?"
            }), 400
        
        logger.info(f"💬 Mensaje recibido: {user_text}")
        
        # Analizar la solicitud con IA
        ai_response = AIParser.parse_interactive_request(user_text)
        
        # Si no es una solicitud de mantenimiento, devolver la respuesta de la IA directamente
        if ai_response.get("type") != "maintenance_request":
            return jsonify(ai_response)
        
        # Es una solicitud de mantenimiento - procesar con Zabbix
        logger.info("🔧 Procesando solicitud de mantenimiento...")
        
        # Buscar entidades por diferentes métodos
        found_hosts = []
        found_groups = []
        missing_hosts = []
        missing_groups = []
        
        # 1. Buscar hosts específicos
        if ai_response.get("hosts"):
            logger.info(f"🔍 Buscando hosts: {ai_response['hosts']}")
            
            # Búsqueda exacta
            hosts_by_name = zabbix_api.get_hosts(ai_response["hosts"])
            found_hosts.extend(hosts_by_name)
            found_host_names = [h["host"] for h in hosts_by_name]
            
            # Búsqueda flexible para hosts no encontrados
            missing_host_names = [h for h in ai_response["hosts"] if h not in found_host_names]
            
            for missing_host in missing_host_names:
                flexible_results = zabbix_api.search_hosts(missing_host)
                if flexible_results:
                    found_hosts.extend(flexible_results)
                else:
                    missing_hosts.append(missing_host)
        
        # 2. Buscar grupos
        if ai_response.get("groups"):
            logger.info(f"🔍 Buscando grupos: {ai_response['groups']}")
            
            # Búsqueda exacta de grupos
            groups_by_name = zabbix_api.get_hostgroups(ai_response["groups"])
            found_groups.extend(groups_by_name)
            found_group_names = [g["name"] for g in groups_by_name]
            
            # Búsqueda flexible para grupos no encontrados
            missing_group_names = [g for g in ai_response["groups"] if g not in found_group_names]
            
            for missing_group in missing_group_names:
                flexible_results = zabbix_api.search_hostgroups(missing_group)
                if flexible_results:
                    found_groups.extend(flexible_results)
                else:
                    missing_groups.append(missing_group)
        
        # 3. Buscar hosts por trigger tags
        hosts_by_tags = []
        if ai_response.get("trigger_tags"):
            logger.info(f"🏷️ Buscando por trigger tags: {ai_response['trigger_tags']}")
            hosts_by_tags = zabbix_api.get_hosts_by_tags(ai_response["trigger_tags"])
            found_hosts.extend(hosts_by_tags)
        
        # Eliminar duplicados en hosts
        unique_hosts = {h["hostid"]: h for h in found_hosts}.values()
        
        logger.info(f"✅ Resultados - Hosts: {len(unique_hosts)}, Grupos: {len(found_groups)}")
        
        # Construir respuesta con información adicional
        response_data = {
            **ai_response,
            "found_hosts": list(unique_hosts),
            "found_groups": found_groups,
            "missing_hosts": missing_hosts,
            "missing_groups": missing_groups,
            "original_message": user_text,
            "search_summary": {
                "total_hosts_found": len(unique_hosts),
                "total_groups_found": len(found_groups),
                "hosts_by_tags": len(hosts_by_tags),
                "has_missing": len(missing_hosts) > 0 or len(missing_groups) > 0,
                "is_routine": ai_response.get("recurrence_type", "once") != "once",
                "has_ticket": bool(ai_response.get("ticket_number", "").strip())
            }
        }
        
        # Si hay recursos faltantes, actualizar el mensaje para ser más informativo
        if missing_hosts or missing_groups:
            missing_info = []
            if missing_hosts:
                missing_info.append(f"hosts: {', '.join(missing_hosts)}")
            if missing_groups:
                missing_info.append(f"grupos: {', '.join(missing_groups)}")
            
            response_data["message"] = f"⚠️ He preparado tu mantenimiento, pero no encontré algunos recursos: {'; '.join(missing_info)}.\n\n✅ **Recursos encontrados:**\n"
            
            if unique_hosts:
                response_data["message"] += f"🖥️ Hosts: {', '.join([h['name'] or h['host'] for h in unique_hosts])}\n"
            if found_groups:
                response_data["message"] += f"📁 Grupos: {', '.join([g['name'] for g in found_groups])}\n"
                
            response_data["message"] += "\n¿Quieres continuar con los recursos encontrados o prefieres ajustar la solicitud?"
        
        elif not unique_hosts and not found_groups:
            response_data["type"] = "clarification_needed"
            response_data["message"] = "😔 No encontré ningún servidor o grupo con esos nombres.\n\n💡 **Sugerencias:**\n- Verifica los nombres de los servidores\n- Usa nombres exactos como aparecen en Zabbix\n- Puedes usar grupos en lugar de servidores individuales\n\n¿Podrías verificar los nombres y intentar de nuevo?"
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"💥 Error en /chat: {str(e)}")
        return jsonify({
            "type": "error",
            "message": f"😔 Ocurrió un error inesperado: {str(e)}. ¿Podrías intentar de nuevo?"
        }), 500

@app.route("/parse", methods=["POST"])
def parse_request():
    """Endpoint legacy para compatibilidad - redirige a /chat"""
    return chat_endpoint()

@app.route("/create_maintenance", methods=["POST"])
def create_maintenance():
    """Endpoint para crear periodos de mantenimiento"""
    try:
        data = request.json
        required_fields = ["start_time", "end_time", "recurrence_type"]
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "type": "error",
                    "message": f"⚠️ Falta información requerida: {field}"
                }), 400
        
        # Debe tener al menos hosts o grupos
        if not data.get("hosts") and not data.get("groups"):
            return jsonify({
                "type": "error",
                "message": "⚠️ Se requieren hosts específicos o grupos para el mantenimiento"
            }), 400
        
        # Convertir fechas a timestamp
        try:
            start_dt = datetime.datetime.strptime(data["start_time"], "%Y-%m-%d %H:%M")
            end_dt = datetime.datetime.strptime(data["end_time"], "%Y-%m-%d %H:%M")
            start_time = int(start_dt.timestamp())
            end_time = int(end_dt.timestamp())
        except ValueError as e:
            return jsonify({
                "type": "error",
                "message": f"⚠️ Formato de fecha inválido: {str(e)}"
            }), 400
        
        # Validaciones adicionales
        if end_time <= start_time:
            return jsonify({
                "type": "error",
                "message": "⚠️ La fecha de fin debe ser posterior a la de inicio"
            }), 400
        
        # Preparar datos para el mantenimiento
        host_ids = []
        group_ids = []
        host_names = []
        group_names = []
        
        # Procesar hosts específicos
        if data.get("hosts"):
            hosts_info = zabbix_api.get_hosts(data["hosts"])
            if hosts_info:
                host_ids = [h["hostid"] for h in hosts_info]
                host_names = [h["name"] for h in hosts_info]
        
        # Procesar grupos
        if data.get("groups"):
            groups_info = zabbix_api.get_hostgroups(data["groups"])
            if groups_info:
                group_ids = [g["groupid"] for g in groups_info]
                group_names = [g["name"] for g in groups_info]
        
        # Verificar que se encontraron recursos válidos
        if not host_ids and not group_ids:
            return jsonify({
                "type": "error",
                "message": "⚠️ No se encontraron hosts ni grupos válidos"
            }), 404
        
        # Generar nombre del mantenimiento usando la nueva función
        maintenance_name = generate_maintenance_name(data, host_names, group_names)
        
        # Preparar descripción (mantener el formato actual, agregando ticket si existe)
        description = data.get("description", "Mantenimiento creado via IA Widget")
        ticket_number = data.get("ticket_number", "").strip()
        if ticket_number and f"Ticket: {ticket_number}" not in description:
            description = f"{description} - Ticket: {ticket_number}"
        
        # Preparar configuración de recurrencia
        recurrence_type = data.get("recurrence_type", "once")
        recurrence_config = data.get("recurrence_config")
        
        # Crear el mantenimiento en Zabbix
        result = zabbix_api.create_maintenance(
            name=maintenance_name,
            host_ids=host_ids if host_ids else None,
            group_ids=group_ids if group_ids else None,
            start_time=start_time,
            end_time=end_time,
            description=description,
            tags=data.get("trigger_tags"),
            recurrence_type=recurrence_type,
            recurrence_config=recurrence_config
        )
        
        if "error" in result:
            error_msg = result["error"].get("data", str(result["error"]))
            return jsonify({
                "type": "error",
                "message": f"❌ Error de Zabbix: {error_msg}"
            }), 400
        
        maintenance_id = None
        if "result" in result and "maintenanceids" in result["result"]:
            maintenance_id = result["result"]["maintenanceids"][0]
        
        success_message = f"🎉 ¡Mantenimiento creado exitosamente!\n\n"
        success_message += f"📋 **Detalles:**\n"
        success_message += f"• Nombre: {maintenance_name}\n"
        success_message += f"• Inicio: {data['start_time']}\n"
        success_message += f"• Fin: {data['end_time']}\n"
        success_message += f"• Hosts afectados: {len(host_ids)}\n"
        success_message += f"• Grupos afectados: {len(group_ids)}\n"
        
        if recurrence_type != "once":
            success_message += f"• Tipo: Rutinario ({recurrence_type})\n"
        
        if ticket_number:
            success_message += f"• Ticket: {ticket_number}\n"
        
        success_message += f"\n✅ El mantenimiento está activo y funcionando."
        
        return jsonify({
            "type": "maintenance_created",
            "success": True,
            "maintenance_id": maintenance_id,
            "hosts_affected": len(host_ids),
            "groups_affected": len(group_ids),
            "start_time": data["start_time"],
            "end_time": data["end_time"],
            "name": maintenance_name,
            "description": description,
            "recurrence_type": recurrence_type,
            "is_routine": recurrence_type != "once",
            "ticket_number": ticket_number,
            "message": success_message
        })
        
    except Exception as e:
        logger.error(f"💥 Error en /create_maintenance: {str(e)}")
        return jsonify({
            "type": "error",
            "message": f"😔 Error interno: {str(e)}"
        }), 500

@app.route("/search_hosts", methods=["POST"])
def search_hosts():
    """Endpoint para buscar hosts por término"""
    try:
        data = request.json
        if not data or "search" not in data:
            return jsonify({
                "type": "error",
                "message": "⚠️ Se requiere el campo 'search'"
            }), 400
        
        search_term = data["search"].strip()
        if not search_term:
            return jsonify({
                "type": "error",
                "message": "⚠️ El término de búsqueda no puede estar vacío"
            }), 400
        
        logger.info(f"🔍 Buscando hosts con término: {search_term}")
        
        hosts = zabbix_api.search_hosts(search_term)
        
        return jsonify({
            "type": "search_results",
            "search_term": search_term,
            "hosts_found": len(hosts),
            "hosts": hosts,
            "message": f"🔍 Encontré {len(hosts)} host(s) que coinciden con '{search_term}'"
        })
        
    except Exception as e:
        logger.error(f"💥 Error en /search_hosts: {str(e)}")
        return jsonify({
            "type": "error",
            "message": f"😔 Error interno: {str(e)}"
        }), 500

@app.route("/search_groups", methods=["POST"])
def search_groups():
    """Endpoint para buscar grupos por término"""
    try:
        data = request.json
        if not data or "search" not in data:
            return jsonify({
                "type": "error",
                "message": "⚠️ Se requiere el campo 'search'"
            }), 400
        
        search_term = data["search"].strip()
        if not search_term:
            return jsonify({
                "type": "error",
                "message": "⚠️ El término de búsqueda no puede estar vacío"
            }), 400
        
        logger.info(f"🔍 Buscando grupos con término: {search_term}")
        
        groups = zabbix_api.search_hostgroups(search_term)
        
        return jsonify({
            "type": "search_results",
            "search_term": search_term,
            "groups_found": len(groups),
            "groups": groups,
            "message": f"🔍 Encontré {len(groups)} grupo(s) que coinciden con '{search_term}'"
        })
        
    except Exception as e:
        logger.error(f"💥 Error en /search_groups: {str(e)}")
        return jsonify({
            "type": "error",
            "message": f"😔 Error interno: {str(e)}"
        }), 500

@app.route("/maintenance/list", methods=["GET"])
def list_maintenances():
    """Endpoint para listar mantenimientos existentes"""
    try:
        params = {
            "output": ["maintenanceid", "name", "active_since", "active_till", "description", "maintenance_type"],
            "selectHosts": ["hostid", "host", "name"],
            "selectGroups": ["groupid", "name"],
            "selectTags": ["tag", "value"],
            "selectTimeperiods": ["timeperiod_type", "start_time", "period", "every", "dayofweek", "dayofmonth"],
            "sortfield": "active_since",
            "sortorder": "DESC",
            "limit": 50
        }
        result = zabbix_api._make_request("maintenance.get", params)
        
        if "error" in result:
            return jsonify({
                "type": "error",
                "message": f"❌ Error obteniendo mantenimientos: {result['error']}"
            }), 400
        
        maintenances = result.get("result", [])
        for maint in maintenances:
            maint["active_since"] = datetime.datetime.fromtimestamp(int(maint["active_since"])).strftime("%Y-%m-%d %H:%M")
            maint["active_till"] = datetime.datetime.fromtimestamp(int(maint["active_till"])).strftime("%Y-%m-%d %H:%M")
            
            # Determinar si es rutinario basado en los timeperiods
            is_routine = False
            routine_type = "once"
            if maint.get("timeperiods"):
                timeperiod = maint["timeperiods"][0]
                tp_type = int(timeperiod.get("timeperiod_type", 0))
                if tp_type == 2:
                    routine_type = "daily"
                    is_routine = True
                elif tp_type == 3:
                    routine_type = "weekly"
                    is_routine = True
                elif tp_type == 4:
                    routine_type = "monthly"
                    is_routine = True
            
            maint["is_routine"] = is_routine
            maint["routine_type"] = routine_type
            
            # Extraer número de ticket del nombre o descripción
            ticket_match = re.search(r'\b\d{3}-\d{3,6}\b', maint.get("name", "") + " " + maint.get("description", ""))
            maint["ticket_number"] = ticket_match.group(0) if ticket_match else ""
        
        return jsonify({
            "type": "maintenance_list",
            "maintenances": maintenances,
            "total": len(maintenances),
            "message": f"📋 Mostrando {len(maintenances)} mantenimiento(s) más recientes"
        })
        
    except Exception as e:
        logger.error(f"💥 Error en /maintenance/list: {str(e)}")
        return jsonify({
            "type": "error",
            "message": f"😔 Error interno: {str(e)}"
        }), 500

@app.route("/maintenance/templates", methods=["GET"])
def get_maintenance_templates():
    """Endpoint para obtener plantillas de mantenimientos rutinarios"""
    templates = {
        "daily": {
            "name": "Mantenimiento Diario",
            "description": "Mantenimiento que se ejecuta todos los días",
            "examples": [
                "Backup diario a las 2 AM por 2 horas con ticket 100-178306",
                "Limpieza de logs cada día a las 23:00 ticket 200-8341",
                "Reinicio de servicios diario de 3-4 AM con ticket 500-43116"
            ]
        },
        "weekly": {
            "name": "Mantenimiento Semanal", 
            "description": "Mantenimiento que se ejecuta semanalmente",
            "examples": [
                "Mantenimiento semanal domingos de 1-3 AM ticket 100-178306",
                "Actualización de BD cada viernes a las 22:00 con ticket 200-8341",
                "Respaldo completo todos los sábados ticket 500-43116"
            ]
        },
        "monthly": {
            "name": "Mantenimiento Mensual",
            "description": "Mantenimiento que se ejecuta mensualmente", 
            "examples": [
                "Mantenimiento el primer día de cada mes con ticket 100-178306",
                "Optimización de BD el día 15 de cada mes ticket 200-8341",
                "Limpieza profunda último domingo del mes con ticket 500-43116"
            ]
        }
    }
    
    return jsonify({
        "type": "templates",
        "templates": templates,
        "message": "📄 Aquí tienes las plantillas disponibles para mantenimientos rutinarios"
    })

@app.route("/examples", methods=["GET"])
def get_examples():
    """Endpoint para obtener ejemplos de uso"""
    examples = {
        "basic": [
            {
                "title": "Mantenimiento Simple",
                "description": "Un servidor específico por tiempo limitado",
                "example": "Mantenimiento para srv-web01 mañana de 8 a 10 con ticket 100-178306"
            },
            {
                "title": "Mantenimiento Múltiple",
                "description": "Varios servidores al mismo tiempo",
                "example": "Poner srv-web01, srv-web02 y srv-web03 en mantenimiento hoy de 14 a 16"
            }
        ],
        "groups": [
            {
                "title": "Mantenimiento de Grupo",
                "description": "Todo un grupo de servidores",
                "example": "Mantenimiento del grupo database el domingo de 2 a 4 AM ticket 200-8341"
            },
            {
                "title": "Múltiples Grupos",
                "description": "Varios grupos a la vez",
                "example": "Mantenimiento para grupos web-servers y app-servers mañana de 1 a 3 AM"
            }
        ],
        "routine": [
            {
                "title": "Backup Diario",
                "description": "Mantenimiento que se repite todos los días",
                "example": "Backup diario para srv-backup de 2 a 4 AM durante enero con ticket 500-43116"
            },
            {
                "title": "Mantenimiento Semanal",
                "description": "Mantenimiento que se ejecuta cada semana",
                "example": "Mantenimiento semanal domingos para grupo database de 1 a 3 AM"
            },
            {
                "title": "Mantenimiento Mensual",
                "description": "Mantenimiento que se ejecuta cada mes",
                "example": "Limpieza mensual primer día del mes para todos los web-servers"
            }
        ]
    }
    
    return jsonify({
        "type": "examples",
        "examples": examples,
        "message": "💡 Aquí tienes algunos ejemplos de cómo solicitar mantenimientos"
    })

# ----- Inicio de la aplicación -----
if __name__ == "__main__":
    print("\n🚀 Asistente Interactivo de Mantenimiento IA para Zabbix 7.2")
    print("================================================================")
    print(f"🔗 Zabbix API: {ZABBIX_API_URL}")
    print(f"🔑 Token: {'✅' if ZABBIX_TOKEN else '❌ No configurado'}")
    print(f"🧠 Proveedor IA: {loaded_provider or '❌ No disponible'}")
    
    if loaded_provider == "openai":
        print(f"   - Modelo: {OPENAI_MODEL}")
    elif loaded_provider == "gemini":
        print(f"   - Modelo: {GEMINI_MODEL}")
    
    # Test de conexión al inicio
    test_result = zabbix_api.test_connection()
    if "result" in test_result:
        print(f"✅ Conexión Zabbix OK - Usuarios encontrados: {len(test_result['result'])}")
    else:
        print(f"❌ Error conexión Zabbix: {test_result.get('error', 'Unknown')}")
    
    print("\n💬 Endpoints de Chat Interactivo:")
    print(f"   - POST /chat (Endpoint principal - conversacional)")
    print(f"   - POST /create_maintenance (Crear mantenimiento)")
    print(f"   - GET /examples (Obtener ejemplos de uso)")
    
    print("\n📡 Endpoints de API:")
    print(f"   - POST /search_hosts (Buscar hosts)")
    print(f"   - POST /search_groups (Buscar grupos)")
    print(f"   - GET /maintenance/list (Listar mantenimientos)")
    print(f"   - GET /maintenance/templates (Plantillas rutinarias)")
    print(f"   - GET /health (Verificar estado)")
    
    print("\n🎯 Tipos de Interacción:")
    print(f"   - 💬 Solicitudes de mantenimiento")
    print(f"   - ❓ Pedidos de ayuda y ejemplos")
    print(f"   - 🔍 Preguntas sobre el sistema")
    print(f"   - ⚠️  Redirección para consultas no relacionadas")
    
    print("\n📄 Tipos de mantenimiento soportados:")
    print(f"   - 🔹 Únicos (once)")
    print(f"   - 🔹 Diarios (daily)")
    print(f"   - 🔹 Semanales (weekly)")
    print(f"   - 🔹 Mensuales (monthly)")
    
    print("\n🎫 Soporte de tickets:")
    print(f"   - Formato: XXX-XXXXXX (ej: 100-178306)")
    print(f"   - Detección automática en texto")
    print(f"   - Nombres personalizados por ticket")
    
    print("\n🤖 Funciones IA Interactivas:")
    print(f"   - Conversación natural y amigable")
    print(f"   - Ejemplos automáticos cuando se soliciten")
    print(f"   - Redirección educada para consultas no relacionadas")
    print(f"   - Clarificación inteligente de solicitudes incompletas")
    print(f"   - Respuestas contextuales con emojis\n")
    
    app.run(host="0.0.0.0", port=5005, debug=False)