# Control de asistencia dominical

Aplicación Streamlit para registrar la asistencia de Arauca Central. La lista
se obtiene de las columnas B–E del Google Sheet y los registros se guardan en
PostgreSQL.

## Configuración local

1. Crea y activa un entorno virtual, e instala las dependencias:

   ```bash
   python -m venv .venv
   .venv/Scripts/activate
   python -m pip install -r requirements.txt
   ```

2. Si todavía no existe `.streamlit/secrets.toml`, copia
   `.streamlit/secrets.example.toml` con ese nombre. Si ya existe, conserva su
   configuración de PostgreSQL y agrega la sección `[auth]`.
3. En el archivo local, configura la URL de PostgreSQL y define una contraseña
   aleatoria de al menos 16 caracteres. Puedes generar una con:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```

   No compartas ni subas `.streamlit/secrets.toml`.
4. Inicia la aplicación:

   ```bash
   python -m streamlit run app.py
   ```

## Configuración en Streamlit Community Cloud

En **App settings → Secrets**, configura los mismos valores del ejemplo, con
`[auth]` y `[neon_db]`. Usa una contraseña fuerte y mantén la URL de la base de
datos como secreto; no la agregues al código ni al repositorio.

## Funciones

- Búsqueda por nombre, apellido o cédula y filtros por estado de asistencia.
- Indicadores de presentes, pendientes y porcentaje de asistencia.
- Confirmación antes de guardar. Se crea una instantánea completa inicial y
  luego solo se escriben las altas o cambios; filtrar la tabla no altera los
  registros que quedaron ocultos.
- Bloqueo del guardado si el Google Sheet contiene documentos duplicados.
- Historial por periodo, consulta y corrección de fechas anteriores, y
  exportación CSV.
- Acceso con una contraseña compartida almacenada en secretos. Para una
  aplicación accesible públicamente, combina esta protección con los controles
  de acceso de la plataforma de alojamiento.

## Pruebas

Ejecuta las pruebas de búsqueda, filtros, edición del borrador y detección de
documentos duplicados con:

```bash
python -m unittest discover -s tests
```
