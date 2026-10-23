"""Private library: original files in Photos; app metadata can live alongside it."""
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
from urllib.parse import unquote
import warnings
from flask import Flask, abort, jsonify, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from storage import metadata_path
from photo_dates import taken_time_ns
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass
Image.MAX_IMAGE_PIXELS = 60_000_000
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.avif'}

class InvalidPhoto(ValueError):
    pass

def create_app(data_dir=None, token=None, auto_index=True):
    app = Flask(__name__)
    root = Path(data_dir or os.environ.get('PHOTO_DATA', 'data/Photos')).resolve()
    meta = metadata_path(root)
    mount = os.environ.get('PHOTO_MOUNT')
    if mount and (not os.path.ismount(mount) or not root.is_relative_to(Path(mount).resolve())):
        raise RuntimeError('Photo USB drive is not mounted at PHOTO_MOUNT')
    if mount and not meta.is_relative_to(Path(mount).resolve()):
        raise RuntimeError('PHOTO_META must be on the photo USB drive')
    secret = token or os.environ.get('PHOTO_TOKEN', '')
    if len(secret) < 32:
        raise RuntimeError('PHOTO_TOKEN must contain at least 32 characters')
    for folder in (root, meta, meta / 'thumbs', meta / 'incoming'):
        folder.mkdir(parents=True, exist_ok=True)
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

    @contextmanager
    def db():
        con = sqlite3.connect(meta / 'photos.sqlite3', timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('''CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, hash TEXT UNIQUE NOT NULL,
            path TEXT UNIQUE NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL,
            bytes INTEGER NOT NULL, mtime INTEGER NOT NULL, width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            uploaded TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))''')
        columns = {r['name'] for r in con.execute('PRAGMA table_info(photos)')}
        if 'taken_ns' not in columns:
            con.execute('ALTER TABLE photos ADD COLUMN taken_ns INTEGER')
        if 'date_checked' not in columns:
            con.execute('ALTER TABLE photos ADD COLUMN date_checked INTEGER NOT NULL DEFAULT 0')
        con.execute('CREATE INDEX IF NOT EXISTS photos_newest ON photos(COALESCE(taken_ns,mtime) DESC,id DESC)')

    @contextmanager
    def catalog_lock():
        # Serialize decodes to bound Pi memory and prevent upload/scanner races.
        with (meta / 'catalog.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def safe_path(relative):
        candidate = root / relative
        resolved = candidate.resolve()
        return resolved if resolved.is_relative_to(root) and not candidate.is_symlink() else None

    def catalog(source, name=None, copy=False):
        with catalog_lock():
            digest = hashlib.sha256()
            size = 0
            with source.open('rb') as photo:
                while block := photo.read(256 * 1024):
                    size += len(block)
                    digest.update(block)
            sha = digest.hexdigest()
            with db() as con:
                if not copy:
                    con.execute('DELETE FROM photos WHERE path=? AND hash!=?', (str(source.relative_to(root)), sha))
                row = con.execute('SELECT * FROM photos WHERE hash=?', (sha,)).fetchone()
                if row:
                    old = safe_path(row['path'])
                    if old and old.is_file():
                        stat = old.stat()
                        if stat.st_size == row['bytes'] and stat.st_mtime_ns == row['mtime']:
                            return dict(row), True
                    con.execute('DELETE FROM photos WHERE id=?', (row['id'],))
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(source) as im:
                        if im.format not in {'JPEG', 'PNG', 'WEBP', 'GIF', 'HEIF', 'AVIF'}:
                            raise InvalidPhoto('Unsupported image format')
                        mime = Image.MIME.get(im.format, 'image/heic')
                        suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif', 'HEIF': '.heic', 'AVIF': '.avif'}[im.format]
                        width, height = im.size
                        taken_ns = taken_time_ns(im)
                        im.load()
                        thumb = ImageOps.exif_transpose(im)
                        thumb.thumbnail((480, 480))
                        fd, temp = tempfile.mkstemp(dir=meta / 'incoming')
                        os.close(fd)
                        try:
                            thumb.convert('RGB').save(temp, 'JPEG', quality=82)
                            os.replace(temp, meta / 'thumbs' / (sha + '.jpg'))
                        finally:
                            Path(temp).unlink(missing_ok=True)
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                raise InvalidPhoto('Invalid photo, unsupported format, or image exceeds 60 megapixels') from error
            original = source
            if copy:
                name = Path((name or 'Photo').replace('\\', '/')).name
                name = ''.join(c for c in name if ord(c) >= 32 and ord(c) != 127).lstrip('.')
                name = name.encode('utf-8')[:180].decode('utf-8', errors='ignore') or 'Photo'
                if Path(name).suffix.lower() not in EXTENSIONS:
                    name += suffix
                count = 0
                while True:
                    candidate = name if not count else f'{Path(name).stem}__{sha[:12]}_{count}{Path(name).suffix}'
                    original = root / candidate
                    try:
                        out = original.open('xb')
                        break
                    except FileExistsError:
                        count += 1
                try:
                    with out, source.open('rb') as incoming:
                        shutil.copyfileobj(incoming, out, 256 * 1024)
                        out.flush()
                        os.fsync(out.fileno())
                except BaseException:
                    original.unlink(missing_ok=True)
                    raise
            stat = original.stat()
            relative = str(original.relative_to(root))
            with db() as con:
                con.execute('DELETE FROM photos WHERE path=?', (relative,))
                con.execute('INSERT INTO photos(hash,path,name,mime,bytes,mtime,width,height,taken_ns,date_checked) VALUES(?,?,?,?,?,?,?,?,?,1)',
                            (sha, relative, original.name, mime, size, stat.st_mtime_ns, width, height, taken_ns))
                row = con.execute('SELECT * FROM photos WHERE hash=?', (sha,)).fetchone()
            return dict(row), False

    scan_lock = threading.Lock()
    scan_state = {'last': 0.0, 'running': False}
    def scan_existing():
        if not scan_lock.acquire(blocking=False):
            return
        scan_state['running'] = True
        try:
            if mount and not os.path.ismount(mount):
                return
            with db() as con:
                rows = con.execute('SELECT path,bytes,mtime,date_checked FROM photos').fetchall()
            known = {r['path']: r for r in rows}
            for directory, folders, files in os.walk(root, followlinks=False):
                folders[:] = [n for n in folders if not n.startswith('.') and n != 'PiPhotosBackup' and not (Path(directory) / n).is_symlink()]
                for name in files:
                    source = Path(directory) / name
                    if source.suffix.lower() not in EXTENSIONS or source.is_symlink():
                        continue
                    try:
                        if mount and not os.path.ismount(mount):
                            return
                        stat = source.stat()
                        relative = str(source.relative_to(root))
                        previous = known.get(relative)
                        if previous and (previous['bytes'], previous['mtime']) == (stat.st_size, stat.st_mtime_ns):
                            if not previous['date_checked']:
                                with catalog_lock():
                                    try:
                                        with Image.open(source) as im:
                                            taken_ns = taken_time_ns(im)
                                    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                                        taken_ns = None
                                    with db() as con:
                                        con.execute('UPDATE photos SET taken_ns=?,date_checked=1 WHERE path=? AND mtime=?',
                                                    (taken_ns, relative, stat.st_mtime_ns))
                            continue
                        catalog(source)
                    except (OSError, InvalidPhoto):
                        app.logger.warning('Skipped an unreadable or unsupported existing photo')
            with catalog_lock(), db() as con:
                for row in con.execute('SELECT id,path FROM photos').fetchall():
                    path = safe_path(row['path'])
                    if not path or not path.is_file():
                        con.execute('DELETE FROM photos WHERE id=?', (row['id'],))
        finally:
            scan_state['running'] = False
            scan_state['last'] = time.monotonic()
            scan_lock.release()
    app.extensions['scan_existing'] = scan_existing

    @app.before_request
    def authenticate():
        if request.path == '/health':
            return None
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode(), ('Bearer ' + secret).encode()):
            abort(401, description='Check the access key in Settings')
        if mount and not os.path.ismount(mount):
            abort(503, description='Photo USB drive is disconnected')

    @app.errorhandler(HTTPException)
    def error(e):
        return jsonify(error=e.description), e.code

    @app.get('/health')
    def health():
        ready = not mount or os.path.ismount(mount)
        return jsonify(status='ok' if ready else 'storage_offline', service='pi-photos'), 200 if ready else 503

    @app.get('/api/photos')
    def photos():
        try:
            before = int(request.args['before']) if 'before' in request.args else None
            if before is not None and not 0 <= before <= 9223372036854775807:
                raise ValueError('Invalid cursor')
            limit = min(100, max(1, int(request.args.get('limit', 60))))
        except ValueError:
            abort(400, description='Invalid page')
        if auto_index and not scan_state['running'] and time.monotonic() - scan_state['last'] > 60:
            scan_state['running'] = True
            threading.Thread(target=scan_existing, daemon=True).start()
        with db() as con:
            if before is None:
                rows = con.execute('SELECT * FROM photos ORDER BY COALESCE(taken_ns,mtime) DESC,id DESC LIMIT ?', (limit + 1,)).fetchall()
            else:
                anchor = con.execute('SELECT COALESCE(taken_ns,mtime) AS date FROM photos WHERE id=?', (before,)).fetchone()
                rows = con.execute('''SELECT * FROM photos WHERE (COALESCE(taken_ns,mtime),id) < (?,?)
                    ORDER BY COALESCE(taken_ns,mtime) DESC,id DESC LIMIT ?''', (anchor['date'], before, limit + 1)).fetchall() if anchor else []
            total = con.execute('SELECT count(*) FROM photos').fetchone()[0]
        return jsonify(photos=[dict(r) for r in rows[:limit]], total=total, indexing=scan_state['running'],
                       next_before=rows[limit-1]['id'] if len(rows) > limit else None)

    @app.post('/api/photos')
    def upload():
        fd, temp = tempfile.mkstemp(dir=meta / 'incoming')
        size = 0
        try:
            with os.fdopen(fd, 'wb') as out:
                while block := request.stream.read(256 * 1024):
                    size += len(block)
                    if size > app.config['MAX_CONTENT_LENGTH']:
                        abort(413)
                    out.write(block)
            try:
                row, duplicate = catalog(Path(temp), unquote(request.headers.get('X-Photo-Name', 'Photo')), copy=True)
            except InvalidPhoto as error:
                abort(415, description=str(error))
            return jsonify(photo=row, duplicate=duplicate), 200 if duplicate else 201
        finally:
            Path(temp).unlink(missing_ok=True)

    @app.get('/api/photos/<int:photo_id>/<kind>')
    def photo(photo_id, kind):
        if kind not in {'original', 'thumbnail'}:
            abort(404)
        with db() as con:
            row = con.execute('SELECT * FROM photos WHERE id=?', (photo_id,)).fetchone()
        if not row:
            abort(404)
        thumb = kind == 'thumbnail'
        path = meta / 'thumbs' / (row['hash'] + '.jpg') if thumb else safe_path(row['path'])
        if not path or not path.is_file():
            abort(404, description='Photo is no longer on the drive')
        response = send_file(path, mimetype='image/jpeg' if thumb else row['mime'],
                             download_name='thumbnail.jpg' if thumb else row['name'], conditional=True)
        response.headers['Cache-Control'] = 'private, max-age=86400'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    return app
