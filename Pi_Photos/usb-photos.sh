#!/usr/bin/env bash
# Manage the PhotoDrive USB and its Pi Photos services.
set -euo pipefail

PHOTO_UUID=EA6C-39A4
PHOTO_PROJECT=/home/p-c/pi-photos
PHOTO_MOUNT=/srv/pi-photos-primary

usage() {
    cat <<'EOF'
Usage: ./usb-photos.sh -connect | -disconnect

-connect     Mount PhotoDrive and start Pi Photos.
-disconnect  Stop photo/backup services, flush writes, and unmount PhotoDrive.

Administrator access is requested through sudo when needed.
Disconnect never forces an unmount or terminates unrelated applications.
EOF
}

drive_device() {
    local device
    if ! device="$(blkid -U "$PHOTO_UUID")" || [[ -z "$device" ]]; then
        return 1
    fi
    printf '%s\n' "$device"
}

connect_usb() {
    local device
    if ! device="$(drive_device)"; then
        echo 'PhotoDrive is not detected. Plug it into the Raspberry Pi and try again.' >&2
        return 1
    fi
    if [[ "$(blkid -s TYPE -o value "$device")" != exfat ]]; then
        echo 'The expected PhotoDrive filesystem was not found; no changes made.' >&2
        return 1
    fi
    if mountpoint -q "$PHOTO_MOUNT"; then
        if [[ "$(findmnt -rn -M "$PHOTO_MOUNT" -o UUID)" != "$PHOTO_UUID" ]]; then
            echo 'A different drive is mounted at the photo location; no changes made.' >&2
            return 1
        fi
    fi
    # This also configures the stable UUID mount on first use.
    if ! mountpoint -q "$PHOTO_MOUNT" || ! systemctl is-active --quiet pi-photos.service; then
        bash "$PHOTO_PROJECT/connect-primary.sh"
    else
        echo 'PhotoDrive is already mounted and Pi Photos is running.'
    fi
    if systemctl is-enabled --quiet pi-photos-backup.timer; then
        systemctl start pi-photos-backup.timer
    fi
    echo 'Connected. Pi Photos is available at http://100.117.156.54:8090'
}

disconnect_usb() {
    local device
    device="$(drive_device)" || device=''
    # Prevent a scheduled backup from starting while the drive is being ejected.
    systemctl stop pi-photos-backup.timer || return $?
    systemctl stop pi-photos-backup.service || return $?
    systemctl stop pi-photos.service || return $?
    if [[ -z "$device" ]]; then
        if mountpoint -q "$PHOTO_MOUNT"; then
            echo 'The drive cannot be identified but a filesystem is still mounted. Safe removal is NOT confirmed.' >&2
            return 1
        fi
        echo 'PhotoDrive is not connected. Photo and backup services are stopped.'
        return 0
    fi
    sync
    # Handle both the server mount and any desktop-created mount, including spaces.
    python3 - "$device" <<'PY' || return $?
import json
import subprocess
import sys


def unmount_drive(device):
    result = subprocess.run(['findmnt', '--json', '--list', '--source', device, '--output', 'TARGET'], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('Could not inspect USB mount locations; safe removal is NOT confirmed.')
    entries = json.loads(result.stdout).get('filesystems', []) if result.stdout.strip() else []
    targets = sorted({entry['target'] for entry in entries}, key=lambda path: (path.count('/'), len(path)), reverse=True)
    for target in targets:
        if target in {'/', '/boot', '/boot/firmware', '/home', '/usr', '/var'}:
            raise RuntimeError('Refusing to unmount a system filesystem.')
        result = subprocess.run(['umount', '--', target])
        if result.returncode:
            raise RuntimeError('USB is still mounted. Close files, file-manager windows, or terminals using it and retry -disconnect. Do not unplug it yet.')
    # Check all partitions on the physical USB before declaring removal safe.
    parent = subprocess.run(['lsblk', '-ndo', 'PKNAME', device], capture_output=True, text=True, check=True).stdout.strip()
    disk = '/dev/' + parent if parent else device
    result = subprocess.run(['lsblk', '--json', '--output', 'NAME,MOUNTPOINTS', disk], capture_output=True, text=True, check=True)
    pending = list(json.loads(result.stdout).get('blockdevices', []))
    while pending:
        item = pending.pop()
        if any(item.get('mountpoints') or []):
            raise RuntimeError('Another filesystem on this USB remains mounted. Safe removal is NOT confirmed.')
        pending.extend(item.get('children', []))


try:
    unmount_drive(sys.argv[1])
except (RuntimeError, subprocess.SubprocessError, ValueError, KeyError) as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
PY
    echo 'Disconnected safely. You can now unplug PhotoDrive.'
    echo 'After plugging it back in, run: ./usb-photos.sh -connect'
}

main() {
    if [[ $# -ne 1 ]]; then usage >&2; return 2; fi
    case "$1" in
        -h|--help) usage; return 0 ;;
        -connect|-disconnect) ;;
        *) usage >&2; return 2 ;;
    esac
    if [[ "$EUID" -ne 0 ]]; then
        local script
        script="$(readlink -f -- "${BASH_SOURCE[0]}")"
        exec sudo -- bash "$script" "$@"
    fi
    # Serialize connect/disconnect operations. /run is writable only by root.
    exec 9>/run/pi-photos-usb.lock
    if ! flock -n 9; then
        echo 'Another USB operation is running. Wait for it to finish and retry.' >&2
        return 1
    fi
    case "$1" in
        -connect) connect_usb ;;
        -disconnect) disconnect_usb ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
