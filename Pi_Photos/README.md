# Pi Photos

Private photo storage for the companion [Pi Photos Android app](../../Android_Apps/PiPhotos/README.md). The Pi is `p-c@100.117.156.54`; the API binds only to its Tailscale address on port **8090**. Tailscale must stay connected on the phone and Pi. No router port forwarding is needed.

Original photo bytes are preserved. The service creates EXIF-oriented thumbnails, stores an SQLite catalog, detects duplicates by SHA-256, and requires a bearer access key. JPEG, PNG, WebP, GIF, HEIC/HEIF and AVIF are accepted, up to 100 MiB and 60 megapixels each. Animated images use the first frame in thumbnails. Videos are outside this app's scope.

## USB storage

The gallery shows newest photos first using EXIF DateTimeOriginal (or DateTimeDigitized) when readable, and filesystem modified time otherwise. Embedded timezone offsets and fractional seconds are respected; camera dates without an offset use the Pi's local timezone. Equal dates have a stable catalog-ID tie-breaker. The existing Android app's numeric cursor remains supported when loading subsequent pages. Capture dates for older catalog entries are filled during background scans, so order can settle as dates and additional photos are discovered. Sorting never rewrites originals or changes their modified dates.

For daily use, `/home/p-c/usb-photos.sh` manages the inspected PhotoDrive USB (UUID `EA6C-39A4`):

```sh
~/usb-photos.sh -connect
~/usb-photos.sh -disconnect
```

The script asks for sudo when needed. Connect configures/mounts the drive, starts the photo server, and resumes the weekly backup timer if enabled. Disconnect stops the backup timer, backup service and photo server, flushes pending writes, and unmounts both the server and desktop mount locations. Unplug only after it prints **Disconnected safely**. A busy file or another mounted partition prevents that confirmation; close files or terminals using the drive and retry. Nothing is formatted, moved or deleted. Other Pi services continue running unless they are using the USB; an application holding it open must release it before safe removal.

Use one drive for the library and the second for a backup. Never format a drive as part of this installation. Inspect existing files and identify each drive by filesystem UUID with `lsblk -f`. Mount the primary at `/srv/pi-photos-primary` and backup at `/srv/pi-photos-backup`, with suitable `/etc/fstab` entries using UUIDs and `nofail`. Both mounts must be writable by `p-c`. For FAT/exFAT/NTFS, use appropriate uid/gid mount options; ext4 uses normal directory ownership. Don't recursively change permissions or ownership of existing files.

Uploads are saved as normal image files directly in `/srv/pi-photos-primary/Photos/`, preserving their filenames when available. If a name already exists with different content, a suffix is added; existing files are never overwritten. Hidden metadata and thumbnails live alongside `Photos`, at `/srv/pi-photos-primary/.pi-photos/`, so `Photos` itself has no app-created subfolders. `PHOTO_META` configures this path; older installations with metadata inside `Photos` remain supported. Existing photos in `Photos` and its subfolders are indexed in place, without copying or modifying them. Identical content appears once in the gallery.

The server checks that the primary is a mounted filesystem at startup and before handling API calls. The service also has a mount condition. An absent drive prevents service startup; a disconnected drive produces a storage error. Do not unplug drives during use. After reconnecting, mount them and run `sudo systemctl restart pi-photos`.

## Install on the Pi

For the inspected primary drive **PhotoDrive** (exFAT UUID `EA6C-39A4`), run `sudo bash /home/p-c/pi-photos/connect-primary.sh` on the Pi. This backs up `/etc/fstab`, replaces the previous Personal USB entry when present, configures a stable UUID mount at `/srv/pi-photos-primary`, checks the existing `Photos` folder is writable by `p-c`, and starts the server. It does not format the drive or move photos. The second USB still needs separate inspection and configuration when connected.

Copy this directory to `/home/p-c/pi-photos`, then run:

```sh
cd /home/p-c/pi-photos
bash install.sh
```

This creates a Python environment, generates a private access key in `.env` (mode 600), and installs systemd units. It does not format or mount drives. Inspect `.env` locally to retrieve the key for the Android app. Keep it private. After configuring USB mounts:

```sh
sudo systemctl start pi-photos
sudo systemctl enable --now pi-photos-backup.timer
curl http://100.117.156.54:8090/health
sudo systemctl status pi-photos
```

The service starts at boot when its primary USB mount is available. Logs: `journalctl -u pi-photos -n 50`. The access key is required for all `/api/` routes and is never accepted in URLs.

## Backups and recovery

The backup timer runs once a week, on Sundays at 03:00 in the Pi's configured local timezone. If the Pi was off at that time, systemd runs the missed backup after startup. It requires both USB mounts. It snapshots SQLite through its backup API, copies immutable originals/thumbnails with rsync, then publishes the catalog. It never deletes destination files. A completed backup is stored under `/srv/pi-photos-backup/Photos/PiPhotosBackup/` with `last-backup.txt`. Photos uploaded since the last successful weekly run are not yet backed up. The backup is kept in its own subfolder to preserve any existing files elsewhere on the second drive.

Run or inspect a backup:

```sh
sudo systemctl start pi-photos-backup
sudo systemctl status pi-photos-backup.timer
journalctl -u pi-photos-backup -n 30
```

For recovery, stop the server, restore the backup folder's photo files into an empty `Photos` folder on a mounted replacement primary drive, and restore its `.pi-photos` folder alongside `Photos` at the configured `PHOTO_META` location. Ensure `p-c` can write both, update the primary mount UUID if needed, and start the server. Keep the existing primary and backup until recovery is verified. The `.env` configuration is stored separately in `/home/p-c/pi-photos`; copy it to a safe location separately if desired.

## Photos already on a drive

Opening or refreshing the gallery triggers a background scan of `Photos` at most once per minute. Existing photos and subfolders are discovered without moving them; tap Refresh again after the initial scan finishes. Hidden folders, symbolic links and `PiPhotosBackup` folders are excluded.

To copy photos from a different folder into `Photos`, explicitly run this on the Pi after the server is running:

```sh
cd /home/p-c/pi-photos
set -a
. ./.env
set +a
.venv/bin/python import_photos.py /path/to/existing/photos
```

Import copies originals into `Photos` without modifying source files. Allow room for these copies. Re-running safely skips identical content. Do not use the managed library or backup folder as the import source. Existing photos already inside `Photos` are indexed automatically; photos outside it are not imported automatically.

## Validation

`flatten_photos.py /srv/pi-photos-primary/Photos` previews moving nested photographs directly into `Photos`; add `--apply` to perform the moves. It keeps matching filenames with numeric suffixes, updates indexed gallery paths, preserves videos and other files, and removes only empty folders. It saves a move manifest and a pre-move catalog snapshot in the configured `.pi-photos` metadata folder. Renames use Linux's no-overwrite operation on the same filesystem; photo contents are unchanged. RAW photos are moved too, although the app currently displays only its supported image formats.

```sh
.venv/bin/python -m unittest -v
```

Tests cover authentication, exact original bytes, thumbnails, restart persistence, concurrent deduplication, pagination, invalid files, upload size limits, existing-file discovery without copies, filename collision handling, and refusal to start with a missing USB mount.
