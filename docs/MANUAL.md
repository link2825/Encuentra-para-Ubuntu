# Manual de Encuentra

## Instalación

Descarga el instalador desde el README y ejecuta:

```bash
sudo apt install ./encuentra_0.5.13-1_all.deb
```

Abre Encuentra desde el menú de aplicaciones.

## Agregar ubicaciones

En Configuración agrega una carpeta local. Para SMB abre primero el recurso en Nautilus y agrega su dirección completa `smb://servidor/recurso/`. Para Google Drive y OneDrive utiliza un montaje rclone activo y agrega su ruta local.

Pulsa Guardar y actualizar índice. Espera a que termine el primer recorrido antes de evaluar los resultados.

## Buscar y abrir

Escribe parte del nombre. Para interpretar tipos o fechas utiliza `ai PDF de ayer`, `ai Excel del mes pasado` o `ai contrato Word` y pulsa Enter. El modo ai puede usar reglas locales; Ollama es opcional.

Las carpetas aparecen primero. Pasa el puntero sobre un resultado para ver la ruta completa. Abre el resultado con su aplicación predeterminada o utiliza Abrir carpeta para ir a su ubicación.

## Solución de problemas

- Sin resultados: comprueba que agregaste la ubicación y que terminó la indexación.
- NAS inaccesible: abre el recurso en Nautilus y comprueba la conexión y los permisos.
- Nube inaccesible: comprueba que rclone está montado y que la ruta corresponde al montaje activo.
- Documento sin abrir: comprueba la aplicación predeterminada del tipo de archivo y prueba abrirlo desde Nautilus.
- Demasiados resultados: concreta el nombre; se muestran hasta 100 coincidencias.

Encuentra busca nombres y metadatos, no el contenido de documentos.

## Desinstalación

```bash
sudo apt remove busca-ai
```

Los datos permanecen en `~/.local/share/busca-ai` o en XDG_DATA_HOME. Retira también cualquier atajo que hayas configurado en GNOME.
