# tareas

Tablero de tareas de la casa: quién hace qué hoy y esta semana. Tareas de una vez, diarias o semanales; se marcan como hechas desde cualquier celular o la tablet y todos lo ven en unos segundos.

- Página: http://192.168.1.4/tareas/
- Datos: `~/.local/share/casa/tareas.db` (SQLite)

## Partes

- `web/`: página estática que se publica en `/var/www/tareas/`.
- `servidor.py`: API JSON (solo Python estándar + SQLite) en `127.0.0.1:8771`. nginx publica `/tareas/api/` → `/api/`.
- `servicio/tareas.service`: servicio systemd de usuario.

## Comandos

Publicar la página:

```
rsync -a --delete ~/proyectos/casa/tareas/web/ /var/www/tareas/
```

Instalar o actualizar el servicio:

```
mkdir -p ~/.config/systemd/user
cp ~/proyectos/casa/tareas/servicio/tareas.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tareas.service
systemctl --user restart tareas.service   # después de cambiar servidor.py
```

Ver el log: `journalctl --user -u tareas -f`

Respaldo de los datos (seguro aunque el servicio esté corriendo):

```
python3 -c "import sqlite3,pathlib; o=sqlite3.connect(pathlib.Path.home()/'.local/share/casa/tareas.db'); d=sqlite3.connect('tareas-respaldo.db'); o.backup(d)"
```

Respaldo automático: todos los días a las 3:30 a. m. en `/media/datos/Backups/casa/` (proyecto `infra/respaldos`).
