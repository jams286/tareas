# tareas (casa)

Tablero de tareas del hogar, compartido entre los celulares y la tablet (vía el hub `infra/home`).

## Qué hace

- Personas de la casa: se agregan, renombran y quitan desde la app (botón "Personas"); cada una recibe un color. Al quitar a alguien, sus tareas quedan para "Cualquiera".
- Tareas con persona (o "Cualquiera") y repetición: **solo una vez**, **todos los días** o **una vez por semana** (lunes a domingo).
- Secciones "Hoy" (únicas y diarias) y "Esta semana" (semanales), con avance "x de y". Tocar una tarea la marca hecha o pendiente; ✎ abre el diálogo para editarla o borrarla.
- Filtro por persona (se recuerda por dispositivo en `localStorage`, clave `tareas.filtro`); muestra las de esa persona más las de "Cualquiera".

## Cómo está hecho

- `servidor.py`: `ThreadingHTTPServer` + `sqlite3`, solo biblioteca estándar, en `127.0.0.1:8771`. Tablas `personas`, `tareas`, `hechas` (una fila por tarea y periodo: `una`, `AAAA-MM-DD` o `AAAA-Wss`) y `meta` (contador `version`). Así las diarias y semanales "se reinician" solas al cambiar el día o la semana, sin tareas programadas. Las de una vez hechas en días anteriores ya no se devuelven. Fechas en hora local del server (America/El_Salvador). Variables `TAREAS_BD` y `TAREAS_PUERTO` para probar sin tocar los datos reales.
- BD: `~/.local/share/casa/tareas.db` (WAL). No va en git.
- `web/`: página estática (sin frameworks), diálogos con `<dialog>`. Revisa `api/tablero` cada 5 s con la pestaña visible; redibuja si cambia `version` o el día. Los cambios se reflejan al tiro y luego se confirman con el servidor.
- `[hidden] { display: none !important; }` en el CSS: hace falta porque varias clases definen `display`.
- Rutas relativas (`api/...`) para que funcione bajo `/tareas/`. Sin login: es solo red local.

## Dónde corre

- Página: http://192.168.1.4/tareas/ (archivos en `/var/www/tareas/`, copiados de `web/`).
- API: nginx publica `/tareas/api/` → `127.0.0.1:8771/api/` (config en `infra/nginx`).
- Servicio systemd de usuario `tareas.service` (copia en `servicio/`).
- Comandos de publicación, servicio y respaldo en el README.
