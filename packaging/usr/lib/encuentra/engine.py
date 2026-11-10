"""Motor independiente de Encuentra GTK4; conserva el formato SQLite y configuración."""
import datetime as dt
import fcntl
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import unquote

DATA = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'busca-ai'
CONFIG = DATA/'config.json'
FOLDER_EXT = '/folder'
TYPES = {'pdf':['pdf'], 'word':['doc','docx','odt'], 'excel':['xls','xlsx','xlsm','ods','csv'],
         'imagenes':['jpg','jpeg','png','webp','heic'], 'video':['mp4','mkv','avi','mov'],
         'audio':['mp3','wav','ogg','flac'], 'zip':['zip','rar','7z','tar','gz'],
         'powerpoint':['ppt','pptx','odp'], 'iso':['iso'], 'sql':['sql'], 'txt':['txt']}

def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD',str(value).casefold()) if not unicodedata.combining(c))

def settings():
    data=json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    for key,value in [('roots',[]),('excludes',[]),('model',''),('minutes',30),('search_prefix','ia'),('hide_technical',True)]:
        data.setdefault(key,value)
    return data

def save(config):
    DATA.mkdir(parents=True,exist_ok=True)
    temp=CONFIG.with_suffix('.tmp');temp.write_text(json.dumps(config,ensure_ascii=False,indent=2));temp.replace(CONFIG)

def mount_for(path):
    try:
        with open('/proc/self/mountinfo') as f:
            mounts=[line.split(' - ')[0].split()[4].replace('\\040',' ') for line in f if ' - fuse.rclone ' in line]
        return next((m for m in sorted(mounts,key=len,reverse=True) if Path(path).is_relative_to(m)), '')
    except (OSError,ValueError):return ''

def is_remote(path):return path.startswith(('smb://','google-drive://'))

def database():
    DATA.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DATA/'files.db',timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''CREATE TABLE IF NOT EXISTS files(root TEXT,path TEXT,name TEXT,norm TEXT,ext TEXT,modified REAL);
    CREATE UNIQUE INDEX IF NOT EXISTS files_root_path ON files(root,path);
    CREATE INDEX IF NOT EXISTS files_date ON files(modified DESC);
    CREATE TABLE IF NOT EXISTS scans(root TEXT PRIMARY KEY,updated REAL,status TEXT);''')
    return conn

def local_filters(query,today=None):
    today=today or dt.date.today(); q=normalize(query)
    extensions=[]
    for key,values in TYPES.items():
        if re.search(r'\b'+key+r'\b',q):
            extensions.extend(values);q=re.sub(r'\b'+key+r'\b',' ',q)
    start=end=None
    m=re.search(r'\b(?:ultimos?|hace)\s+(\d+)\s+dias?\b',q)
    if m:
        start=today-dt.timedelta(days=int(m.group(1)));end=today+dt.timedelta(days=1);q=q.replace(m.group(0),' ')
    elif re.search(r'\bhoy\b',q):
        start=today;end=today+dt.timedelta(days=1);q=re.sub(r'\bhoy\b',' ',q)
    elif re.search(r'\bayer\b',q):
        start=today-dt.timedelta(days=1);end=today;q=re.sub(r'\bayer\b',' ',q)
    stop={'de','del','el','la','los','las','en','por','que','con','y','a','un','una','busca','buscar','dame','muestra','todos','todas','solo','mis'}
    terms=[t for t in re.findall(r'[\w.-]+',q) if t not in stop]
    return terms,sorted(set(extensions)),start,end

def interpret(query,model=''):
    return local_filters(query),'Reglas en español'

def technical_file(path,ext):
    p=unquote(path).replace('\\','/').casefold()
    return any(x in p.split('/') for x in ('.local','__pycache__','.cache','.git')) or p.startswith(('/usr/','/etc/','/proc/','/sys/','/dev/','/var/'))

def search(conn,config,filters,limit=100,offset=0,order='name',kind='all'):
    terms,extensions,begin,end=filters
    clauses=['1=1'];args=[]
    if kind=='files':clauses.append('ext<>?');args.append(FOLDER_EXT)
    if kind=='folders':clauses.append('ext=?');args.append(FOLDER_EXT)
    for t in terms:
        clauses.append('instr(norm,?)>0');args.append(normalize(t))
    if extensions:
        clauses.append('ext IN ('+','.join('?' for _ in extensions)+')');args.extend(extensions)
    if begin:clauses.append('modified>=?');args.append(dt.datetime.combine(begin,dt.time()).timestamp())
    if end:clauses.append('modified<?');args.append(dt.datetime.combine(end,dt.time()).timestamp())
    for p in config.get('excludes',[]):
        clauses.append('path NOT LIKE ?');args.append(p.rstrip('/')+'/%')
    if config.get('hide_technical',True):
        conn.create_function('encuentra_technical',2,technical_file)
        clauses.append('NOT encuentra_technical(path,ext)')
    sort={'name':'ORDER BY (ext=?) DESC,norm ASC','newest':'ORDER BY modified DESC','oldest':'ORDER BY modified ASC'}.get(order,'ORDER BY modified DESC')
    if order=='name':args.append(FOLDER_EXT)
    rows=conn.execute('SELECT path,name,modified,ext FROM files WHERE '+' AND '.join(clauses)+' '+sort+' LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    return [(p,n,m,True,e==FOLDER_EXT) for p,n,m,e in rows]

def scan(force=False,progress=None):
    from gi.repository import Gio
    import time
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'scan.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        roots=settings()['roots'];done=0
        with database() as conn:
            for root in roots:
                base=root['path'];count=0
                if progress:progress(done,len(roots),base,base,count)
                previous=conn.execute('SELECT updated FROM scans WHERE root=?',(base,)).fetchone()
                if not force and previous and time.time()-previous[0]<settings()['minutes']*60:
                    done+=1;continue
                conn.execute('CREATE TEMP TABLE IF NOT EXISTS seen(path TEXT PRIMARY KEY)')
                conn.execute('DELETE FROM seen')
                try:
                    if is_remote(base):
                        pending=[Gio.File.new_for_uri(base)]
                        while pending:
                            folder=pending.pop()
                            enum=folder.enumerate_children('standard::name,standard::type,time::modified',Gio.FileQueryInfoFlags.NONE,None)
                            while info:=enum.next_file(None):
                                child=folder.get_child(info.get_name());path=child.get_uri();isdir=info.get_file_type()==Gio.FileType.DIRECTORY
                                name=info.get_name();mtime=info.get_modification_date_time();stamp=mtime.to_unix() if mtime else 0
                                ext=FOLDER_EXT if isdir else Path(name).suffix.lower().lstrip('.')
                                conn.execute('INSERT INTO files(root,path,name,norm,ext,modified) VALUES(?,?,?,?,?,?) ON CONFLICT(root,path) DO UPDATE SET name=excluded.name,norm=excluded.norm,ext=excluded.ext,modified=excluded.modified',(base,path,name,normalize(name),ext,stamp))
                                conn.execute('INSERT OR IGNORE INTO seen(path) VALUES(?)',(path,));count+=1
                                if isdir:pending.append(child)
                                if progress and count%200==0:progress(done,len(roots),base,path,count)
                            enum.close(None)
                    else:
                        for current,dirs,files in os.walk(base):
                            dirs[:]=[d for d in dirs if not d.startswith('.')]
                            for name,isdir in [(d,True) for d in dirs]+[(f,False) for f in files]:
                                path=os.path.join(current,name)
                                try:stamp=os.path.getmtime(path)
                                except OSError:continue
                                ext=FOLDER_EXT if isdir else Path(name).suffix.lower().lstrip('.')
                                conn.execute('INSERT INTO files(root,path,name,norm,ext,modified) VALUES(?,?,?,?,?,?) ON CONFLICT(root,path) DO UPDATE SET name=excluded.name,norm=excluded.norm,ext=excluded.ext,modified=excluded.modified',(base,path,name,normalize(name),ext,stamp))
                                conn.execute('INSERT OR IGNORE INTO seen(path) VALUES(?)',(path,));count+=1
                            if progress and count%200==0:progress(done,len(roots),base,current,count)
                    conn.execute('DELETE FROM files WHERE root=? AND path NOT IN (SELECT path FROM seen)',(base,))
                    status='Actualizado'
                except (OSError,Exception) as exc:
                    status='Parcial: '+str(exc)[:160]
                conn.execute('INSERT INTO scans(root,updated,status) VALUES(?,?,?) ON CONFLICT(root) DO UPDATE SET updated=excluded.updated,status=excluded.status',(base,time.time(),status))
                conn.commit();done+=1
                if progress:progress(done,len(roots),base,base,count)
    return True
