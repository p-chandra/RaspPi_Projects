"""Move nested photographs to Photos without overwrites; preserve gallery IDs."""
import argparse
from contextlib import closing
import ctypes
import datetime
import errno
import fcntl
import json
import os
from pathlib import Path
import sqlite3
from storage import metadata_path

EXTENSIONS = {'.jpg', '.jpeg', '.heic', '.heif', '.png', '.webp', '.gif', '.avif', '.dng', '.tif', '.tiff', '.bmp', '.cr2', '.cr3', '.nef', '.arw', '.orf', '.rw2'}


def move_exclusive(source, target):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(code, 'Destination exists')
        raise OSError(code, os.strerror(code))


def flatten(root, apply=False):
    root = Path(root).resolve(strict=True)
    meta = metadata_path(root)
    if not (meta / 'photos.sqlite3').is_file():
        raise RuntimeError('Expected an existing Pi Photos library')
    with (meta / 'catalog.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sources, directories = [], []
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = [n for n in folders if not n.startswith('.') and n != 'PiPhotosBackup' and not (Path(directory) / n).is_symlink()]
            if Path(directory) == root:
                continue
            directories.append(Path(directory))
            for name in files:
                p = Path(directory) / name
                if p.suffix.lower() in EXTENSIONS and p.is_file() and not p.is_symlink():
                    sources.append(p)
        reserved = {p.name.casefold() for p in root.iterdir()}
        plan, renamed = [], 0
        for source in sorted(sources):
            name, counter = source.name, 1
            while name.casefold() in reserved:
                counter += 1
                name = f'{source.stem}__{counter}{source.suffix}'
            renamed += name != source.name
            reserved.add(name.casefold())
            plan.append({'from': str(source.relative_to(root)), 'to': name, 'bytes': source.stat().st_size})
        summary = {'photos': len(plan), 'collision_renames': renamed, 'bytes': sum(p['bytes'] for p in plan)}
        if not apply or not plan:
            return summary
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        manifest = meta / ('flatten-' + stamp + '.jsonl')
        with manifest.open('x') as out:
            for entry in plan:
                out.write(json.dumps(entry, ensure_ascii=False) + '\n')
            out.flush()
            os.fsync(out.fileno())
        with closing(sqlite3.connect(meta / 'photos.sqlite3', timeout=30)) as con:
            with closing(sqlite3.connect(meta / ('pre-flatten-' + stamp + '.sqlite3'))) as backup:
                con.backup(backup)
            try:
                for index, entry in enumerate(plan, 1):
                    source, target = root / entry['from'], root / entry['to']
                    move_exclusive(source, target)
                    stat = target.stat()
                    con.execute('UPDATE photos SET path=?,name=?,bytes=?,mtime=? WHERE path=?',
                                (entry['to'], target.name, stat.st_size, stat.st_mtime_ns, entry['from']))
                    if index % 100 == 0:
                        con.commit()
                        print('Moved', index, 'of', len(plan), flush=True)
                con.commit()
            except BaseException:
                # Retain catalog updates for successfully completed moves.
                con.commit()
                raise
        removed = 0
        for folder in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
                removed += 1
            except OSError as error:
                if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise
        missing = [entry for entry in plan if not (root / entry['to']).is_file() or (root / entry['to']).stat().st_size != entry['bytes']]
        if missing:
            raise RuntimeError('Post-move file verification failed')
        summary.update(empty_folders_removed=removed, manifest=str(manifest))
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(flatten(args.folder, args.apply)))
