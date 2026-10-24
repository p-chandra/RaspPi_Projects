"""Copy immutable photos and a consistent SQLite snapshot to the backup USB.

Never deletes files at the destination. Missing drives cause a failure, not an SD-card copy.
"""
import datetime
from contextlib import closing
import fcntl
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from storage import metadata_path


def main():
    primary = Path(os.environ["PHOTO_MOUNT"]).resolve()
    backup = Path(os.environ["PHOTO_BACKUP_MOUNT"]).resolve()
    if not primary.is_mount() or not backup.is_mount() or primary == backup:
        raise RuntimeError("Both distinct USB drives must be mounted before backup")
    source = Path(os.environ["PHOTO_DATA"]).resolve()
    source_meta = metadata_path(source)
    if not source.is_relative_to(primary) or not source_meta.is_relative_to(primary):
        raise RuntimeError("PHOTO_DATA and PHOTO_META must be on the primary USB drive")
    target = backup / "Photos"
    target.mkdir(parents=True, exist_ok=True)
    target_meta = backup / ".pi-photos"
    target_meta.mkdir(exist_ok=True)
    with open(source_meta / "backup.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd, snapshot = tempfile.mkstemp(prefix="catalog-", suffix=".sqlite3", dir=target)
        os.close(fd)
        try:
            with closing(sqlite3.connect(f"file:{source_meta / 'photos.sqlite3'}?mode=ro", uri=True)) as src, closing(sqlite3.connect(snapshot)) as dest:
                src.backup(dest)
            subprocess.run(["rsync", "-rlt", "--modify-window=2", "--exclude=.pi-photos/photos.sqlite3*",
                            "--exclude=.pi-photos/incoming/", "--exclude=.pi-photos/*.lock", "--exclude=PiPhotosBackup/",
                            str(source) + "/", str(target) + "/"], check=True)
            subprocess.run(["rsync", "-rlt", "--modify-window=2", "--exclude=photos.sqlite3*",
                            "--exclude=incoming/", "--exclude=*.lock", str(source_meta) + "/", str(target_meta) + "/"], check=True)
            for folder in ("Videos", "Surveillance"):
                media = primary / folder
                if media.is_symlink():
                    raise RuntimeError(f"Refusing linked media folder: {media}")
                if media.is_dir():
                    subprocess.run(["rsync", "-rlt", "--modify-window=2",
                                    str(media), str(backup) + "/"], check=True)
            if not primary.is_mount() or not backup.is_mount():
                raise RuntimeError("USB disconnected during backup")
            with closing(sqlite3.connect(snapshot)) as catalog:
                for (relative,) in catalog.execute("SELECT path FROM photos"):
                    if not (target / relative).is_file():
                        raise RuntimeError("Backup incomplete: a cataloged photo is missing")
            os.replace(snapshot, target_meta / "photos.sqlite3")
            (target_meta / "last-backup.txt").write_text(datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n")
            print("Photo backup completed")
        finally:
            Path(snapshot).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
