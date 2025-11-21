# Traducciones básicas para el backend
TRANSLATIONS = {
    'en': {
        'maintenance_created': 'Maintenance created successfully',
        'error_creating': 'Error creating maintenance',
        'invalid_request': 'Invalid request',
        'backend_connected': 'Backend connected',
        'backend_error': 'Backend connection error'
    },
    'es': {
        'maintenance_created': 'Mantenimiento creado exitosamente',
        'error_creating': 'Error al crear mantenimiento',
        'invalid_request': 'Solicitud inválida',
        'backend_connected': 'Backend conectado',
        'backend_error': 'Error de conexión del backend'
    }
}

def get_translation(key: str, lang: str = 'en') -> str:
    """Obtener traducción para una clave y idioma específico"""
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))