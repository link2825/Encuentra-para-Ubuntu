import calendar
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit, unquote
import unicodedata
import urllib.request

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "busca-ai"
CONFIG = DATA / "config.json"
FOLDER_EXT = "/folder"
TYPES = {
    "pdf": ("pdf",), "excel": ("xls", "xlsx", "xlsm", "ods", "csv"),
    "word": ("doc", "docx", "odt"), "imagenes": ("jpg", "jpeg", "png", "webp", "heic"),
    "powerpoint": ("ppt", "pptx", "odp"),
    "video": ("mp4", "mkv", "avi", "mov", "webm"),
    "audio": ("mp3", "flac", "wav", "ogg", "m4a"),
    "zip": ("zip", "7z", "rar", "tar", "gz"),
    "iso": ("iso",), "txt": ("txt",), "csv": ("csv",),
    "json": ("json",), "sql": ("sql",),
    "respaldo": ("bak", "backup", "sql", "zip"),
}


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold())
                   if not unicodedata.combining(c))


def settings():
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {
        "roots": [], "excludes": [], "model": "", "minutes": 30, "search_prefix": "ia",
    }

    config.setdefault("search_prefix", "ia")

    # Retire direct API sources while preserving mounted folders and other settings.
    roots = [root for root in config["roots"]
             if not root["path"].startswith(("drive-api:", "onedrive-api:"))]
    if roots != config["roots"]:
        config["roots"] = roots
        save(config)
    return config


def save(config):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False))
    temp.replace(CONFIG)


def rclone_mounts():
    found = []
    with open("/proc/self/mountinfo") as mounts:
        for line in mounts:
            prefix, suffix = line.rstrip().split(" - ", 1)
            mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), prefix.split()[4])
            if suffix.split()[0] == "fuse.rclone":
                found.append(mount)
    return sorted(found, key=len, reverse=True)


def mount_for(path):
    return next((mount for mount in rclone_mounts() if Path(path).is_relative_to(mount)), "")


def is_remote(path):
    return path.startswith(("google-drive://", "smb://"))


def remote_mounts():
    from gi.repository import Gio
    return [mount.get_root() for mount in Gio.VolumeMonitor.get().get_mounts()
            if is_remote(mount.get_root().get_uri())]


def remote_available(path, mounts):
    from gi.repository import Gio
    file = Gio.File.new_for_uri(path)
    return any(file.equal(mount) or file.has_prefix(mount) for mount in mounts)


def smb_server_only(path):
    return path.startswith("smb://") and not urlsplit(path).path.strip("/")


def remote_entries(folder, retry_google):
    from gi.repository import Gio, GLib
    for attempt in range(3):
        try:
            entries = folder.enumerate_children(
                "standard::name,standard::display-name,standard::type,standard::is-hidden,time::modified",
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
            try:
                children = []
                while (info := entries.next_file(None)) is not None:
                    children.append((info, entries.get_child(info)))
                return children
            finally:
                entries.close(None)
        except GLib.Error as error:
            if not retry_google or "(code 500)" not in error.message or attempt == 2:
                raise OSError(f"{folder.get_parse_name()}: {error.message}") from error
            time.sleep(2 ** attempt)


def walk_remote(root, errors, progress=None):
    from gi.repository import Gio
    pending = [Gio.File.new_for_uri(root)]
    visited = set()
    files = 0
    while pending:
        folder = pending.pop()
        uri = folder.get_uri()
        if uri in visited:
            continue
        visited.add(uri)
        if progress:
            progress(folder.get_parse_name(), files)
        try:
            children = remote_entries(folder, root.startswith("google-drive://"))
        except OSError as error:
            if not root.startswith("google-drive://") or folder.equal(Gio.File.new_for_uri(root)):
                raise
            errors.append(str(error))
            continue
        for info, child in children:
            if info.has_attribute("standard::is-hidden") and info.get_is_hidden():
                continue
            kind = info.get_file_type()
            if kind == Gio.FileType.DIRECTORY:
                pending.append(child)
            if kind in (Gio.FileType.DIRECTORY, Gio.FileType.REGULAR):
                files += kind == Gio.FileType.REGULAR
                name = info.get_display_name()
                yield (root, child.get_uri(), name, normalize(name),
                       FOLDER_EXT if kind == Gio.FileType.DIRECTORY else Path(name).suffix.lower().lstrip("."),
                       info.get_attribute_uint64("time::modified"))


def database():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / "files.db", timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            root TEXT, path TEXT, name TEXT, norm TEXT, ext TEXT, modified REAL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS files_root_path ON files(root,path);
        CREATE INDEX IF NOT EXISTS files_date ON files(modified DESC);
        CREATE VIRTUAL TABLE IF NOT EXISTS names USING fts5(
            norm, content='files', content_rowid='rowid', tokenize='trigram'
        );
        CREATE TRIGGER IF NOT EXISTS files_insert AFTER INSERT ON files BEGIN
            INSERT INTO names(rowid,norm) VALUES(new.rowid,new.norm);
        END;
        CREATE TRIGGER IF NOT EXISTS files_delete AFTER DELETE ON files BEGIN
            INSERT INTO names(names,rowid,norm) VALUES('delete',old.rowid,old.norm);
        END;
        CREATE TABLE IF NOT EXISTS scans(root TEXT PRIMARY KEY, updated REAL, status TEXT);
    """)
    return conn


def scan(force=False, progress=None):
    def report(done, total, path="", folder="", files=0):
        if progress:
            progress(done, total, path, folder, files)

    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "scan.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        config = settings()
        with database() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                conn.execute("UPDATE scans SET updated=0")
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='onedrive_state'").fetchone():
                    conn.execute("DELETE FROM onedrive_state")
                conn.execute("PRAGMA user_version=1")
                conn.commit()
            conn.execute("CREATE TEMP TABLE staged AS SELECT * FROM files WHERE 0")
            conn.execute("CREATE UNIQUE INDEX staged_path ON staged(path)")
            configured = {item["path"] for item in config["roots"]}
            for (old_root,) in conn.execute("SELECT root FROM scans").fetchall():
                if old_root not in configured:
                    conn.execute("DELETE FROM files WHERE root=?", (old_root,))
                    conn.execute("DELETE FROM scans WHERE root=?", (old_root,))
                    if old_root.startswith("onedrive-api:") and conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='onedrive_state'"
                    ).fetchone():
                        conn.execute("DELETE FROM onedrive_state WHERE root=?", (old_root,))
                        conn.execute("DELETE FROM onedrive_items WHERE root=?", (old_root,))
            conn.commit()
            roots = sorted(config["roots"], key=lambda item: (
                is_remote(item["path"]), item["path"].startswith("google-drive://"),
                bool(item["mount"])))
            for done, root in enumerate(roots):
                report(done, len(roots), root["path"])
                path = root["path"]
                previous = conn.execute("SELECT updated,status FROM scans WHERE root=?", (path,)).fetchone()
                now = dt.datetime.now().timestamp()
                if smb_server_only(path):
                    status = "Agrega una carpeta compartida del NAS"
                elif root["mount"] and mount_for(path) != root["mount"]:
                    status = "Montaje no disponible"
                elif not force and previous and (previous[1] == "Actualizado" or previous[1].startswith("Parcial")) and now - previous[0] < config["minutes"] * 60:
                    continue
                else:
                    try:
                        errors = []
                        conn.execute("DELETE FROM staged")
                        conn.executemany("INSERT INTO staged VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO NOTHING",
                                         walk_remote(path, errors, lambda folder, files: report(done, len(roots), path, folder, files)) if is_remote(path) else walk(path, config["excludes"], lambda folder, files: report(done, len(roots), path, folder, files)))
                        if root["mount"] and mount_for(path) != root["mount"]:
                            raise OSError("El montaje se desconectó")
                        conn.execute("""DELETE FROM files WHERE root=? AND (NOT ? OR path IN (SELECT path FROM staged)) AND NOT EXISTS (
                            SELECT 1 FROM staged WHERE staged.path=files.path
                            AND staged.modified=files.modified AND staged.name=files.name AND staged.ext=files.ext
                        )""", (path, bool(errors)))
                        conn.execute("""INSERT INTO files SELECT * FROM staged WHERE NOT EXISTS (
                            SELECT 1 FROM files WHERE files.root=? AND files.path=staged.path
                        )""", (path,))
                        status = (f"Parcial · {len(errors)} carpetas con error · {errors[0]}"
                                  if errors else "Actualizado")
                    except OSError as error:
                        status = str(error)
                conn.execute("INSERT OR REPLACE INTO scans VALUES(?,?,?)", (path, now, status))
                conn.commit()
            report(len(roots), len(roots))
    return True


def walk(root, excludes, progress=None):
    excluded = [Path(path) for path in excludes]
    if any(Path(root).is_relative_to(path) for path in excluded):
        return
    nested_mounts = {mount for mount in rclone_mounts() if mount != root and Path(mount).is_relative_to(root)}
    pending = [root]
    files = 0
    last_report = 0
    while pending:
        folder = pending.pop()
        if progress:
            progress(folder, files)
            last_report = time.monotonic()
        with os.scandir(folder) as entries:
            for entry in entries:
                if (entry.name.startswith(".") or entry.path in nested_mounts
                        or any(Path(entry.path).is_relative_to(path) for path in excluded)):
                    continue
                directory = entry.is_dir(follow_symlinks=False)
                if directory:
                    pending.append(entry.path)
                if directory or entry.is_file(follow_symlinks=False):
                    try:
                        modified = entry.stat(follow_symlinks=False).st_mtime
                    except FileNotFoundError:
                        continue
                    files += not directory
                    if progress and time.monotonic() - last_report >= 0.5:
                        progress(folder, files)
                        last_report = time.monotonic()
                    yield (root, entry.path, entry.name, normalize(entry.name),
                           FOLDER_EXT if directory else Path(entry.name).suffix.lower().lstrip("."), modified)

    if progress:
        progress(root, files)


def local_filters(query, today):
    phrase = normalize(query)
    begin = end = None
    months_ago = re.search(r"\b(?:de |desde |hace )?(\d{1,2}) meses?\b", phrase)
    if months_ago:
        months = int(months_ago.group(1))
        if 1 <= months <= 120:
            month_index = today.year * 12 + today.month - 1 - months
            year, month_zero = divmod(month_index, 12)
            begin = dt.date(year, month_zero + 1, 1)
            end = dt.date(year + (month_zero == 11), (month_zero + 1) % 12 + 1, 1)
            phrase = phrase[:months_ago.start()] + " " + phrase[months_ago.end():]
    for pattern, period in [
        (r"\b(?:el |del )?mes pasado\b", "last"),
        (r"\b(?:este|en este) mes\b", "month"),
        (r"\banteayer\b", 2), (r"\bayer\b", 1), (r"\bhoy\b", 0),
    ]:
        if begin is None and re.search(pattern, phrase):
            phrase = re.sub(pattern, "", phrase)
            if period == "last":
                end = today.replace(day=1)
                begin = (end - dt.timedelta(days=1)).replace(day=1)
            elif period == "month":
                begin = today.replace(day=1)
                end = begin + dt.timedelta(days=calendar.monthrange(today.year, today.month)[1])
            else:
                begin = today - dt.timedelta(days=period)
                end = begin + dt.timedelta(days=1)
            break
    relative = re.search(r"\bultimos? (\d{1,3}) dias?\b", phrase)
    if relative:
        days = int(relative.group(1))
        if 1 <= days <= 365:
            begin = today - dt.timedelta(days=days)
            end = today + dt.timedelta(days=1)
            phrase = phrase.replace(relative.group(0), " ")
    year = re.search(r"\b(?:de |del |en )?(20\d{2})\b", phrase)
    if year and begin is None:
        y = int(year.group(1))
        begin, end = dt.date(y, 1, 1), dt.date(y+1, 1, 1)
        phrase = phrase.replace(year.group(0), " ")
    extensions = []
    for kind, values in TYPES.items():
        pattern = rf"\b{kind}s?\b"
        if re.search(pattern, phrase):
            extensions.extend(values)
            phrase = re.sub(pattern, "", phrase)
    terms = re.findall(r"[\w-]+", phrase)
    ignored = "busca buscar encuentra muestra archivos archivo documentos documento los las el la de del que en un una por con y o modificados modificado recientes reciente mas ultimo ultimos".split()
    return [term for term in terms if term not in ignored], extensions, begin, end


def interpret(query, model):
    today = dt.date.today()
    if not model:
        return local_filters(query, today), "Reglas en español"
    prompt = (
        f"Hoy es {today}. Interpreta una consulta de archivos. Devuelve solo un objeto JSON "
        "con terms (lista de palabras del nombre), extensions (lista sin punto), "
        "start (YYYY-MM-DD inclusivo o null), end (YYYY-MM-DD exclusivo o null). "
        "Las fechas son de modificación. No inventes términos. Consulta: " + query
    )
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False,
                         "format": "json", "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            parsed = json.loads(json.load(response)["response"])
        terms, extensions = parsed["terms"], parsed["extensions"]
        for values in (terms, extensions):
            if not isinstance(values, list) or len(values) > 20 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 100 for item in values
            ):
                raise ValueError("Filtros no válidos")
        dates = [dt.date.fromisoformat(parsed[key]) if parsed[key] else None for key in ("start", "end")]
        filters = ([normalize(term) for term in terms],
                   [ext.lower().lstrip(".") for ext in extensions], *dates)
        if not any(filters) or (all(dates) and dates[0] >= dates[1]):
            raise ValueError("Filtros no válidos")
        return filters, "IA local"
    except (OSError, ValueError, KeyError, TypeError):
        return local_filters(query, today), "Ollama no disponible o respuesta inválida. Se usaron reglas."


def technical_file(path, ext):
    decoded = unquote(path).replace("\\", "/").casefold()
    parts = decoded.split("/")
    if decoded.startswith(("/usr/", "/etc/", "/proc/", "/sys/", "/dev/", "/var/", "/boot/", "/opt/")):
        return True
    if any(part == ".local" for part in parts):
        return True
    if any(part in {"__pycache__", "node_modules", "$recycle.bin", "#recycle", "site-packages", "dist-packages"} for part in parts):
        return True
    if "softmaker" in parts and any("templates" in part for part in parts):
        return True
    return ext.casefold() in {"pyc", "pyo", "so", "dll", "o", "a", "class", "tmvx", "pmvx", "prvx"}


def search(conn, config, filters, limit=100, offset=0, order='name', kind='all'):
    terms, extensions, begin, end = filters
    roots = {item["path"]: item["mount"] for item in config["roots"]}
    if not roots or not any(filters):
        return []
    clauses = ["root IN (" + ",".join("?" for _ in roots) + ")"]
    args = list(roots)
    if kind == "files":
        clauses.append("ext <> ?")
        args.append(FOLDER_EXT)
    elif kind == "folders":
        clauses.append("ext = ?")
        args.append(FOLDER_EXT)
    if config.get("hide_technical", True):
        conn.create_function("encuentra_technical", 2, technical_file, deterministic=True)
        clauses.append("NOT encuentra_technical(path,ext)")
    for path in config["excludes"]:
        prefix = path.rstrip("/") + "/"
        clauses.append("(path <> ? AND substr(path,1,?) <> ?)")
        args.extend((path, len(prefix), prefix))
    long_terms = [term for term in terms if len(term) >= 3 and "\0" not in term]
    if long_terms:
        clauses.append("rowid IN (SELECT rowid FROM names WHERE names MATCH ?)")
        args.append(" AND ".join('"' + term.replace('"', '""') + '"' for term in long_terms))
    for term in terms:
        if term not in long_terms:
            clauses.append("instr(norm, ?) > 0")
            args.append(term)
    if extensions:
        clauses.append("ext IN (" + ",".join("?" for _ in extensions) + ")")
        args.extend(extensions)
    for operator, date in ((">=", begin), ("<", end)):
        if date:
            clauses.append(f"modified {operator} ?")
            args.append(dt.datetime.combine(date, dt.time()).timestamp())
    order_sql = {"name": "ORDER BY (ext = ?) DESC, norm ASC, name ASC, path ASC",
                 "newest": "ORDER BY modified DESC, norm ASC",
                 "oldest": "ORDER BY modified ASC, norm ASC"}.get(order)
    if order_sql is None:
        order_sql = "ORDER BY (ext = ?) DESC, norm ASC, name ASC, path ASC"
        order = "name"
    extra = [FOLDER_EXT] if order == "name" else []
    rows = conn.execute("SELECT root,path,name,modified,ext FROM files WHERE " +
                        " AND ".join(clauses) + " " + order_sql + " LIMIT ? OFFSET ?",
                        args + extra + [limit, offset])
    mounted_remotes = remote_mounts() if any(map(is_remote, roots)) else []
    available = {path: remote_available(path, mounted_remotes) if is_remote(path)
                 else not mount or mount_for(path) == mount for path, mount in roots.items()}
    return [(path, name, modified, available[root], ext == FOLDER_EXT)
            for root, path, name, modified, ext in rows]
