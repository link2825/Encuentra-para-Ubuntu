# Migración experimental GTK 4 + libadwaita

Rama separada de `main` para no reemplazar Encuentra 0.6.4.

Objetivos: frontend GTK 4/Adw, `Gtk.FileDialog` para seleccionar carpetas, compatibilidad con el índice SQLite y el motor de búsqueda existentes, búsquedas `ia`, paginación, filtros de archivos/carpetas, fechas, y nombres SMB legibles.

Estado: prototipo de frontend creado y comprobado sintácticamente fuera del repositorio. **Todavía no está integrado ni validado en Ubuntu**. No publicar DEB ni fusionar antes de integrar y probar: atajos GNOME, configuración completa, progreso de indexación, rutas NAS/GVfs y arranque.

Versión funcional actual: 0.6.4 en `main`.