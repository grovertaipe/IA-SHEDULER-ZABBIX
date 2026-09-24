# AI Maintenance Assistant — Widget de Zabbix

Módulo de widget para el dashboard de Zabbix que expone el asistente de
mantenimiento con IA. Este es el **artefacto de frontend** del proyecto y se
despliega de forma **independiente del backend**.

- **id del módulo:** `aimaintenance`
- **namespace:** `AIMaintenance`
- **Compatibilidad:** Zabbix 7.2+ (probado también en 7.4)
- **Backend:** se despliega por separado. Consulta [`backend/README.md`](../../backend/README.md)
  para el despliegue del servicio HTTP/Flask.

> El widget solo consume la API del backend a través de una URL configurable
> (`Backend API URL`). No incluye lógica de negocio: el cálculo determinista de
> los periodos de mantenimiento vive en el backend.

## Requisitos previos

- Zabbix Frontend **7.2 o superior**.
- Acceso al sistema de archivos del frontend de Zabbix
  (`/usr/share/zabbix/ui/` en instalaciones estándar).
- Permisos de administrador en Zabbix (rol Super admin) para habilitar módulos.
- Un backend del "AI Maintenance Assistant" desplegado y accesible por HTTP
  desde el navegador de los usuarios del dashboard (ver `backend/README.md`).
- Para empaquetar: `make` y `zip` disponibles (opcional; también se puede copiar
  la carpeta directamente).

## Estructura del módulo

```
aimaintenance/
├── manifest.json          # id + namespace + acciones + assets (manifest v2)
├── Widget.php             # clase del widget (CWidget)
├── actions/               # controlador de vista (CControllerDashboardWidgetView)
├── includes/              # WidgetForm (campos de configuración, p. ej. api_url)
├── views/                 # widget.view.php / widget.edit.php
└── assets/
    ├── js/                # class.widget.js y módulos JS
    └── css/               # estilos del widget
```

## Empaquetado

Desde el directorio `widget/` (donde está el `Makefile`):

```bash
make zip
```

Esto genera un archivo `zabbix-widget-aimaintenance-<VERSION>.zip` en `widget/`,
comprimiendo el contenido de `aimaintenance/`. La versión se toma de
`git describe`; también puedes forzarla:

```bash
make zip VERSION=1.1.0
```

Si no dispones de `make`, puedes empaquetar manualmente:

```bash
cd aimaintenance && zip -r ../zabbix-widget-aimaintenance.zip .
```

## Instalación en Zabbix 7.2+

1. **Copia el módulo** dentro del directorio de módulos del frontend de Zabbix.
   La carpeta del módulo debe conservar el nombre `aimaintenance`:

   ```bash
   # Desde una copia local o descomprimiendo el zip generado
   sudo cp -r aimaintenance /usr/share/zabbix/ui/modules/aimaintenance
   ```

   El resultado debe ser: `/usr/share/zabbix/ui/modules/aimaintenance/manifest.json`.

2. **Ajusta permisos** para que el servidor web pueda leer los archivos
   (usuario típico `www-data`, ajusta según tu distribución):

   ```bash
   sudo chown -R www-data:www-data /usr/share/zabbix/ui/modules/aimaintenance
   ```

3. **Habilita el módulo** en la interfaz de Zabbix:
   - Ve a **Administration → General → Modules**.
   - Pulsa **Scan directory** para que Zabbix detecte el nuevo módulo.
   - Localiza **AI Maintenance Assistant** en la lista y cambia su estado a
     **Enabled**.

## Añadir el widget a un dashboard

1. Abre un dashboard y entra en modo edición.
2. Pulsa **Add widget** (o edita un widget existente).
3. En **Type**, selecciona **AI Maintenance Assistant**.
4. Configura los campos del widget y guarda.
5. Guarda el dashboard.

## Configuración del backend (URL)

El widget se conecta al backend mediante el campo **Backend API URL** del
formulario de configuración del widget:

- **Campo:** `Backend API URL` (`api_url`).
- **Valor por defecto:** `http://localhost:5005`.
- Debe apuntar a la URL base del backend accesible **desde el navegador** de los
  usuarios del dashboard (por ejemplo `http://mi-servidor:5005` o una URL detrás
  de un proxy inverso HTTPS).

El widget usa esta URL para verificar el estado (`/health`), cargar plantillas
(`/maintenance/templates`) y procesar las solicitudes de mantenimiento. Si la URL
no es alcanzable, el widget muestra un aviso de conexión y sus funciones quedan
limitadas hasta restablecerla.

> El backend se despliega y opera de forma independiente (Docker/compose,
> variables de entorno, proveedores de IA, etc.). Consulta
> [`backend/README.md`](../../backend/README.md).
