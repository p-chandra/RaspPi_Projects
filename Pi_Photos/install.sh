#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_DIR="$PWD"
PHOTO_USER="$(id -un)"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
if [[ ! -f .env ]]; then
    umask 077
    PHOTO_NEW_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
    cat > .env <<EOF
PHOTO_TOKEN=$PHOTO_NEW_TOKEN
PHOTO_MOUNT=/srv/pi-photos-primary
PHOTO_DATA=/srv/pi-photos-primary/Photos
PHOTO_META=/srv/pi-photos-primary/.pi-photos
PHOTO_BACKUP_MOUNT=/srv/pi-photos-backup
PHOTO_BIND=100.117.156.54:8090
EOF
fi
chmod 600 .env
sudo mkdir -p /srv/pi-photos-primary /srv/pi-photos-backup
sudo tee /etc/systemd/system/pi-photos.service >/dev/null <<EOF
[Unit]
Description=Private Pi Photos server
After=network-online.target tailscaled.service
Wants=network-online.target
RequiresMountsFor=/srv/pi-photos-primary
ConditionPathIsMountPoint=/srv/pi-photos-primary

[Service]
Type=simple
User=$PHOTO_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/.venv/bin/gunicorn --bind \${PHOTO_BIND} --workers 1 --threads 2 --timeout 180 --access-logfile - wsgi:app
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF
sudo tee /etc/systemd/system/pi-photos-backup.service >/dev/null <<EOF
[Unit]
Description=Back up Pi Photos to second USB drive
RequiresMountsFor=/srv/pi-photos-primary /srv/pi-photos-backup
ConditionPathIsMountPoint=/srv/pi-photos-primary
ConditionPathIsMountPoint=/srv/pi-photos-backup

[Service]
Type=oneshot
User=$PHOTO_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/.venv/bin/python backup.py
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
EOF
sudo tee /etc/systemd/system/pi-photos-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Weekly Pi Photos backup
[Timer]
OnCalendar=Sun *-*-* 03:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF
sudo chmod 644 /etc/systemd/system/pi-photos.service /etc/systemd/system/pi-photos-backup.service /etc/systemd/system/pi-photos-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable pi-photos.service
echo 'Installed. Configure USB mounts, then run: sudo systemctl start pi-photos'
echo 'For a second-drive backup: sudo systemctl enable --now pi-photos-backup.timer'
