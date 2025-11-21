# AI Maintenance Widget

Widget de Zabbix para interactuar con el backend de AI Maintenance.

## Instalación

### 1. Descargar Widget

Descargar la última versión desde [releases](./releases/) o compilar desde el código fuente.

### 2. Instalar en Zabbix

```bash
# Extraer el widget en el directorio de módulos de Zabbix
cp -r src/aimaintenance /usr/share/zabbix/ui/modules/aimaintenance
```

### 3. Escanear Módulos

1. Ir a **Administration → General → Modules**
2. Hacer clic en **Scan directory**
3. El widget "AI Maintenance Assistant" aparecerá en la lista

### 4. Agregar al Dashboard

1. Ir a **Dashboard → Edit**
2. Hacer clic en **Add widget**
3. Seleccionar **AI Maintenance Assistant**
4. Configurar la **URL del backend** (ej: `http://localhost:5005`)

## Configuración

### Parámetros del Widget

- **Backend URL**: URL donde está corriendo la API del backend
- **Refresh Interval**: Intervalo de actualización (opcional)

### Ejemplo de Configuración

```
Backend URL: http://localhost:5005
Refresh Interval: 30s
```

## Compilación

Para compilar una nueva versión del widget:

```bash
cd widget
make clean
make build
```

El archivo ZIP se generará en `releases/`.

## Estructura del Widget

```
src/aimaintenance/
├── manifest.json          # Configuración del widget
├── Widget.php            # Lógica principal
├── actions/              # Acciones del widget
├── assets/               # CSS y JavaScript
├── includes/             # Archivos de inclusión
└── views/                # Vistas del widget
```

## Troubleshooting

### Widget no aparece
1. Verificar que se extrajo en `/usr/share/zabbix/ui/modules/`
2. Hacer **Scan directory** en Administration → General → Modules
3. Verificar permisos de archivos

### Widget no conecta al backend
1. Verificar URL del backend en configuración
2. Comprobar que el backend esté corriendo
3. Revisar conectividad de red
4. Verificar logs del navegador (F12)

### Error de CORS
El backend debe permitir conexiones desde el frontend de Zabbix. Verificar configuración de CORS en el backend.