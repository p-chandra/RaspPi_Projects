import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from server import create_app


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name, "test-key-" * 8, auto_index=False)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer " + "test-key-" * 8, "X-Photo-Name": "holiday%20photo.jpg"}
        out = io.BytesIO()
        Image.new("RGB", (120, 80), "green").save(out, "JPEG")
        self.photo = out.getvalue()

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_original_thumbnail_duplicate_and_restart(self):
        result = self.client.post("/api/photos", data=self.photo, headers=self.headers)
        self.assertEqual(result.status_code, 201)
        photo = result.json["photo"]
        self.assertEqual(photo["name"], "holiday photo.jpg")
        self.assertEqual(photo["hash"], hashlib.sha256(self.photo).hexdigest())
        original = self.client.get(f'/api/photos/{photo["id"]}/original', headers=self.headers)
        self.assertEqual(original.data, self.photo)
        original.close()
        thumb = self.client.get(f'/api/photos/{photo["id"]}/thumbnail', headers=self.headers)
        self.assertEqual(Image.open(io.BytesIO(thumb.data)).size, (120, 80))
        thumb.close()
        duplicate = self.client.post("/api/photos", data=self.photo, headers=self.headers)
        self.assertTrue(duplicate.json["duplicate"])
        restarted = create_app(self.temp.name, "test-key-" * 8, auto_index=False).test_client()
        self.assertEqual(restarted.get("/api/photos", headers=self.headers).json["total"], 1)

    def test_access_and_bad_inputs(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        for method, path in [("get", "/api/photos"), ("post", "/api/photos"), ("get", "/api/photos/1/original")]:
            self.assertEqual(getattr(self.client, method)(path).status_code, 401)
        self.assertEqual(self.client.post("/api/photos", data=b"not a photo", headers=self.headers).status_code, 415)
        self.assertEqual(self.client.get("/api/photos?limit=oops", headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get("/api/photos/1/original", headers=self.headers).status_code, 404)
        self.app.config["MAX_CONTENT_LENGTH"] = 10
        self.assertEqual(self.client.post("/api/photos", data=self.photo, headers=self.headers).status_code, 413)
        self.assertFalse(list((Path(self.temp.name) / ".pi-photos" / "incoming").iterdir()))

    def test_existing_photos_index_without_copy_and_collisions_preserve_originals(self):
        root = Path(self.temp.name)
        existing = root / "holiday photo.jpg"
        existing.write_bytes(self.photo)
        folder = root / "Family"
        folder.mkdir()
        out = io.BytesIO()
        Image.new("RGB", (20, 10), "purple").save(out, "PNG")
        nested = folder / "existing.png"
        nested.write_bytes(out.getvalue())
        self.app.extensions["scan_existing"]()
        result = self.client.get("/api/photos", headers=self.headers).json
        self.assertEqual(result["total"], 2)
        self.assertEqual(existing.read_bytes(), self.photo)
        self.assertEqual(nested.read_bytes(), out.getvalue())
        self.assertEqual(len(list(root.rglob("*.jpg"))), 3)  # original and two hidden thumbnails
        duplicate = self.client.post("/api/photos", data=self.photo, headers=self.headers)
        self.assertTrue(duplicate.json["duplicate"])
        out = io.BytesIO()
        Image.new("RGB", (30, 20), "orange").save(out, "JPEG")
        collision = self.client.post("/api/photos", data=out.getvalue(), headers=self.headers)
        self.assertEqual(collision.status_code, 201)
        self.assertNotEqual(collision.json["photo"]["name"], "holiday photo.jpg")
        self.assertEqual(existing.read_bytes(), self.photo)
        nested.unlink()
        self.app.extensions["scan_existing"]()
        self.assertEqual(self.client.get("/api/photos", headers=self.headers).json["total"], 2)

    def test_pagination_and_concurrent_duplicate(self):
        def upload(_):
            with self.app.test_client() as c:
                return c.post("/api/photos", data=self.photo, headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=4) as executor:
            codes = list(executor.map(upload, range(4)))
        self.assertEqual(codes.count(201), 1)
        for color in ["red", "blue"]:
            out = io.BytesIO()
            Image.new("RGB", (20, 10), color).save(out, "PNG")
            self.assertEqual(self.client.post("/api/photos", data=out.getvalue(), headers=self.headers).status_code, 201)
        first = self.client.get("/api/photos?limit=2", headers=self.headers).json
        second = self.client.get(f'/api/photos?before={first["next_before"]}&limit=2', headers=self.headers).json
        self.assertEqual(len(first["photos"]), 2)
        self.assertEqual(len(second["photos"]), 1)
        self.assertIsNone(second["next_before"])
        self.assertEqual(first["total"], 3)

    def test_missing_usb_refuses_startup(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"PHOTO_MOUNT": "/a/nonexistent/usb"}):
            with self.assertRaises(RuntimeError):
                create_app(self.temp.name, "test-key-" * 8)

    def test_metadata_moved_outside_photos_preserves_gallery(self):
        from unittest.mock import patch
        original = self.client.post("/api/photos", data=self.photo, headers=self.headers).json["photo"]
        with tempfile.TemporaryDirectory() as external:
            moved = Path(external) / ".pi-photos"
            (Path(self.temp.name) / ".pi-photos").rename(moved)
            with patch.dict(os.environ, {"PHOTO_META": str(moved)}):
                migrated = create_app(self.temp.name, "test-key-" * 8, auto_index=False).test_client()
                library = migrated.get("/api/photos", headers=self.headers).json
                self.assertEqual(library["photos"][0]["id"], original["id"])
                for kind in ("original", "thumbnail"):
                    response = migrated.get(f'/api/photos/{original["id"]}/{kind}', headers=self.headers)
                    self.assertEqual(response.status_code, 200)
                    response.close()
                self.assertFalse(any(p.is_dir() for p in Path(self.temp.name).iterdir()))

    def test_newest_capture_date_fallback_ties_and_pagination(self):
        from datetime import datetime, timezone
        root = Path(self.temp.name)
        fixtures = [
            ('old-capture.jpg', '2020:01:01 12:00:00', 2030, 'red'),
            ('new-capture.jpg', '2024:01:01 12:00:00', 2010, 'green'),
            ('no-exif.jpg', None, 2023, 'blue'),
            ('same-capture.jpg', '2024:01:01 12:00:00', 2011, 'orange'),
            ('invalid-date.jpg', 'not a date', 2022, 'purple'),
        ]
        snapshots = {}
        for name, taken, modified_year, color in fixtures:
            path = root / name
            exif = Image.Exif()
            if taken:
                exif[0x8769] = {0x9003: taken, 0x9011: '+00:00'}
            Image.new('RGB', (30, 20), color).save(path, 'JPEG', exif=exif)
            modified_ns = int(datetime(modified_year, 1, 1, tzinfo=timezone.utc).timestamp()) * 1_000_000_000
            os.utime(path, ns=(modified_ns, modified_ns))
            snapshots[name] = (path.read_bytes(), path.stat().st_mtime_ns)
        self.app.extensions['scan_existing']()
        all_photos = []
        before = None
        while True:
            url = '/api/photos?limit=2' + (f'&before={before}' if before is not None else '')
            result = self.client.get(url, headers=self.headers).json
            all_photos.extend(result['photos'])
            before = result['next_before']
            if before is None:
                break
        self.assertEqual(len({p['id'] for p in all_photos}), 5)
        self.assertEqual({p['name'] for p in all_photos[:2]}, {'same-capture.jpg', 'new-capture.jpg'})
        self.assertEqual([p['name'] for p in all_photos[2:]], ['no-exif.jpg', 'invalid-date.jpg', 'old-capture.jpg'])
        keys = [(p['taken_ns'] if p['taken_ns'] is not None else p['mtime'], p['id']) for p in all_photos]
        self.assertEqual(keys, sorted(keys, reverse=True))
        for name, snapshot in snapshots.items():
            path = root / name
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshot)
        for cursor in ('-1', '999999999999999999999999999999'):
            self.assertEqual(self.client.get('/api/photos?before=' + cursor, headers=self.headers).status_code, 400)

    def test_backfill_capture_dates_preserves_existing_ids(self):
        from contextlib import closing
        import sqlite3
        path = Path(self.temp.name) / 'existing.jpg'
        exif = Image.Exif()
        exif[0x8769] = {0x9003: '2021:01:01 12:00:00', 0x9011: '+02:00', 0x9291: '125'}
        Image.new('RGB', (30, 20), 'yellow').save(path, 'JPEG', exif=exif)
        self.app.extensions['scan_existing']()
        before = self.client.get('/api/photos', headers=self.headers).json['photos'][0]
        with closing(sqlite3.connect(Path(self.temp.name) / '.pi-photos' / 'photos.sqlite3')) as con:
            con.execute('UPDATE photos SET taken_ns=NULL,date_checked=0')
            con.commit()
        self.app.extensions['scan_existing']()
        after = self.client.get('/api/photos', headers=self.headers).json['photos'][0]
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['taken_ns'], before['taken_ns'])
        self.assertEqual(after['taken_ns'], 1609495200125000000)


if __name__ == "__main__":
    unittest.main()
