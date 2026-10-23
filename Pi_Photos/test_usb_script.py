"""Exercise USB ejection safeguards with mocked OS commands; never unmount live drives."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("usb-photos.sh")


class UsbScriptTests(unittest.TestCase):
    def unmount_function(self):
        source = SCRIPT.read_text().split("<<'PY' || return $?\n", 1)[1].split("\nPY\n", 1)[0]
        source = source.split("\ntry:\n    unmount_drive", 1)[0]
        namespace = {}
        exec(compile(source, "usb-unmount", "exec"), namespace)
        return namespace["unmount_drive"]

    def simulate(self, mounts, busy=False, other_partition=False):
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            output = ""
            code = 0
            if args[0] == "findmnt":
                output = json.dumps({"filesystems": [{"target": p} for p in mounts]})
            elif args[0] == "umount":
                code = 32 if busy else 0
            elif args[:3] == ["lsblk", "-ndo", "PKNAME"]:
                output = "sda\n"
            elif args[:2] == ["lsblk", "--json"]:
                output = json.dumps({"blockdevices": [{"name": "sda", "mountpoints": [None], "children": [
                    {"name": "sda1", "mountpoints": ["/media/other" if other_partition else None]}]}]})
            return subprocess.CompletedProcess(args, code, output, "")

        return command, calls

    def test_unmounts_both_server_and_desktop_with_spaces(self):
        command, calls = self.simulate(["/srv/pi-photos-primary", "/media/p-c/Photo Drive"])
        with patch("subprocess.run", side_effect=command):
            self.unmount_function()("/dev/sda1")
        self.assertIn(["umount", "--", "/media/p-c/Photo Drive"], calls)
        self.assertIn(["umount", "--", "/srv/pi-photos-primary"], calls)
        self.assertFalse(any("-f" in call or "-l" in call for call in calls))

    def test_busy_drive_does_not_report_success(self):
        command, calls = self.simulate(["/srv/pi-photos-primary"], busy=True)
        with patch("subprocess.run", side_effect=command), self.assertRaisesRegex(RuntimeError, "Do not unplug"):
            self.unmount_function()("/dev/sda1")

    def test_other_mounted_partition_blocks_safe_removal(self):
        command, _ = self.simulate([], other_partition=True)
        with patch("subprocess.run", side_effect=command), self.assertRaisesRegex(RuntimeError, "Another filesystem"):
            self.unmount_function()("/dev/sda1")

    def test_system_mount_refused(self):
        command, calls = self.simulate(["/"])
        with patch("subprocess.run", side_effect=command), self.assertRaisesRegex(RuntimeError, "system filesystem"):
            self.unmount_function()("/dev/sda1")
        self.assertFalse(any(call[0] == "umount" for call in calls))

    def test_invalid_flag_fails_before_sudo(self):
        result = subprocess.run(["bash", str(SCRIPT), "-invalid"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)

    def test_connect_and_disconnect_service_order(self):
        # Source functions so this test needs neither root nor real systemd access.
        harness = '''
source "$1"
blkid() { if [[ "$1" == -U ]]; then echo /dev/sda1; else echo exfat; fi; }
mountpoint() { return 0; }
findmnt() { echo EA6C-39A4; }
systemctl() { echo "systemctl $*"; }
sync() { echo sync; }
python3() { cat >/dev/null; echo unmount-checked; }
connect_usb
disconnect_usb
'''
        result = subprocess.run(["bash", "-c", harness, "usb-test", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("systemctl start pi-photos-backup.timer", lines)
        expected = ["systemctl stop pi-photos-backup.timer", "systemctl stop pi-photos-backup.service",
                    "systemctl stop pi-photos.service", "sync", "unmount-checked"]
        positions = [lines.index(item) for item in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Disconnected safely.", result.stdout)
