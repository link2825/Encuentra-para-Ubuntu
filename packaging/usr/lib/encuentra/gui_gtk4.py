"""Encuentra GTK4/libadwaita GTK4; shares the existing SQLite index and config."""
import datetime as dt
import json
import os
import fcntl
import time
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk
import engine

VERSION = '0.8.7'
CSS = '''
window.encuentra {background:#211d29;}
.search {
    border:2px solid #3584E4;
    border-radius:22px;
    min-height:42px;
    font-size:18px;
}
.search:focus,
.search:focus-within {
    border-color:#3584E4;
    outline-color:#3584E4;
    box-shadow:0 0 0 1px #3584E4;
}
.section {background:#35303f;border-radius:14px;padding:10px;}
.section-title {font-weight:bold;font-size:15px;}
.result {background:transparent;border:0;box-shadow:none;}
.result:hover {background:#554364;}
.muted {opacity:0.75;font-size:12px;}
'''

class Encuentra(Adw.Application):
    def __init__(self):
        super().__init__(application_id='local.encuentra.Gtk4', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.generation = 0
        self.pending = 0
        self.files = []
        self.apps = []
        self.shop = []
        self.has_more = False
        self.last_query = None
        self.loading_more = False
        self.serial = 0
        self.file_dialog = None
        self.scan_process = None
        self.scan_progress_path = engine.DATA / 'gtk4-scan-progress.json'
        self.scan_last = None
        self.preferences_dialog = None
        self.focus_check_id = 0

    def do_command_line(self, command_line):
        args = command_line.get_arguments()
        if '--background' in args:
            self.hold()
            self.refresh()
            return 0
        self.activate()
        if '--settings' in args:
            self.preferences()
        return 0

    def do_activate(self):
        if self.window is None:
            self.build()
        self.window.present()
        GLib.idle_add(self.entry.grab_focus)

    def build(self):
        self.window = Adw.ApplicationWindow(application=self, title='Encuentra')
        self.window.set_icon_name('encuentra')
        self.window.connect('notify::is-active', self.on_window_active)
        self.window.set_default_size(700, 75)
        self.window.add_css_class('encuentra')
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main.set_margin_top(12); main.set_margin_bottom(12)
        main.set_margin_start(14); main.set_margin_end(14)
        self.window.set_content(main)
        header = Gtk.Box(spacing=10)
        main.append(header)
        header.append(Gtk.Label(label='⌕ Encuentra'))
        self.entry = Gtk.SearchEntry(placeholder_text='Buscar aplicaciones, archivos, ajustes y tienda…')
        self.entry.set_hexpand(True); self.entry.add_css_class('search')
        self.entry.connect('search-changed', self.changed)
        self.entry.connect('activate', self.submit)
        header.append(self.entry)
        settings = Gtk.Button(icon_name='preferences-system-symbolic', tooltip_text='Configuración')
        settings.connect('clicked', lambda *_: self.preferences())
        header.append(settings)
        self.status = Gtk.Label(xalign=0)
        main.append(self.status)
        self.index_status = Gtk.Label(xalign=0)
        self.index_status.add_css_class('muted')
        main.append(self.index_status)
        GLib.timeout_add_seconds(2, self.poll_index)
        self.poll_index()
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        main.append(self.scroll)
        self.sections = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.scroll.set_child(self.sections)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.key_pressed)
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.window.add_controller(keys)
        self.update_panel()

    def on_window_active(self, window, _pspec):
        # GTK4 can temporarily deactivate the toplevel when a native
        # context menu or a transient preferences window receives focus.
        if window.is_active():
            if self.focus_check_id:
                GLib.source_remove(self.focus_check_id)
                self.focus_check_id = 0
        elif window.get_visible() and not self.focus_check_id:
            self.focus_check_id = GLib.timeout_add(500, self.check_window_focus)

    def has_visible_popover(self, widget):
        if isinstance(widget, Gtk.Popover) and widget.get_visible():
            return True
        child = widget.get_first_child()
        while child is not None:
            if self.has_visible_popover(child):
                return True
            child = child.get_next_sibling()
        return False

    def check_window_focus(self):
        self.focus_check_id = 0
        if not self.window.get_visible() or self.window.is_active():
            return GLib.SOURCE_REMOVE
        if self.preferences_dialog is not None and self.preferences_dialog.get_visible():
            return GLib.SOURCE_REMOVE
        if self.has_visible_popover(self.window):
            return GLib.SOURCE_REMOVE
        self.window.hide()
        return GLib.SOURCE_REMOVE

    def key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.window.hide()
            return True
        if keyval in (Gdk.KEY_l, Gdk.KEY_L) and state & Gdk.ModifierType.CONTROL_MASK:
            self.entry.grab_focus()
            self.entry.select_region(0, -1)
            return True
        return False

    def update_panel(self):
        active = bool(self.entry.get_text().strip())
        self.scroll.set_visible(active)
        self.status.set_visible(active)
        self.index_status.set_visible(active)
        self.window.set_resizable(active)
        self.window.set_default_size(700, 500 if active else 75)
        if not active:
            self.window.set_size_request(-1, -1)

    def natural(self, q):
        prefix = engine.settings().get('search_prefix', 'ia')
        return q.casefold().startswith(prefix.casefold() + ' ')

    def changed(self, *_):
        self.generation += 1; self.serial += 1
        if self.pending:
            GLib.source_remove(self.pending); self.pending = 0
        q = self.entry.get_text().strip()
        self.apps = []; self.files = []; self.shop = []
        self.has_more = False; self.last_query = None
        if self.natural(q):
            prefix = engine.settings().get('search_prefix', 'ia')
            self.status.set_text('Interpretando consulta…')
            self.pending = GLib.timeout_add(450, self.dispatch, q[len(prefix)+1:].strip(), True)
        elif q:
            n = engine.normalize(q)
            self.apps = [app for app in Gio.AppInfo.get_all() if app.should_show() and n in engine.normalize((app.get_display_name() or '') + ' ' + (app.get_description() or ''))]
            self.apps.sort(key=lambda app: (not engine.normalize(app.get_display_name() or '').startswith(n), app.get_display_name() or ''))
            self.apps = self.apps[:12]
            self.pending = GLib.timeout_add(180, self.dispatch, q, False)
            if len(q) >= 3 and shutil.which('snap'):
                serial = self.serial
                f = self.pool.submit(self.find_store, q)
                f.add_done_callback(lambda fut: GLib.idle_add(self.store_ready, serial, fut))
            self.status.set_text('Buscando…')
        else:
            self.status.set_text('')
        self.render(); self.update_panel()

    @staticmethod
    def find_store(q):
        try:
            result = subprocess.run(['snap', 'find', q], capture_output=True, text=True, timeout=7)
            if result.returncode:
                return []
            output = []
            for line in result.stdout.splitlines()[1:]:
                fields = line.split(None, 4)
                if len(fields) == 5:
                    output.append((fields[0], fields[4]))
            return output[:5]
        except (OSError, subprocess.TimeoutExpired):
            return []

    def store_ready(self, serial, future):
        if serial == self.serial:
            try: self.shop = future.result()
            except Exception: self.shop = []
            self.render()
        return False

    @staticmethod
    def lookup(query, natural, offset=0):
        kind = 'all'; order = 'name'; recent = False
        if natural:
            q = engine.normalize(query)
            if re.search(r'\b(?:solo )?(?:carpetas|directorios)\b', q):
                kind = 'folders'
            elif re.search(r'\b(?:archivos?|ficheros?)\b', q):
                kind = 'files'
            if re.search(r'\b(?:recientes?|mas recientes?|mas nuevos?|ultimos?|actualizados?)\b', q):
                order = 'newest'
                recent = bool(re.search(r'\b(?:recientes?|mas recientes?)\b', q))
            elif re.search(r'\b(?:mas antiguos?|primero)\b', q):
                order = 'oldest'
            q = re.sub(r'\b(?:solo )?(?:archivos?|ficheros?|carpetas|directorios)\b', ' ', q)
            q = re.sub(r'\b(?:mas )?(?:recientes?|nuevos?|antiguos?)\b|\b(?:ultimos?|actualizados?|primero)\b', ' ', q)
            filters, mode = engine.interpret(q, engine.settings().get('model', ''))
            if recent and filters[2] is None and filters[3] is None:
                today = dt.date.today()
                filters = (filters[0], filters[1], today-dt.timedelta(days=14), today+dt.timedelta(days=1))
                mode += ' · Últimos 14 días'
        else:
            filters, mode = ([engine.normalize(query)], [], None, None), 'Por nombre'
        with engine.database() as conn:
            rows = engine.search(conn, engine.settings(), filters, limit=101, offset=offset, order=order, kind=kind)
            return rows[:100], mode, len(rows)>100

    def dispatch(self, q, natural):
        self.pending = 0; self.generation += 1
        gen = self.generation
        self.last_query = (q, natural)
        future = self.pool.submit(self.lookup, q, natural)
        future.add_done_callback(lambda f: GLib.idle_add(self.show_results, gen, f))
        return False

    def show_results(self, gen, future):
        if gen != self.generation:
            return False
        try:
            self.files, mode, self.has_more = future.result()
            self.status.set_text(f'{len(self.apps)} aplicaciones · {len(self.files)} archivos mostrados' + (' · Hay más' if self.has_more else '') + ' · ' + mode)
        except Exception as exc:
            self.status.set_text(f'Error de búsqueda: {exc}')
        self.render(); self.update_panel()
        return False

    def load_more(self, *_):
        if self.loading_more or not self.has_more or not self.last_query:
            return
        self.loading_more = True
        gen = self.generation
        q, natural = self.last_query
        future = self.pool.submit(self.lookup, q, natural, len(self.files))
        future.add_done_callback(lambda f: GLib.idle_add(self.append_results, gen, f))

    def append_results(self, gen, future):
        self.loading_more = False
        if gen != self.generation:
            return False
        try:
            batch, mode, self.has_more = future.result()
            self.files.extend(batch)
            self.status.set_text(f'{len(self.apps)} aplicaciones · {len(self.files)} archivos mostrados' + (' · Hay más' if self.has_more else '') + ' · ' + mode)
        except Exception as exc:
            self.status.set_text(str(exc))
        self.render()
        return False

    def section(self, name):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.add_css_class('section')
        heading = Gtk.Label(label=name, xalign=0)
        heading.add_css_class('section-title')
        panel.append(heading)
        self.sections.append(panel)
        return panel

    def item(self, parent, title, detail, icon, callback):
        button = Gtk.Button()
        button.add_css_class('result')
        line = Gtk.Box(spacing=10)
        button.set_child(line)
        if isinstance(icon, Gio.Icon):
            img = Gtk.Image.new_from_gicon(icon)
        else:
            img = Gtk.Image.new_from_icon_name(icon)
        img.set_pixel_size(32)
        line.append(img)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        line.append(text)
        name = Gtk.Label(label=title, xalign=0, ellipsize=3)
        text.append(name)
        if detail:
            subtitle = Gtk.Label(label=detail, xalign=0, ellipsize=3)
            subtitle.add_css_class('muted')
            text.append(subtitle)
        button.connect('clicked', lambda *_: callback())
        parent.append(button)

    def render(self):
        while child := self.sections.get_first_child():
            self.sections.remove(child)
        if not self.entry.get_text().strip():
            return
        if self.apps:
            panel = self.section(f'Aplicaciones ({len(self.apps)})')
            for app in self.apps[:10]:
                self.item(panel, app.get_display_name(), app.get_description() or '', app.get_icon() or 'application-x-executable', lambda app=app: self.launch_app(app))
        if self.shop:
            panel = self.section(f'Tienda de aplicaciones ({len(self.shop)})')
            for name, summary in self.shop:
                self.item(panel, name, summary, 'software-store', lambda name=name: self.open_store(name))
        if self.files:
            panel = self.section(f'Archivos y carpetas ({len(self.files)})')
            for path, name, modified, available, directory in self.files:
                stamp = dt.datetime.fromtimestamp(modified).strftime('%d/%m/%Y %H:%M') if modified else 'Fecha desconocida'
                detail = f'{unquote(path)} · Modificado: {stamp}' if available else 'Ubicación no disponible'
                self.item(panel, name, detail, 'folder' if directory else 'text-x-generic', lambda path=path, directory=directory: self.open_file(path, directory))
        if self.has_more:
            panel = self.section('Más resultados')
            button = Gtk.Button(label='Cargar 100 resultados más')
            button.connect('clicked', self.load_more)
            panel.append(button)

    def launch_app(self, app):
        try:
            app.launch([], None)
            self.window.hide()
        except GLib.Error as exc:
            self.status.set_text(str(exc))

    def open_store(self, name):
        try:
            Gio.AppInfo.launch_default_for_uri('snap://' + quote(name, safe=''), None)
            self.window.hide()
        except GLib.Error:
            self.status.set_text('No hay un manejador de enlaces snap://')

    def open_file(self, path, directory):
        try:
            file = Gio.File.new_for_uri(path) if '://' in path else Gio.File.new_for_path(path)
            if directory:
                subprocess.Popen(['nautilus', file.get_uri()])
            else:
                Gio.AppInfo.launch_default_for_uri(file.get_uri(), None)
            self.window.hide()
        except (GLib.Error, OSError) as exc:
            self.status.set_text(str(exc))

    def submit(self, *_):
        if self.apps:
            self.launch_app(self.apps[0])
        elif self.files:
            path, name, date, available, directory = self.files[0]
            self.open_file(path, directory)

    def preferences(self):
        if self.preferences_dialog is not None and self.preferences_dialog.get_visible():
            self.preferences_dialog.present()
            return
        config = engine.settings()
        dialog = Adw.PreferencesWindow(transient_for=self.window, modal=True, title='Configuración de Encuentra')
        self.preferences_dialog = dialog
        dialog.connect('close-request', self.on_preferences_closed)
        dialog.set_default_size(650, 560)
        page = Adw.PreferencesPage()
        dialog.add(page)
        roots = Adw.PreferencesGroup(title='Carpetas indexadas', description='Ubicaciones locales y montajes SMB/GVfs')
        page.add(roots)
        for item in config['roots']:
            row = Adw.ActionRow(title=unquote(item['path']))
            remove = Gtk.Button(icon_name='user-trash-symbolic', valign=Gtk.Align.CENTER)
            def delete(_button, path=item['path'], row=row):
                latest = engine.settings()
                latest['roots'] = [r for r in latest['roots'] if r['path'] != path]
                self.save_config(latest)
                roots.remove(row)
            remove.connect('clicked', delete)
            row.add_suffix(remove)
            roots.add(row)
        add = Adw.ActionRow(title='Agregar carpeta')
        button = Gtk.Button(icon_name='list-add-symbolic', valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda *_: self.select_folder(dialog, roots))
        add.add_suffix(button)
        roots.add(add)
        options = Adw.PreferencesGroup(title='Opciones')
        page.add(options)
        hide = Adw.SwitchRow(title='Ocultar archivos técnicos y .local')
        hide.set_active(config.get('hide_technical', True))
        hide.connect('notify::active', lambda row, *_: self.set_option('hide_technical', row.get_active()))
        options.add(hide)
        prefix = Adw.EntryRow(title='Prefijo de consultas inteligentes')
        prefix.set_text(config.get('search_prefix', 'ia'))
        prefix.connect('apply', lambda row: self.set_option('search_prefix', row.get_text().strip() or 'ia'))
        options.add(prefix)
        reindex = Adw.ActionRow(title='Actualizar índice')
        run = Gtk.Button(label='Indexar', valign=Gtk.Align.CENTER)
        run.connect('clicked', lambda *_: self.refresh())
        reindex.add_suffix(run)
        options.add(reindex)
        index_info = Adw.ActionRow(title='Estado de indexación', subtitle=self.index_status.get_text())
        options.add(index_info)
        shortcuts = Adw.PreferencesGroup(title='Atajos de teclado')
        page.add(shortcuts)
        shortcut_row = Adw.ActionRow(title='Abrir Encuentra', subtitle='Haz clic en el campo y pulsa tu combinación')
        shortcut_entry = Gtk.Entry(placeholder_text='Ctrl + Espacio', hexpand=True, valign=Gtk.Align.CENTER)
        shortcut_entry.set_text(self.current_shortcut() or '<Control>space')
        shortcut_entry.set_width_chars(20)
        shortcut_entry.set_editable(False)
        shortcut_row.add_suffix(shortcut_entry)
        save_key = Gtk.Button(label='Guardar', valign=Gtk.Align.CENTER)
        save_key.add_css_class('suggested-action')
        shortcut_row.add_suffix(save_key)
        shortcuts.add(shortcut_row)
        shortcut_feedback = Adw.ActionRow(title='Estado del atajo', subtitle='Sin cambios')
        shortcuts.add(shortcut_feedback)
        save_key.set_sensitive(False)
        def validate_entry(*_args):
            accelerator = shortcut_entry.get_text().strip()
            try:
                label = self.shortcut_conflict(accelerator)
                if label:
                    shortcut_feedback.set_subtitle('Combinación ocupada por «' + label + '». Elige otra.')
                    save_key.set_sensitive(False)
                else:
                    shortcut_feedback.set_subtitle('Combinación disponible. Pulsa Guardar.')
                    save_key.set_sensitive(True)
            except (ValueError, GLib.Error) as exc:
                shortcut_feedback.set_subtitle(str(exc))
                save_key.set_sensitive(False)
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        def capture_key(_controller, keyval, _keycode, state):
            modifiers = state & Gtk.accelerator_get_default_mod_mask()
            if keyval == Gdk.KEY_Escape:
                shortcut_feedback.set_subtitle('Captura cancelada')
                return True
            if not modifiers or keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
                                            Gdk.KEY_Control_L, Gdk.KEY_Control_R,
                                            Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
                                            Gdk.KEY_Super_L, Gdk.KEY_Super_R):
                return True
            key = Gdk.keyval_to_lower(keyval)
            accelerator = Gtk.accelerator_name(key, modifiers)
            shortcut_entry.set_text(accelerator)
            validate_entry()
            return True
        key_controller.connect('key-pressed', capture_key)
        shortcut_entry.add_controller(key_controller)
        shortcut_entry.connect('changed', validate_entry)
        shortcut_entry.connect('notify::has-focus', lambda entry, _pspec: shortcut_feedback.set_subtitle('Pulsa la combinación deseada') if entry.has_focus() else None)
        save_key.connect('clicked', lambda *_: self.save_shortcut(shortcut_entry.get_text().strip(), shortcut_feedback))
        validate_entry()
        shortcuts.add(Adw.ActionRow(title='Esc', subtitle='Ocultar Encuentra'))
        shortcuts.add(Adw.ActionRow(title='Intro', subtitle='Abrir el primer resultado'))
        shortcuts.add(Adw.ActionRow(title='Ctrl + L', subtitle='Enfocar la barra de búsqueda'))
        version_group = Adw.PreferencesGroup()
        version_row = Adw.ActionRow(title='Encuentra', subtitle='Versión 0.8.10')
        version_group.add(version_row)
        page.add(version_group)
        dialog.present()

    def on_preferences_closed(self, dialog):
        self.preferences_dialog = None
        # Return keyboard focus to the search field after closing settings.
        if self.window.get_visible():
            self.window.present()
            GLib.idle_add(self.entry.grab_focus)
        return False

    def select_folder(self, dialog, group):
        chooser = Gtk.FileDialog(title='Selecciona una carpeta')
        self.file_dialog = chooser
        chooser.select_folder(dialog, None, self.folder_selected, group)

    def folder_selected(self, chooser, result, group):
        try:
            folder = chooser.select_folder_finish(result)
            uri = folder.get_uri()
            path = folder.get_path() if uri.startswith('file://') else uri
            config = engine.settings()
            if not any(r['path'] == path for r in config['roots']):
                config['roots'].append({'path': path, 'mount': engine.mount_for(path) if not engine.is_remote(path) else ''})
                self.save_config(config)
                group.add(Adw.ActionRow(title=unquote(path)))
                self.refresh()
        except GLib.Error as exc:
            if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self.status.set_text(str(exc))

    def save_config(self, config):
        engine.DATA.mkdir(parents=True, exist_ok=True)
        (engine.DATA / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')

    def set_option(self, key, value):
        config = engine.settings()
        config[key] = value
        self.save_config(config)

    @staticmethod
    def shortcut_settings():
        schema = Gio.SettingsSchemaSource.get_default()
        key = 'org.gnome.settings-daemon.plugins.media-keys'
        if not schema or not schema.lookup(key, True):
            return None
        return Gio.Settings.new(key)

    SHORTCUT_PATH = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/encuentra/'

    def current_shortcut(self):
        settings = self.shortcut_settings()
        if settings and self.SHORTCUT_PATH in settings.get_strv('custom-keybindings'):
            return Gio.Settings.new_with_path(
                'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding',
                self.SHORTCUT_PATH).get_string('binding')
        return ''

    @staticmethod
    def shortcut_pair(accelerator):
        """Normalize accelerator strings for meaningful comparison."""
        parsed = Gtk.accelerator_parse(accelerator)
        # GTK 4 devuelve (success, keyval, modifiers); GTK 3 devolvía dos valores.
        if len(parsed) == 3:
            success, key, modifiers = parsed
            if not success:
                raise ValueError('Combinación inválida. Elige otra.')
        elif len(parsed) == 2:
            key, modifiers = parsed
        else:
            raise ValueError('Formato de combinación no reconocido.')
        if not key or not Gtk.accelerator_valid(key, modifiers):
            raise ValueError('Combinación inválida. Elige otra.')
        return Gdk.keyval_to_lower(key), modifiers

    def shortcut_conflict(self, accelerator):
        """Check custom and GNOME system keybindings before any write."""
        pair = self.shortcut_pair(accelerator)
        source = Gio.SettingsSchemaSource.get_default()
        if source is None:
            raise ValueError('No se pueden consultar los atajos del sistema.')
        custom_schema = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
        settings = self.shortcut_settings()
        if settings is None:
            raise ValueError('GNOME no ofrece el esquema de atajos de teclado.')
        for path in settings.get_strv('custom-keybindings'):
            if path == self.SHORTCUT_PATH:
                continue
            other = Gio.Settings.new_with_path(custom_schema, path)
            binding = other.get_string('binding')
            try:
                if self.shortcut_pair(binding) == pair:
                    return other.get_string('name') or 'otro atajo personalizado'
            except ValueError:
                pass

        # GNOME represents built-in shortcuts as strings or arrays of strings.
        # Iterate installed schemas, avoiding arbitrary application settings.
        schema_ids = (
            'org.gnome.desktop.wm.keybindings',
            'org.gnome.shell.keybindings',
            'org.gnome.mutter.keybindings',
            'org.gnome.mutter.wayland.keybindings',
            'org.gnome.settings-daemon.plugins.media-keys',
        )
        for schema_id in schema_ids:
            schema = source.lookup(schema_id, True)
            if schema is None:
                continue
            instance = Gio.Settings.new(schema_id)
            for name in schema.list_keys():
                if schema_id.endswith('media-keys') and name == 'custom-keybindings':
                    continue
                value = instance.get_value(name)
                signature = value.get_type_string()
                if signature == 's':
                    bindings = [value.unpack()]
                elif signature == 'as':
                    bindings = value.unpack()
                else:
                    continue
                for binding in bindings:
                    if not binding or binding == 'disabled':
                        continue
                    try:
                        if self.shortcut_pair(binding) == pair:
                            return name.replace('-', ' ') + ' (' + schema_id + ')'
                    except ValueError:
                        continue
        return None

    def save_shortcut(self, accelerator, status_row=None):
        """Validate conflicts, persist shortcut, and verify GNOME readback."""
        try:
            key, modifiers = self.shortcut_pair(accelerator)
            conflict = self.shortcut_conflict(accelerator)
            if conflict:
                raise ValueError('Combinación ocupada por «' + conflict + '». Elige otra.')
            accelerator = Gtk.accelerator_name(key, modifiers)
            settings = self.shortcut_settings()
            schema = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
            path = self.SHORTCUT_PATH
            paths = settings.get_strv('custom-keybindings')
            shortcut = Gio.Settings.new_with_path(schema, path)
            for name, value in (('name', 'Encuentra'),
                                ('command', '/usr/bin/encuentra'),
                                ('binding', accelerator)):
                if not shortcut.set_string(name, value):
                    raise RuntimeError('GNOME rechazó guardar ' + name + '.')
            if path not in paths and not settings.set_strv('custom-keybindings', [*paths, path]):
                raise RuntimeError('GNOME rechazó registrar el atajo.')
            Gio.Settings.sync()
            check = Gio.Settings.new_with_path(schema, path)
            if (path not in settings.get_strv('custom-keybindings') or
                check.get_string('binding') != accelerator or
                check.get_string('command') != '/usr/bin/encuentra'):
                raise RuntimeError('GNOME no conservó el atajo.')
            message = 'Atajo guardado: ' + Gtk.accelerator_get_label(key, modifiers)
        except (GLib.Error, RuntimeError, ValueError) as exc:
            message = 'No se pudo guardar: ' + str(exc)
        if status_row is not None:
            status_row.set_subtitle(message)

    def poll_index(self):
        try:
            lock_path = engine.DATA / 'scan.lock'
            running = False
            if lock_path.exists():
                with lock_path.open('a') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(lock, fcntl.LOCK_UN)
                    except BlockingIOError:
                        running = True
            if running:
                if self.scan_progress_path.exists():
                    data = json.loads(self.scan_progress_path.read_text())
                    current = data.get('done', 0)
                    total = data.get('total', 0)
                    folder = unquote(data.get('folder') or data.get('path') or '')
                    self.index_status.set_text(f'Indexando: {current}/{total} carpetas raíz · {folder[-75:]} · {data.get("files", 0)} archivos')
                else:
                    self.index_status.set_text('Indexando… preparando análisis')
            else:
                with engine.database() as conn:
                    count = conn.execute('SELECT COUNT(*) FROM files').fetchone()[0]
                    rows = conn.execute('SELECT MAX(updated) FROM scans').fetchone()[0]
                when = dt.datetime.fromtimestamp(rows).strftime('%d/%m/%Y %H:%M') if rows else 'sin indexación registrada'
                self.index_status.set_text(f'Índice disponible · {count:,} elementos · Última actualización: {when}')
        except Exception as exc:
            self.index_status.set_text(f'Índice: no se pudo consultar el estado ({exc})')
        return True

    def refresh(self):
        try:
            self.index_status.set_text('Solicitando actualización del índice…')
            subprocess.Popen([sys.executable, __file__, '--index'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            if self.window:
                self.index_status.set_text(str(exc))


def write_progress(done, total, path, folder, files):
    target = engine.DATA / 'gtk4-scan-progress.json'
    engine.DATA.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps({'done': done, 'total': total, 'path': path, 'folder': folder, 'files': files}))
    tmp.replace(target)

if __name__ == '__main__':
    if '--index' in sys.argv:
        if not engine.scan(force="--force" in sys.argv, progress=write_progress):
            sys.exit(2)
    else:
        app = Encuentra()
        sys.exit(app.run(sys.argv))
