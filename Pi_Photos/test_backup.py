import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import io
from server import create_app
from backup import main as backup


class BackupTests(unittest.TestCase):
    def test_consistent_backup_and_preservation_of_existing_files(self):
        with tempfile.TemporaryDirectory() as primary, tempfile.TemporaryDirectory() as secondary:
            source = Path(primary) / "Photos"
            destination = Path(secondary) / "Photos"
            destination.mkdir()
            untouched = destination / "preexisting.txt"
            untouched.write_text("keep this file")
            app = create_app(source, "test-secret-" * 5, auto_index=False)
            image = io.BytesIO()
            Image.new("RGB", (40, 30), "blue").save(image, "JPEG")
            result = app.test_client().post("/api/photos", data=image.getvalue(), headers={
                "Authorization": "Bearer " + "test-secret-" * 5, "X-Photo-Name": "Test.jpg"})
            self.assertEqual(result.status_code, 201)
            # Exercise the new sibling-metadata layout.
            (source / ".pi-photos").rename(Path(primary) / ".pi-photos")
            env = {"PHOTO_MOUNT": primary, "PHOTO_DATA": str(source), "PHOTO_BACKUP_MOUNT": secondary}
            with patch.dict(os.environ, env), patch("backup.Path.is_mount", return_value=True):
                backup()
                # An existing backup-only file must also survive subsequent backups.
                extra = destination / "PiPhotosBackup" / "keep.txt"
                extra.write_text("preserve")
                backup()
            target = destination / "PiPhotosBackup"
            self.assertEqual((target / "Test.jpg").read_bytes(), image.getvalue())
            self.assertEqual(untouched.read_text(), "keep this file")
            self.assertEqual(extra.read_text(), "preserve")
            self.assertTrue((target / "last-backup.txt").is_file())
            with closing(sqlite3.connect(target / ".pi-photos" / "photos.sqlite3")) as catalog:
                self.assertEqual(catalog.execute("SELECT path FROM photos").fetchone()[0], "Test.jpg")

    def test_missing_mount_refuses_backup(self):
        env = {"PHOTO_MOUNT": "/missing/primary", "PHOTO_DATA": "/missing/primary/Photos", "PHOTO_BACKUP_MOUNT": "/missing/backup"}
        with patch.dict(os.environ, env), patch("backup.Path.is_mount", return_value=False):
            with self.assertRaises(RuntimeError):
                backup()
