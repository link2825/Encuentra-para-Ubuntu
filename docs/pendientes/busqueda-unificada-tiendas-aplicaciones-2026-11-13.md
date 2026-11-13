# Pendiente: búsqueda unificada en tiendas de aplicaciones

**Fecha:** 2026-11-13
**Proyecto:** Encuentra para Ubuntu
**Versión de referencia:** 0.8.10-2
**Estado:** Pendiente de corrección / mejora

## Extracto de la conversación y evidencia

- Al buscar `ignition` en Encuentra, se mostraron **0 aplicaciones**, **12 archivos** y **5 resultados de la tienda Snap**; no apareció el gestor de inicio automático Ignition de Flathub.
- Al buscar `ignition` desde ArcMenu, apareció una entrada en **Software**; al abrirla se mostró la ficha de **Ignition (Heliguy)**, con botón **Instalar** y origen **Flathub**.
- La búsqueda `grep -ril 'Ignition'` en rutas de lanzadores no devolvió resultados y `Gio.AppInfo.get_all()` mostró 176 aplicaciones, ninguna llamada Ignition. Esto concuerda con que era una aplicación **disponible en tienda, no instalada**.
- El usuario también señala que Encuentra **no busca en Bazaar**.
- Requisito expreso del usuario: la solución **no debe limitarse a GNOME Software ni Flathub**; debe contemplar tiendas y proveedores que se incorporen en el futuro.

## Comportamiento esperado

La búsqueda de aplicaciones debe distinguir claramente:
1. Aplicaciones instaladas, obtenidas de los registros del escritorio.
2. Aplicaciones disponibles para instalar, obtenidas de múltiples catálogos compatibles (p. ej., Snap, Flathub/Flatpak y catálogos utilizados por GNOME Software o Bazaar).

Diseñar una **arquitectura extensible de proveedores**, no una lista fija de tiendas: adaptadores con capacidades declaradas, normalización de resultados (nombre, ID, origen, descripción, icono, enlace de instalación), deduplicación entre tiendas, errores/tiempos de espera independientes y opción para habilitar/deshabilitar fuentes. Evitar confundir la interfaz de tienda con el catálogo subyacente y no prometer que cualquier tienda futura será compatible automáticamente: requerirá adaptador o API compatible.

## Criterios de aceptación propuestos

- `ignition` devuelve Ignition de Flathub aunque no esté instalada, con su origen identificado.
- Se conservan resultados de Snap y aplicaciones instaladas.
- Las aplicaciones de Bazaar se encuentran cuando su catálogo esté disponible mediante el proveedor correspondiente.
- Resultados duplicados entre fuentes se agrupan o identifican claramente.
- La falla de una tienda no bloquea las demás.
- Una nueva tienda puede incorporarse mediante un adaptador sin reescribir el buscador.
- Pruebas de búsqueda, ranking, latencia y funcionamiento sin conexión.

**Alcance:** registrar el pendiente; no se ha implementado ni validado todavía.
