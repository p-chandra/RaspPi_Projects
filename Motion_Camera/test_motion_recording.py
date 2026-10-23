"""Motion and capture lifecycle tests; no GPIO or physical cameras are used."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

import main as recorder

MODE = {'format': 'MJPG', 'width': 1920, 'height': 1080, 'fps': 30}
CAMERAS = [('/dev/camera-a', MODE), ('/dev/camera-b', MODE)]


class MotionRecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mount = Path(self.temp.name)
        self.output = self.mount / 'Surveillance'

    def run_capture(self, factory, stop=None):
        with patch.object(Path, 'is_mount', return_value=True), \
             patch.object(recorder.shutil, 'disk_usage', return_value=SimpleNamespace(free=10**10)), \
             patch.object(recorder.subprocess, 'Popen', side_effect=factory):
            return recorder.record_motion(CAMERAS, stop or threading.Event(), self.output, self.mount)

    def process_factory(self, failed=None, stalled=None, stop=None):
        processes = []
        case = self

        class Process:
            def __init__(self, command, **kwargs):
                self.command = command
                self.index = len(processes)
                self.returncode = None
                self.terminated = False
                Path(command[-1]).write_bytes(b'fake-camera-output-' + bytes([self.index]))
                processes.append(self)
                if stop is not None and len(processes) == 2:
                    stop.set()

            def poll(self):
                # The recorder must start both cameras before waiting on either.
                case.assertEqual(len(processes), 2)
                if self.returncode is None and self.index != stalled and stop is None:
                    self.returncode = 1 if self.index == failed else 0
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = 255

            def wait(self, timeout=None):
                return self.returncode

        return Process, processes

    def test_both_cameras_launch_before_wait_and_save_matching_event_files(self):
        factory, processes = self.process_factory()
        files = self.run_capture(factory)
        self.assertEqual(len(files), 2)
        self.assertEqual({p.name.split('_camera-')[0] for p in files}, {files[0].name.split('_camera-')[0]})
        self.assertTrue(all(p.is_file() and p.stat().st_size > 0 for p in files))
        self.assertFalse(list(self.output.glob('*.partial.mkv')))
        for process in processes:
            command = process.command
            self.assertEqual(command[command.index('-t')+1], '5')
            self.assertIn('-n', command)
            self.assertIn('copy', command)
            self.assertNotIn('pipe:1', command)

    def test_one_failed_camera_preserves_other_clip_and_incomplete_file(self):
        factory, _ = self.process_factory(failed=1)
        with self.assertLogs(recorder.__name__, level='ERROR'):
            files = self.run_capture(factory)
        self.assertEqual(len(files), 1)
        self.assertIn('camera-1', files[0].name)
        self.assertEqual(len(list(self.output.glob('*.partial.mkv'))), 1)

    def test_stalled_camera_is_terminated_without_losing_completed_camera(self):
        factory, processes = self.process_factory(stalled=1)
        with patch.object(recorder.time, 'monotonic', side_effect=[0, 100]), \
             self.assertLogs(recorder.__name__, level='ERROR'):
            files = self.run_capture(factory)
        self.assertEqual(len(files), 1)
        self.assertTrue(processes[1].terminated)

    def test_shutdown_stops_both_recorders_and_keeps_incomplete_files(self):
        stop = threading.Event()
        factory, processes = self.process_factory(stop=stop)
        with self.assertLogs(recorder.__name__, level='ERROR'):
            files = self.run_capture(factory, stop)
        self.assertEqual(files, [])
        self.assertTrue(all(process.terminated for process in processes))
        self.assertEqual(len(list(self.output.glob('*.partial.mkv'))), 2)

    def test_missing_usb_does_not_create_storage_on_sd_card(self):
        with patch.object(Path, 'is_mount', return_value=False), self.assertRaises(RuntimeError):
            recorder.prepare_storage(self.output, self.mount)
        self.assertFalse(self.output.exists())

    def test_low_space_refuses_capture_without_deleting_existing_clips(self):
        self.output.mkdir()
        existing = self.output / 'keep.mkv'
        existing.write_bytes(b'keep this recording')
        with patch.object(Path, 'is_mount', return_value=True), \
             patch.object(recorder.shutil, 'disk_usage', return_value=SimpleNamespace(free=100)), \
             self.assertRaises(RuntimeError):
            recorder.prepare_storage(self.output, self.mount)
        self.assertEqual(existing.read_bytes(), b'keep this recording')

    def test_pir_high_level_causes_one_recording_until_sensor_goes_low(self):
        stop = threading.Event()
        triggers = []

        class Sensor:
            motion_calls = 0
            low_checks = 0
            def wait_for_motion(self, timeout):
                self.motion_calls += 1
                return True
            def wait_for_no_motion(self, timeout):
                self.low_checks += 1
                if self.low_checks == 3:
                    stop.set()
                return False

        sensor = Sensor()
        recorder.monitor_motion(sensor, stop, lambda: triggers.append('motion'))
        self.assertEqual(triggers, ['motion'])
        self.assertEqual(sensor.motion_calls, 1)
        self.assertEqual(sensor.low_checks, 3)

    def test_sensor_rearms_after_low_for_a_second_motion_event(self):
        stop = threading.Event()
        triggers = []

        class Sensor:
            def wait_for_motion(self, timeout):
                return True
            def wait_for_no_motion(self, timeout):
                return True

        def capture():
            triggers.append('motion')
            if len(triggers) == 2:
                stop.set()

        recorder.monitor_motion(Sensor(), stop, capture)
        self.assertEqual(len(triggers), 2)
