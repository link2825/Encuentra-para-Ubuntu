import sqlite3
import datetime as dt
import json
import os
from pathlib import Path
from urllib.parse import quote
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

import engine

TITLE = "Encuentra"
VERSION = "0.5.14-1"
QUICK_BINDING = "<Super><Shift>f"
KEYS = "org.gnome.settings-daemon.plugins.media-keys"
BINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/busca-ai/"


class Launcher(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.busca_ai.Launcher",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.quick = False
        self.worker = ThreadPoolExecutor(max_workers=2)
        self.generation = 0
        self.pending = 0
        self.process = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Window.set_default_icon_name("encuentra")
        self.hold()
        GLib.timeout_add_seconds(60, self.refresh)
        self.refresh()

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        if "--background" in arguments:
            return 0
        self.quick = "--quick" in arguments and "--settings" not in arguments
        self.activate()
        if "--settings" in arguments:
            self.preferences()
        return 0

    def do_activate(self):
        if self.window is None:
            self.build()
        self.window.set_decorated(not self.quick)
        self.window.set_skip_taskbar_hint(self.quick)
        if self.quick:
            self.entry.set_text("")
            self.changed()
        self.window.show_all()
        self.settings_button.set_visible(not self.quick)
        self.folder_button.set_visible(not self.quick)
        self.update_panel()
        self.window.present()
        self.entry.grab_focus()
        self.refresh()

    def build(self):
        self.window = Gtk.ApplicationWindow(application=self, title=TITLE)
        self.window.set_default_size(690, 420)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.connect("key-press-event", self.keyboard)
        self.window.connect("delete-event", lambda window, _: window.hide_on_delete())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self.window.add(box)
        bar = Gtk.Box(spacing=8)
        box.pack_start(bar, False, False, 0)
        self.entry = Gtk.SearchEntry(placeholder_text="Buscar archivos y carpetas…")
        self.entry.connect("changed", self.changed)
        self.entry.connect("activate", self.submit)
        bar.pack_start(self.entry, True, True, 0)
        button = self.settings_button = Gtk.Button(label="Configuración")
        button.connect("clicked", lambda _: self.preferences())
        bar.pack_start(button, False, False, 0)
        self.status = Gtk.Label(label="Agrega carpetas en Configuración.", xalign=0)
        self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 0)
        self.rows = Gtk.ListStore(str, str, str, bool, str)
        self.results = Gtk.TreeView(model=self.rows, headers_visible=False)
        column = Gtk.TreeViewColumn()
        icon = Gtk.CellRendererPixbuf(xpad=12, stock_size=Gtk.IconSize.DND)
        label = Gtk.CellRendererText(ellipsize=3, ypad=7)
        column.pack_start(icon, False)
        column.add_attribute(icon, "icon-name", 0)
        column.pack_start(label, True)
        column.add_attribute(label, "markup", 1)
        self.results.append_column(column)
        self.results.set_tooltip_column(4)
        self.results.connect("row-activated", lambda *_: self.open_selected(False))
        self.list_scroll = Gtk.ScrolledWindow()
        self.list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list_scroll.add(self.results)
        box.pack_start(self.list_scroll, True, True, 0)
        open_folder = self.folder_button = Gtk.Button(label="Abrir carpeta")
        open_folder.connect("clicked", lambda _: self.open_selected(True))
        box.pack_end(open_folder, False, False, 0)
        if engine.settings()["roots"]:
            self.status.set_text("Escribe para buscar. Usa el prefijo inteligente configurado.")

    def update_panel(self):
        has_results = bool(len(self.rows))
        self.list_scroll.set_visible(not self.quick or has_results)
        self.status.set_visible(not self.quick or bool(self.entry.get_text().strip()))
        height = min(420, 75 + 58 * len(self.rows)) if has_results else 1
        self.window.resize(690, height if self.quick else 420)

    def keyboard(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            self.window.hide()
            return True
        if event.keyval == Gdk.KEY_Down and self.entry.has_focus() and len(self.rows):
            self.results.grab_focus()
            self.results.set_cursor(Gtk.TreePath.new_from_indices([0]))
            return True
        return False

    @staticmethod
    def natural(query):
        return query.casefold().startswith(engine.settings().get("search_prefix", "ia").casefold() + " ")

    def changed(self, *_):
        self.generation += 1
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0
        self.rows.clear()
        query = self.entry.get_text().strip()
        if self.natural(query):
            self.status.set_text("Pulsa Enter para buscar.")
        elif query:
            self.status.set_text("Buscando…")
            self.pending = GLib.timeout_add(100, self.dispatch, query, False)
        else:
            self.status.set_text("Escribe un nombre o una consulta con el prefijo configurado.")
        self.update_panel()

    def submit(self, *_):
        query = self.entry.get_text().strip()
        if self.natural(query):
            if len(self.rows):
                self.open_selected(False)
            else:
                self.dispatch(query[len(engine.settings().get("search_prefix", "ia")) + 1:].strip(), True)
        elif len(self.rows):
            self.open_selected(False)

    def dispatch(self, query, natural):
        self.pending = 0
        self.generation += 1
        generation = self.generation
        if natural:
            self.status.set_text("Interpretando consulta…")
        job = self.worker.submit(self.lookup, query, natural)
        job.add_done_callback(lambda future: GLib.idle_add(self.show_results, generation, future))
        return False

    @staticmethod
    def lookup(query, natural):
        config = engine.settings()
        if natural:
            filters, mode = engine.interpret(query, config["model"])
        else:
            filters, mode = ([engine.normalize(query)], [], None, None), "Por nombre"
        with engine.database() as conn:
            rows = engine.search(conn, config, filters)
            return [(*row, Launcher.result_path(conn, row[0])) for row in rows], mode

    def show_results(self, generation, future):
        if generation != self.generation:
            return False
        try:
            rows, mode = future.result()
            self.rows.clear()
            for path, name, date, available, directory, full_path in rows:
                label = name if available else name + " (Ubicación no disponible)"
                modified = dt.datetime.fromtimestamp(date).strftime("%d/%m/%Y")
                parent = (Gio.File.new_for_uri(path).get_parent().get_parse_name().replace("%20", " ")
                          if engine.is_remote(path) else str(Path(path).parent))
                content_type, _ = Gio.content_type_guess(name, None)
                icon_names = Gio.content_type_get_icon(content_type).get_names()
                icon = "folder" if directory else next((name for name in icon_names
                             if Gtk.IconTheme.get_default().has_icon(name)), "text-x-generic")
                title = GLib.markup_escape_text(label)
                detail = GLib.markup_escape_text(f"{'Carpeta' if directory else modified} · {parent}")
                self.rows.append((icon, f"<b>{title}</b>\n<small>{detail}</small>", path, directory, GLib.markup_escape_text(full_path)))
            if rows:
                self.results.get_selection().select_path(Gtk.TreePath.new_from_indices([0]))
            count = "Primeros 100 resultados" if len(rows) == 100 else f"{len(rows)} resultados"
            self.status.set_text(f"{count} · {mode}")
        except Exception as error:
            self.status.set_text(str(error))
        self.update_panel()
        return False

    @staticmethod
    def result_path(conn, selected):
        if engine.is_remote(selected):
            return Gio.File.new_for_uri(selected).get_parse_name()
        return selected

    @staticmethod
    def run_nautilus(uri):
        Gio.Subprocess.new(["nautilus", "--new-window", uri], Gio.SubprocessFlags.NONE)

    def open_selected(self, folder):
        model, row = self.results.get_selection().get_selected()
        if row is None:
            return
        selected, directory = model[row][2], model[row][3]
        if engine.is_remote(selected):
            file = Gio.File.new_for_uri(selected)
            try:
                if folder or directory:
                    target = file.get_parent() if folder else file
                    Gio.AppInfo.launch_default_for_uri(target.get_uri(), None)
                else:
                    file.query_default_handler(None).launch([file], None)
                self.window.hide()
            except GLib.Error as error:
                self.status.set_text(str(error))
            return
        path = Path(selected)
        roots = engine.settings()["roots"]
        if not any(path.is_relative_to(item["path"]) and (
            not item["mount"] or engine.mount_for(path) == item["mount"]
        ) for item in roots):
            self.status.set_text("La ubicación ya no está disponible.")
            return
        if not path.exists() or path.is_dir() != directory:
            self.status.set_text("El archivo se movió o ya no está disponible.")
            return
        try:
            Gio.AppInfo.launch_default_for_uri((path.parent if folder else path).as_uri(), None)
            self.window.hide()
        except GLib.Error as error:
            self.status.set_text(str(error))

    def refresh(self, force=False):
        if self.process is None or self.process.poll() is not None:
            command = [sys.executable, __file__, "--index"]
            if force:
                command.append("--force")
            if self.process:
                progress_file(self.process.pid).unlink(missing_ok=True)
            self.process = subprocess.Popen(command)
        return True

    def preferences(self):
        config = engine.settings()
        dialog = Gtk.Dialog(title="Configuración de Encuentra", transient_for=self.window,
                            modal=True)
        dialog.set_default_size(650, 475)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                           "Guardar y actualizar índice", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        store = Gtk.ListStore(str, str, str)
        for root in config["roots"]:
            store.append((root["path"], root["mount"], "Pendiente"))
        progress = Gtk.ProgressBar(show_text=True)
        box.pack_start(progress, False, False, 0)

        def update_progress():
            process = self.process
            code = process.poll() if process else None
            running = process is not None and code is None
            state = {}
            if process:
                try:
                    state = json.loads(progress_file(process.pid).read_text())
                except (OSError, ValueError):
                    pass
            active = state.get("path") if running else None
            total = state.get("total", 0)
            done = state.get("done", 0)
            progress.set_fraction(done / total if total else 0)
            if running:
                label = f"{done} de {total} carpetas procesadas" if total else "Iniciando indexado…"
                if active:
                    label += f" · Indexando {active}"
                if state.get("folder"):
                    label = (f"{done} de {total} ubicaciones · "
                             f"{state['files']} archivos detectados")
            elif code == 2:
                label = "Ya hay otro indexado en ejecución"
            elif code:
                label = f"El indexador se detuvo (código {code})"
            elif state:
                label = f"Proceso terminado · {done} de {total} carpetas procesadas"
            else:
                label = "Sin indexado activo"
            progress.set_text(label)
            progress.set_tooltip_text(state.get("folder") or label)
            with engine.database() as conn:
                statuses = dict(conn.execute("SELECT root,status FROM scans"))
                counts = dict(conn.execute("SELECT root,COUNT(*) FROM files GROUP BY root"))
            for row in store:
                path = row[0]
                status = statuses.get(path, "Pendiente")
                if path == active:
                    status = (f"Indexando… {state.get('files', 0)} archivos detectados"
                              if state.get("folder") else "Indexando…")
                elif engine.smb_server_only(path):
                    status = "Agrega una carpeta compartida del NAS"
                elif status == "Actualizado":
                    status = f"Actualizado · {counts.get(path, 0)} archivos"
                elif status.startswith("Parcial"):
                    status += f" · {counts.get(path, 0)} archivos en el índice"
                if row[2] != status:
                    row[2] = status
            return True

        view = Gtk.TreeView(model=store)
        for index, title in ((0, "Carpeta indexada"), (2, "Última actualización")):
            view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        buttons = Gtk.Box(spacing=6)
        box.pack_start(buttons, False, False, 0)

        def add(_, drive):
            picker = Gtk.FileChooserDialog(title="Selecciona una carpeta",
                                           transient_for=dialog,
                                           action=Gtk.FileChooserAction.SELECT_FOLDER)
            if drive:
                picker.set_local_only(False)
                for remote in engine.remote_mounts():
                    try:
                        picker.add_shortcut_folder_uri(remote.get_uri())
                    except GLib.Error:
                        pass
            picker.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Agregar", Gtk.ResponseType.OK)
            if picker.run() == Gtk.ResponseType.OK:
                uri = picker.get_uri()
                if drive and uri and engine.is_remote(uri):
                    add_remote_uri(uri)
                    picker.destroy()
                    return
                filename = picker.get_filename()
                if filename is None:
                    message.set_text("Selecciona Google Drive o una carpeta local.")
                    picker.destroy()
                    return
                path = os.path.realpath(filename)
                mount = engine.mount_for(path)
                if path == "/" or (drive and not mount):
                    message.set_text("Abre tu cuenta en Archivos o elige una carpeta de un montaje rclone activo." if drive
                                     else "Elige una carpeta específica.")
                elif any(not engine.is_remote(row[0]) and row[1] == mount and (Path(path).is_relative_to(row[0])
                         or Path(row[0]).is_relative_to(path)) for row in store):
                    message.set_text("La carpeta se superpone con otra ubicación del índice.")
                else:
                    store.append((path, mount, "Pendiente"))
                    message.set_text("")
            picker.destroy()

        def add_remote_uri(uri):
            uri = uri.strip()
            if not engine.is_remote(uri) or not uri.split("://", 1)[1].split("/")[0]:
                message.set_text("Pega la dirección smb:// o google-drive:// de Nautilus.")
                return
            if engine.smb_server_only(uri):
                message.set_text("En Nautilus entra en una carpeta compartida y copia su dirección completa.")
                return
            uri = Gio.File.new_for_uri(uri).get_uri()
            if any(row[0] == uri for row in store):
                message.set_text("Esa carpeta ya está agregada.")
                return
            store.append((uri, "", "Pendiente"))
            message.set_text("Carpeta agregada. Pulsa Guardar y actualizar índice.")

        drive_address = Gtk.Entry(placeholder_text="Dirección smb:// o google-drive:// de Nautilus")
        address_row = Gtk.Box(spacing=6)
        address_row.pack_start(drive_address, True, True, 0)
        add_address = Gtk.Button(label="Agregar dirección")
        add_address.connect("clicked", lambda _: add_remote_uri(drive_address.get_text()))
        address_row.pack_start(add_address, False, False, 0)
        box.pack_start(address_row, False, False, 0)

        def remove(_):
            _, row = view.get_selection().get_selected()
            if row is not None:
                store.remove(row)

        for label, callback, args in [
            ("Agregar local", add, (False,)), ("Agregar Drive o NAS", add, (True,)),
            ("Quitar", remove, ()), ("Activar buscador flotante", lambda _:
             message.set_text(self.shortcut()), ()),
        ]:
            button = Gtk.Button(label=label)
            button.connect("clicked", callback, *args)
            buttons.pack_start(button, False, False, 0)
        prefix_entry = Gtk.Entry(text=config.get("search_prefix", "ia"))
        box.pack_start(Gtk.Label(label="Prefijo de búsqueda inteligente (por defecto ia)", xalign=0), False, False, 0)
        box.pack_start(prefix_entry, False, False, 0)
        shortcut_entry = Gtk.Entry()
        shortcut_entry.set_editable(False)
        shortcut_entry.set_text(self.current_shortcut() or "Sin asignar")
        chosen = [self.current_shortcut()]
        shortcut_row = Gtk.Box(spacing=6)
        shortcut_row.pack_start(shortcut_entry, True, True, 0)
        capture = Gtk.Button(label="Capturar atajo")
        shortcut_row.pack_start(capture, False, False, 0)
        box.pack_start(Gtk.Label(label="Atajo global para abrir Encuentra", xalign=0), False, False, 0)
        box.pack_start(shortcut_row, False, False, 0)
        def on_capture_key(widget, event):
            modifiers = event.state & Gtk.accelerator_get_default_mod_mask()
            key = Gdk.keyval_to_lower(event.keyval)
            if not Gtk.accelerator_valid(key, modifiers):
                return True
            chosen[0] = Gtk.accelerator_name(key, modifiers)
            shortcut_entry.set_text(Gtk.accelerator_get_label(key, modifiers))
            capture.set_label("Capturar atajo")
            widget.disconnect_by_func(on_capture_key)
            return True
        def begin_capture(widget):
            widget.set_label("Pulsa combinación…")
            widget.grab_focus()
            widget.connect("key-press-event", on_capture_key)
        capture.connect("clicked", begin_capture)
        hide_technical = Gtk.CheckButton(label="Ocultar archivos del sistema y de aplicaciones")
        hide_technical.set_active(config.get("hide_technical", True))
        hide_technical.set_tooltip_text("Oculta plantillas de SoftMaker, archivos compilados, dependencias y papeleras. No borra archivos.")
        box.pack_start(hide_technical, False, False, 0)
        model = Gtk.Entry(text=config["model"], placeholder_text="Vacío para usar reglas en español")
        excluded = Gtk.Entry(text=" | ".join(config["excludes"]),
                             placeholder_text="Ejemplo /home/usuario/privado | /ruta/otra")
        minutes = Gtk.SpinButton.new_with_range(1, 1440, 1)
        minutes.set_value(config["minutes"])
        for label, widget in [
            ("Excluir carpetas (separa rutas absolutas con |)", excluded),
            ("Modelo Ollama local (opcional)", model),
            ("Intervalo de revisión automática (minutos)", minutes),
        ]:
            box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            box.pack_start(widget, False, False, 0)
        message = Gtk.Label(xalign=0)
        message.set_line_wrap(True)
        box.pack_start(message, False, False, 0)
        box.pack_start(Gtk.Label(label=f"Versión {VERSION}", xalign=0), False, False, 0)
        update_progress()
        progress_timer = GLib.timeout_add_seconds(1, update_progress)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            exclusions = [part.strip() for part in excluded.get_text().split("|") if part.strip()]
            if any(not Path(path).is_absolute() for path in exclusions):
                message.set_text("Escribe rutas absolutas para las exclusiones.")
                continue
            prefix = prefix_entry.get_text().strip().casefold()
            if not prefix or any(c.isspace() for c in prefix):
                message.set_text("El prefijo debe ser una palabra sin espacios.")
                continue
            if chosen[0]:
                outcome = self.save_shortcut(chosen[0])
                if outcome != "Atajo guardado.":
                    message.set_text(outcome)
                    continue
            engine.save({"search_prefix": prefix, "roots": [{"path": row[0], "mount": row[1]} for row in store],
                         "excludes": [os.path.normpath(path) for path in exclusions],
                         "model": model.get_text().strip(), "minutes": minutes.get_value_as_int(),
                         "hide_technical": hide_technical.get_active()})
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.process.wait()
            self.refresh(force=True)
            self.entry.set_text("")
            self.status.set_text("Actualizando índice en segundo plano.")
            dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
            dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).set_label("Cerrar")
            message.set_text("Puedes cerrar esta ventana mientras continúa el indexado.")
            update_progress()
        GLib.source_remove(progress_timer)
        dialog.destroy()

    @staticmethod
    def current_shortcut():
        source = Gio.SettingsSchemaSource.get_default()
        if not source.lookup(KEYS, True):
            return ""
        keys = Gio.Settings.new(KEYS)
        if BINDING_PATH not in keys.get_strv("custom-keybindings"):
            return ""
        binding = Gio.Settings.new_with_path(KEYS + ".custom-keybinding", BINDING_PATH)
        return binding.get_string("binding")

    @staticmethod
    def save_shortcut(accelerator):
        source = Gio.SettingsSchemaSource.get_default()
        if not source.lookup(KEYS, True):
            return "GNOME no ofrece atajos personalizados."
        key, mods = Gtk.accelerator_parse(accelerator)
        if not Gtk.accelerator_valid(key, mods):
            return "Combinación no válida."
        keys = Gio.Settings.new(KEYS)
        paths = keys.get_strv("custom-keybindings")
        for path in paths:
            if path != BINDING_PATH:
                other = Gio.Settings.new_with_path(KEYS + ".custom-keybinding", path)
                if Gtk.accelerator_parse(other.get_string("binding")) == (key, mods):
                    return "Atajo ya utilizado por otra aplicación."
        binding = Gio.Settings.new_with_path(KEYS + ".custom-keybinding", BINDING_PATH)
        if not all((binding.set_string("name", TITLE),
                    binding.set_string("command", "/usr/bin/busca-ai --quick"),
                    binding.set_string("binding", accelerator),
                    keys.set_strv("custom-keybindings", list(dict.fromkeys(paths + [BINDING_PATH]))))):
            return "GNOME no permitió guardar el atajo."
        Gio.Settings.sync()
        return "Atajo guardado."

    @staticmethod
    def shortcut():
        return Launcher.save_shortcut(Launcher.current_shortcut() or QUICK_BINDING)


def progress_file(pid):
    return engine.DATA / f"scan-progress-{pid}.json"


def write_progress(done, total, path, folder, files):
    target = progress_file(os.getpid())
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"done": done, "total": total, "path": path, "folder": folder, "files": files}))
    temp.replace(target)


if __name__ == "__main__":
    if "--index" in sys.argv:
        if not engine.scan(force="--force" in sys.argv, progress=write_progress):
            sys.exit(2)
    else:
        sys.exit(Launcher().run(sys.argv))
