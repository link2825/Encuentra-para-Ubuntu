Encuentra 0.5.13 para Ubuntu GNOME

Instalación desde la carpeta de descarga:
    sudo apt install ./encuentra_0.5.13-1_all.deb

También puedes abrir el .deb con un instalador gráfico que admita
dependencias de APT. Abre Encuentra desde el menú de aplicaciones.

En Configuración agrega carpetas locales y la carpeta de Google Drive
desde un montaje rclone activo.
Pulsa «Activar buscador flotante» para usar Super + Mayús + F. Puedes
asignar otro atajo al comando busca-ai --quick desde Configuración de GNOME.

Escribe a57 para buscar por nombre. Escribe ai los PDF de ayer y pulsa
Enter para interpretar la frase. Usa flecha abajo para pasar a la lista,
Enter para abrir el resultado y Esc para ocultar la barra.

El índice incluye carpetas y archivos. Guarda nombres, rutas, extensiones y fechas de modificación.
Se omiten archivos ocultos, enlaces simbólicos y montajes rclone
anidados que no se hayan agregado explícitamente. Las revisiones
periódicas empiezan al iniciar sesión en GNOME, con la barra oculta.
Se comparan los metadatos con el índice anterior y solo se aplican cambios.
Puedes forzar una revisión con Guardar y actualizar índice. Si rclone
se desconecta, sus resultados aparecen como no disponibles.

El modo ai aplica reglas en español de forma predeterminada. Si tienes
Ollama, configura el nombre exacto de un modelo instalado para usar IA
local. Ollama recibe solo la consulta de texto. Ante un fallo, se aplican
las reglas. La inferencia del modelo tiene su propio tiempo de respuesta.

Para desinstalar, quita el atajo Encuentra en GNOME y ejecuta
sudo apt remove busca-ai. El índice y la configuración permanecen
en ~/.local/share/busca-ai, o bajo XDG_DATA_HOME si lo personalizaste.

Para un NAS SMB, abre la carpeta compartida en Nautilus, copia su
dirección smb:// y pégala en Configuración con Agregar dirección.

Google Drive y OneDrive
----------------------
Las integraciones directas por API se retiraron. Agrega la carpeta local
del montaje rclone, por ejemplo /home/usuario/GoogleDrive. Rclone gestiona
la autorización y la subida de cambios. Encuentra no necesita credenciales
de Google ni Microsoft. Las antiguas fuentes API se quitan automáticamente
de la configuración; las carpetas locales, montajes y NAS se conservan.
Las autorizaciones antiguas de Encuentra no se usan ni se borran.

En Configuración, «Ocultar archivos del sistema y de aplicaciones» está
activado por defecto. Filtra los resultados antes del límite de 100:
plantillas de SoftMaker, binarios compilados, dependencias, papeleras y
rutas estándar del sistema. No borra archivos ni elimina datos del índice.
Desactívalo y guarda para volver a mostrar esos resultados.
