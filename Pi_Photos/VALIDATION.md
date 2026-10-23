# Validation — 2026-10-22

## Newest-first gallery — 2026-10-23

Deployed server-side ordering by embedded capture date, falling back to original filesystem modified time. Added capture-date metadata migration/backfill and kept numeric Android pagination cursors compatible with the new date order. Sixteen tests pass on the Pi, including capture-date precedence, absent/invalid metadata fallback, timezone offsets, fractional seconds, ties, pagination without duplicate rows, and unchanged original bytes/timestamps. Live three-page order was checked after deployment. A 20-file pre/post date-and-size comparison also passed. Existing photos continue being indexed in the background; capture dates are read without rewriting files. No Android update is required; Refresh reloads the order.

## USB helper — 2026-10-23

Added `usb-photos.sh -connect|-disconnect` and a home-directory launcher on the Pi. Shell syntax and six isolated lifecycle tests passed, including service stop order, dual mount paths with spaces, busy-drive failure, rejection of system filesystems, detection of another mounted partition, and argument validation. Tests mock mount operations and leave the live USB and photo service running. PhotoDrive UUID is `EA6C-39A4`; its existing Photos/Videos layout is preserved.

## USB connection follow-up

### Final flat Photos layout

Moved the remaining 62 nested `.qt` files directly into `Photos` and verified every moved file retained its size and modified timestamp. Removed the five now-empty Amazon download directories. Moved the application's `.pi-photos` metadata folder alongside `Photos` at `/srv/pi-photos-primary/.pi-photos`, added `PHOTO_META` to the private server environment, and reloaded Gunicorn. Verified that `Photos` has zero subfolders, the gallery and thumbnails work, and authenticated requests from the phone still succeed. Updated weekly backup code to include the external metadata folder; server and backup tests pass with this layout. Earlier `.heic.qt` moves and the MP4/MOV move to `Personal/Videos` also retained modified dates.

The Personal drive (exFAT UUID `6AB7-83CD`) is now mounted at `/srv/pi-photos-primary` using a UUID entry in `/etc/fstab`; the original fstab was backed up. The user ran `connect-primary.sh` with sudo. `pi-photos.service` is active. Authenticated API requests and gallery thumbnail retrieval succeeded from the Pixel's own Tailscale connection (`100.119.12.107`). The existing `Photos` tree contains 12,429 supported image files; background indexing is running and initial thumbnails are available. The second USB backup drive is still pending.

## Initial setup record

### Photo folder flattening

At the user's request, moved 12,437 nested photographs (including eight DNG files) directly into `Photos`, keeping all files. Eleven filenames received numeric suffixes to prevent collisions. Removed 48 empty folders; preserved all 331 QT, 30 MP4 and 38 MOV files in their existing folders. Verified 12,438 photos now reside directly in `Photos`, zero remain nested, and every indexed gallery path exists. Authenticated gallery listing and thumbnail retrieval passed after the move. Original paths and sizes are recorded in `.pi-photos/flatten-20261022-220947-554147.jsonl`, alongside a pre-move catalog snapshot. Background indexing of previously unindexed photos continues.

- Android debug build and lint passed with no errors. Nonblocking lint warnings concern English-only UI strings and the platform EXIF reader.
- Installed `com.pawan.piphotos` on the connected Pixel 8. Its private settings contain `http://100.117.156.54:8090` and the generated server key.
- Device instrumentation passed against a disposable Gunicorn instance on the Pi, port 8091, with all test photos and metadata under `/dev/shm` (RAM). Verified the real foreground upload service, duplicate retry, gallery listing, byte-for-byte original retrieval, and thumbnail decoding. The runner used a generated test image and restored the production address afterward. The temporary test server and test APK were removed afterward.
- Seven server/backup tests cover original preservation, authentication, thumbnails, invalid inputs, limits, persistence, concurrent duplicate uploads, pagination, existing-file indexing without copies, filename collisions, mount refusal, consistent SQLite backup, and preservation of unrelated backup-drive files.
- Server installed at `/home/p-c/pi-photos` on `p-c@100.117.156.54`.
- `pi-photos.service` is enabled but inactive because the primary USB is absent. Its mount condition was verified to prevent startup. Planned photo folder: `/srv/pi-photos-primary/Photos`.
- Weekly backup timer enabled: Sunday at 03:00 America/Los_Angeles. Planned destination: `/srv/pi-photos-backup/Photos/PiPhotosBackup`. Actual backup to the user's drives remains untested until connected.
- No USB drives were connected during setup; no formatting, drive mounting or fstab edits were performed. When the drives arrive, inspect filesystem UUIDs, contents and permissions, configure stable mounts, start the photo service, and perform the first real backup.
