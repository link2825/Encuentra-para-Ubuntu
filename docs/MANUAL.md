# Manual de Encuentra 0.6.3 (versión de pruebas)

Encuentra es un buscador flotante para Ubuntu. Busca aplicaciones instaladas, sugerencias de la tienda Snap y archivos indexados en ubicaciones locales, NAS SMB y montajes rclone. El índice registra nombres, rutas, extensiones y fechas de modificación; no lee el contenido de los documentos.

## Instalación
Descarga el archivo DEB de la versión correspondiente en GitHub Releases e instala con `sudo apt install ./encuentra_0.6.3-1_all.deb`. Abre **Encuentra** desde el menú de aplicaciones. El comando técnico del ejecutable es `busca-ai`, pero **el prefijo de búsqueda inteligente dentro de Encuentra es `ia`**.

## Configuración
Pulsa el engranaje a la derecha de la barra. Agrega las ubicaciones locales, NAS SMB o montajes rclone. Guarda y actualiza el índice. La primera indexación puede tardar. Configura también el atajo de teclado, las exclusiones y el prefijo de consultas.

## Búsqueda
Sin prefijo, Encuentra busca nombres de archivos y aplicaciones. Con `ia` interpreta filtros en español, automáticamente después de escribir. Los resultados de archivos se muestran en páginas de 100; desplázate y pulsa **Cargar 100 resultados más** cuando aparezca.

## Diccionario aprobado y estado de implementación
**Implementado en 0.6.3 (sujeto a pruebas):**
- Tipos: PDF, Excel, Word, PowerPoint, imágenes, video, audio, ZIP, ISO, TXT, CSV, JSON, SQL y respaldo.
- Fechas: hoy, ayer, anteayer, este mes, mes pasado, hace N meses, últimos N días, año YYYY.
- Orden: más reciente, más nuevo, último, actualizado, más antiguo, primero.
- Coincidencia por términos del nombre; orden por nombre por defecto.
- Paginación de resultados: 100 por página.

**Aprobado para siguientes etapas, aún no implementado completamente:**
- Ubicaciones: Descargas, Documentos, Escritorio, NAS, Google Drive, dentro de carpeta.
- Operadores: y, o, excepto, sin, cualquiera, todos, nombre exacto, empieza con, termina en.
- Cantidades: primeros N, solo carpetas, únicamente.
- Tamaños: más grande, más pequeño, mayor/menor de N MB/GB.
- Aproximación: similar, parecido, alias, errores tipográficos.
- Estado: disponible, en línea, sin acceso, duplicado, faltante.
- Acciones: abrir, abrir carpeta, copiar ruta, mostrar ubicación, ejecutar.

Las funciones pendientes requieren cambios de esquema, filtrado o interfaz. **No se interpretan como instrucciones efectivas todavía.**

## Ejemplos
- `ia curp vicky mas reciente`: nombres con ambos términos, ordenados por fecha descendente.
- `ia word de hace 4 meses`: Word modificados en el mes calendario de cuatro meses atrás.
- `ia pdf ultimos 30 dias`: PDF modificados durante los últimos 30 días.
- `ia imagenes`: imágenes por extensión; no analiza su contenido.
- `factura`: búsqueda simple por nombre.

## Solución de problemas
Si no aparecen resultados, comprueba la carpeta indexada, el estado del montaje y la última indexación. Si un documento del NAS no abre, prueba la misma ruta en Nautilus y revisa si la aplicación predeterminada admite rutas GVfs. Algunas aplicaciones Snap no pueden abrir rutas GVfs fuera de sus ubicaciones compartidas.

Para diagnosticar el programa en terminal: `busca-ai`. Para desinstalar el paquete: `sudo apt remove busca-ai`. Los índices y la configuración se conservan en `~/.local/share/busca-ai`.

## Límites conocidos
La paginación no equivale a una búsqueda del contenido de los documentos. Los filtros de tamaño, coincidencia aproximada, exclusión y ubicación están aprobados pero pendientes de desarrollo. El orden cronológico usa fecha de modificación.
