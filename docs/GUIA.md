# Guía de Encuentra 0.8.10-2

## Funciones

1. **Búsqueda:** localiza archivos, carpetas y aplicaciones mediante el campo principal. La interfaz muestra resultados por categorías.
2. **Fuentes:** desde Configuración se añaden carpetas locales y rutas SMB/GVfs; las fuentes configuradas quedan guardadas en `~/.local/share/busca-ai/config.json`.
3. **Indexación:** utiliza SQLite (`~/.local/share/busca-ai/files.db`). El botón Actualizar índice solicita la revisión de las fuentes. En esta versión, el indicador de progreso puede no reflejar inmediatamente la actividad.
4. **Atajo:** haz clic en el campo de captura, pulsa la combinación y guarda. Los atajos reservados por GNOME pueden ejecutarse antes de que la aplicación reciba el evento.
5. **Icono:** se conserva el diseño de carpetas y lupa, con fondo exterior transparente.

## Mantenimiento

No elimines `~/.local/share/busca-ai/` durante una actualización. Comprueba las unidades montadas antes de iniciar la indexación. Para ver los archivos registrados de una unidad, consulta la tabla `files` en SQLite usando su campo `path`.

## Verificación de la versión

Paquete: `encuentra_0.8.10-2_all.deb`. Se comprobó la coincidencia de 3,222 elementos entre una unidad montada y el índice. Se verificó visualmente la búsqueda de aplicaciones, archivos y documentos en GNOME.
