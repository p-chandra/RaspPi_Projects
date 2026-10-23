#!/usr/bin/env bash
# Configure the inspected PhotoDrive USB without formatting or moving files.
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
    echo 'Run: sudo bash /home/p-c/pi-photos/connect-primary.sh' >&2
    exit 1
fi
PHOTO_UUID=EA6C-39A4
PHOTO_TARGET=/srv/pi-photos-primary
PHOTO_DEVICE="$(blkid -U "$PHOTO_UUID")"
if [[ -z "$PHOTO_DEVICE" || "$(blkid -s TYPE -o value "$PHOTO_DEVICE")" != exfat ]]; then
    echo 'The expected PhotoDrive exFAT USB drive is not connected.' >&2
    exit 1
fi
if mountpoint -q "$PHOTO_TARGET" && [[ "$(findmnt -rn -M "$PHOTO_TARGET" -o UUID)" != "$PHOTO_UUID" ]]; then
    echo 'Another drive is still mounted at the primary location; no changes made.' >&2
    exit 1
fi
python3 - <<'PY'
from pathlib import Path
import datetime
import shutil
fstab = Path('/etc/fstab')
text = fstab.read_text()
entries = [line.split() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
existing = [parts for parts in entries if len(parts) > 1 and parts[1] == '/srv/pi-photos-primary']
if len(existing) > 1 or (existing and existing[0][0] not in {'UUID=6AB7-83CD', 'UUID=EA6C-39A4'}):
    raise SystemExit('A different primary USB is already configured; no changes made.')
entry = 'UUID=EA6C-39A4 /srv/pi-photos-primary exfat defaults,nofail,uid=1000,gid=1000,fmask=0022,dmask=0022,nodev,nosuid,x-systemd.device-timeout=10s 0 0'
if not existing or existing[0][0] != 'UUID=EA6C-39A4':
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    shutil.copy2(fstab, '/etc/fstab.pi-photos-' + stamp + '.bak')
    if existing:
        lines = []
        for line in text.splitlines():
            parts = line.split()
            if parts and not line.lstrip().startswith('#') and len(parts) > 1 and parts[1] == '/srv/pi-photos-primary':
                lines.append(entry)
            else:
                lines.append(line.replace('# Pi Photos primary USB (Personal)', '# Pi Photos primary USB (PhotoDrive)'))
        fstab.write_text('\n'.join(lines) + '\n')
    else:
        with fstab.open('a') as out:
            out.write('\n# Pi Photos primary USB (PhotoDrive)\n' + entry + '\n')
    print('Configured PhotoDrive by UUID; previous fstab backed up.')
PY
mkdir -p "$PHOTO_TARGET"
systemctl daemon-reload
if ! mountpoint -q "$PHOTO_TARGET"; then
    mount "$PHOTO_TARGET"
fi
if [[ "$(findmnt -rn -M "$PHOTO_TARGET" -o UUID)" != "$PHOTO_UUID" ]]; then
    echo 'Unexpected drive at primary mount; server was not started.' >&2
    exit 1
fi
runuser -u p-c -- test -d "$PHOTO_TARGET/Photos"
runuser -u p-c -- test -w "$PHOTO_TARGET/Photos"
systemctl restart pi-photos
curl --fail --silent --show-error --retry 5 --retry-connrefused --retry-delay 1 http://100.117.156.54:8090/health
echo
systemctl --no-pager --full status pi-photos
