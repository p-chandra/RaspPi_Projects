"""Import existing photos into the library, leaving source files untouched."""
import argparse
import http.client
import os
from pathlib import Path
import urllib.parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--url", default="http://100.117.156.54:8090")
    args = parser.parse_args()
    token = os.environ["PHOTO_TOKEN"]
    url = urllib.parse.urlparse(args.url)
    connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    failures = 0
    for path in sorted(args.folder.rglob("*")):
        if path.is_symlink() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".avif"}:
            continue
        if not path.is_file():
            continue
        connection = connection_type(url.hostname, url.port, timeout=180)
        try:
            connection.putrequest("POST", "/api/photos")
            connection.putheader("Authorization", "Bearer " + token)
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(path.stat().st_size))
            connection.putheader("X-Photo-Name", urllib.parse.quote(path.name))
            connection.endheaders()
            with path.open("rb") as photo:
                while chunk := photo.read(256 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            body = response.read()
            if response.status not in (200, 201):
                raise RuntimeError(f"HTTP {response.status}: {body.decode(errors='replace')}")
            print("Imported" if response.status == 201 else "Already saved", path.name)
        except Exception as error:
            failures += 1
            print("Failed", path.name, str(error))
        finally:
            connection.close()
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
