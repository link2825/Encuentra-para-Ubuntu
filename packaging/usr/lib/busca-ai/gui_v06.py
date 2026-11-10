"""Encuentra 0.6: buscador flotante con resultados agrupados."""
import sys
import subprocess
import shutil
from pathlib import Path
from urllib.parse import quote
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gio, Gdk, GLib
import engine
import gui
from gui import Launcher as Base
gui.VERSION = "0.6.3-1"
CSS=b"""
#encuentra {background:#201e29;border:2px solid #a65ad6;border-radius:18px}
#search {font-size:19px;min-height:44px;border:2px solid #a65ad6;border-radius:24px;background:#302a38;color:white}
.section {background:#34303e;border-radius:14px;padding:12px}
.heading {font-weight:bold;font-size:15px}
.result {background:transparent;border:0;box-shadow:none}
.result:hover {background:#5b456e}
"""
class Launcher(Base):
    def __init__(self):
        super().__init__()
        self.apps=[];self.files=[];self.shop=[];self.serial=0;self.has_more=False;self.last_query=None;self.loading_more=False
    def do_activate(self):
        super().do_activate()
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.settings_button.show()
        self.folder_button.hide()
    def build(self):
        self.window=Gtk.ApplicationWindow(application=self,title="Encuentra")
        self.window.set_name("encuentra")
        self.window.set_default_size(850,130)
        self.window.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.window.connect("delete-event",lambda w,e:w.hide_on_delete())
        self.window.connect("key-press-event",self.keyboard)
        provider=Gtk.CssProvider();provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        main=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=9,margin=15);self.window.add(main)
        header=Gtk.Box(spacing=10);main.pack_start(header,False,False,0)
        header.pack_start(Gtk.Label(label="⌕  Encuentra"),False,False,0)
        self.entry=Gtk.SearchEntry();self.entry.set_name("search")
        self.entry.set_placeholder_text("Buscar aplicaciones, archivos, ajustes y tienda…")
        self.entry.connect("changed",self.changed);self.entry.connect("activate",self.submit)
        header.pack_start(self.entry,True,True,0)
        self.settings_button=Gtk.Button.new_from_icon_name("preferences-system-symbolic",Gtk.IconSize.BUTTON)
        self.settings_button.connect("clicked",lambda b:self.preferences())
        header.pack_start(self.settings_button,False,False,0)
        self.folder_button=Gtk.Button(label="Abrir carpeta");self.folder_button.set_no_show_all(True)
        self.status=Gtk.Label(xalign=0);main.pack_start(self.status,False,False,0)
        self.list_scroll=Gtk.ScrolledWindow();self.list_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        main.pack_start(self.list_scroll,True,True,0)
        self.sections=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);self.list_scroll.add(self.sections)
        self.rows=Gtk.ListStore(str,str,str,bool,str)
        self.results=Gtk.TreeView(model=self.rows)
        self.results.append_column(Gtk.TreeViewColumn("Resultado",Gtk.CellRendererText(),markup=1))
        self.render()
    def update_panel(self):
        active=bool(self.entry.get_text().strip())
        self.list_scroll.set_visible(active);self.status.set_visible(active)
        self.window.resize(850,590 if active else 105)
    def changed(self,*args):
        self.generation+=1;self.serial+=1
        if self.pending:GLib.source_remove(self.pending);self.pending=0
        q=self.entry.get_text().strip()
        self.apps=[];self.files=[];self.shop=[];self.rows.clear();self.has_more=False;self.last_query=None
        if q and self.natural(q):
            prefix=engine.settings().get('search_prefix','ia')
            self.status.set_text('Interpretando consulta…')
            self.pending=GLib.timeout_add(450,self.dispatch,q[len(prefix)+1:].strip(),True)
        elif q:
            n=engine.normalize(q)
            for app in Gio.AppInfo.get_all():
                if app.should_show() and n in engine.normalize((app.get_display_name() or "")+" "+(app.get_description() or "")):
                    self.apps.append(app)
            self.apps.sort(key=lambda a:(not engine.normalize(a.get_display_name() or "").startswith(n),a.get_display_name() or ""))
            self.apps=self.apps[:12]
            self.pending=GLib.timeout_add(180,self.dispatch,q,False)
            if len(q)>=3 and shutil.which("snap"):
                serial=self.serial
                f=self.worker.submit(self.find_store,q)
                f.add_done_callback(lambda future:GLib.idle_add(self.store_ready,serial,future))
        if not self.natural(q): self.status.set_text("Buscando…" if q else "")
        self.render();self.update_panel()
    @staticmethod
    def find_store(q):
        try:
            r=subprocess.run(["snap","find",q],capture_output=True,text=True,timeout=7)
            if r.returncode:return []
            out=[]
            for line in r.stdout.splitlines()[1:]:
                fields=line.split(None,4)
                if len(fields)==5:out.append((fields[0],fields[4]))
            return out[:5]
        except (OSError,subprocess.TimeoutExpired):return []
    def store_ready(self,serial,f):
        if serial==self.serial:
            try:self.shop=f.result()
            except Exception:self.shop=[]
            self.render()
        return False
    def show_results(self,generation,future):
        if generation!=self.generation:return False
        try:
            self.files,mode=future.result()
            self.rows.clear()
            for path,name,date,available,directory,full in self.files:
                self.rows.append(("folder" if directory else "text-x-generic",GLib.markup_escape_text(name),path,directory,GLib.markup_escape_text(full)))
            self.status.set_text(f"{len(self.apps)} aplicaciones · {len(self.files)} archivos · {mode}")
        except Exception as e:self.status.set_text(str(e))
        self.render();self.update_panel()
        return False
    def section(self,title):
        panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6)
        panel.get_style_context().add_class("section")
        head=Gtk.Label(label=title,xalign=0);head.get_style_context().add_class("heading")
        panel.pack_start(head,False,False,0)
        self.sections.pack_start(panel,False,False,0)
        return panel
    def item(self,parent,title,detail,icon,callback):
        b=Gtk.Button();b.get_style_context().add_class("result")
        line=Gtk.Box(spacing=10);b.add(line)
        img=Gtk.Image.new_from_gicon(icon,Gtk.IconSize.DND) if isinstance(icon,Gio.Icon) else Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.DND)
        img.set_pixel_size(34);line.pack_start(img,False,False,0)
        texts=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        line.pack_start(texts,True,True,0)
        label=Gtk.Label(label=title,xalign=0);label.set_ellipsize(3);texts.pack_start(label,False,False,0)
        if detail:
            sub=Gtk.Label(label=detail,xalign=0);sub.set_ellipsize(3);sub.set_max_width_chars(95)
            texts.pack_start(sub,False,False,0)
        b.connect("clicked",lambda *_:callback());parent.pack_start(b,False,False,0)
    def render(self):
        for child in self.sections.get_children():self.sections.remove(child)
        if not self.entry.get_text().strip():return
        if self.apps:
            panel=self.section(f"Aplicaciones ({len(self.apps)})")
            grid=Gtk.FlowBox();grid.set_selection_mode(Gtk.SelectionMode.NONE);grid.set_max_children_per_line(5)
            panel.pack_start(grid,False,False,0)
            for app in self.apps[:10]:
                holder=Gtk.Box()
                self.item(holder,app.get_display_name(),"",app.get_icon() or "application-x-executable",lambda app=app:self.launch_app(app))
                grid.add(holder)
        if self.shop:
            panel=self.section(f"Tienda de aplicaciones ({len(self.shop)})")
            for name,summary in self.shop:self.item(panel,name,summary,"software-store",lambda name=name:self.open_store(name))
        settings=[a for a in self.apps if "configuraci" in engine.normalize(a.get_display_name() or "") or "settings" in engine.normalize(a.get_display_name() or "")]
        if settings:
            panel=self.section(f"Configuración ({len(settings)})")
            for app in settings[:5]:self.item(panel,app.get_display_name(),app.get_description() or "",app.get_icon() or "preferences-system",lambda app=app:self.launch_app(app))
        if self.files:
            panel=self.section(f"Archivos y carpetas ({len(self.files)})")
            for i,(path,name,date,available,directory,full) in enumerate(self.files):
                self.item(panel,name,full if available else "Ubicación no disponible","folder" if directory else "text-x-generic",lambda i=i:self.open_file(i))
        self.sections.show_all()
    def launch_app(self,app):
        try:app.launch([],None);self.window.hide()
        except GLib.Error as e:self.status.set_text(str(e))
    def open_store(self,name):
        try:Gio.AppInfo.launch_default_for_uri("snap://"+quote(name,safe=""),None);self.window.hide()
        except GLib.Error:self.status.set_text("No hay un manejador de enlaces snap://")
    def open_file(self,index):
        self.results.get_selection().select_path(Gtk.TreePath.new_from_indices([index]))
        self.open_selected(False)
    def submit(self,*args):
        q=self.entry.get_text().strip()
        if self.natural(q):self.dispatch(q[len(engine.settings().get("search_prefix","ia"))+1:].strip(),True)
        elif self.apps:self.launch_app(self.apps[0])
        elif self.files:self.open_file(0)
    def keyboard(self,widget,event):
        if event.keyval==Gdk.KEY_Escape:self.window.hide();return True
        return False
if __name__=="__main__":
    if "--index" in sys.argv:
        from gui import write_progress
        sys.exit(0 if engine.scan(force="--force" in sys.argv,progress=write_progress) else 2)
    sys.exit(Launcher().run(sys.argv))
