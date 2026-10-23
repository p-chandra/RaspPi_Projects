"""Mode-selection checks; no camera or stream is opened."""
import unittest
from contextlib import redirect_stdout
import io
import socket
import threading
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import stream_picam
from stream_picam import choose_mode, parse_modes, stream_command, detect_webcams, create_listener, stream_webcam


class WebcamModes(unittest.TestCase):
    def test_c920_full_hd_native_video(self):
        modes = parse_modes("""
[0]: 'YUYV' (raw)
 Size: Discrete 1920x1080
  Interval: Discrete 0.200s (5.000 fps)
[1]: 'MJPG' (compressed)
 Size: Discrete 640x480
  Interval: Discrete 0.033s (30.000 fps)
 Size: Discrete 1920x1080
  Interval: Discrete 0.033s (30.000 fps)
  Interval: Discrete 0.067s (15.000 fps)
""")
        mode = choose_mode(modes)
        self.assertEqual((mode['format'], mode['width'], mode['height'], mode['fps']), ('MJPG', 1920, 1080, 30))
        command = stream_command('/dev/video0', mode)
        self.assertIn('copy', command)
        self.assertNotIn('libx264', command)
        self.assertEqual(command[-1], 'pipe:1')

    def test_new_4k_camera_needs_no_code_changes(self):
        mode = choose_mode([{'format': 'MJPG', 'width': 1920, 'height': 1080, 'fps': 60},
                            {'format': 'MJPG', 'width': 3840, 'height': 2160, 'fps': 60},
                            {'format': 'H264', 'width': 3840, 'height': 2160, 'fps': 60}])
        self.assertEqual((mode['width'], mode['height'], mode['fps'], mode['format']), (3840, 2160, 60, 'H264'))

    def test_smooth_video_preferred_over_slow_4k(self):
        mode = choose_mode([{'format': 'MJPG', 'width': 3840, 'height': 2160, 'fps': 5},
                            {'format': 'MJPG', 'width': 1920, 'height': 1080, 'fps': 29.97}])
        self.assertEqual(mode['height'], 1080)

    def test_raw_camera_limits_pi_encoding_load(self):
        mode = choose_mode([{'format': 'YUYV', 'width': 3840, 'height': 2160, 'fps': 30},
                            {'format': 'YUYV', 'width': 1280, 'height': 720, 'fps': 30}])
        self.assertEqual(mode['height'], 720)
        self.assertIn('libx264', stream_command('/dev/video0', mode))

    def test_slow_camera_prefers_frame_rate(self):
        mode = choose_mode([{'format': 'MJPG', 'width': 1920, 'height': 1080, 'fps': 5},
                            {'format': 'MJPG', 'width': 1280, 'height': 720, 'fps': 15}])
        self.assertEqual(mode['fps'], 15)

    def test_metadata_and_unsupported_devices_skipped(self):
        self.assertEqual(parse_modes("[0]: 'META'\n Size: Discrete 640x480\n Interval: Discrete 0.033s (30 fps)"), [])
        with self.assertRaises(ValueError):
            choose_mode([])
        with patch('stream_picam.glob.glob', return_value=['/dev/v4l/by-id/usb-camera-video-index0']):
            self.assertEqual(detect_webcams(), ['/dev/v4l/by-id/usb-camera-video-index0'])


class ConcurrentStreams(unittest.TestCase):
    def test_main_limits_capture_to_two_cameras_and_separate_ports(self):
        output = "[0]: 'MJPG'\n Size: Discrete 1920x1080\n Interval: Discrete 0.033s (30 fps)"
        workers = [MagicMock(), MagicMock()]
        for worker in workers:
            worker.is_alive.return_value = False
        listeners = [MagicMock(), MagicMock()]
        with patch('stream_picam.shutil.which', return_value='/usr/bin/tool'), \
             patch('stream_picam.detect_webcams', return_value=['camera-0', 'camera-1', 'camera-2']), \
             patch('stream_picam.subprocess.run', return_value=SimpleNamespace(stdout=output)) as probe, \
             patch('stream_picam.create_listener', side_effect=listeners) as bind, \
             patch('stream_picam.threading.Thread', side_effect=workers) as thread, \
             patch('stream_picam.signal.signal'), redirect_stdout(io.StringIO()):
            stream_picam.main()
        self.assertEqual(probe.call_count, 2)
        self.assertEqual([call.args[0] for call in bind.call_args_list], [5000, 5001])
        self.assertEqual([call.kwargs['args'][0] for call in thread.call_args_list], ['camera-0', 'camera-1'])
        self.assertTrue(all(worker.start.called for worker in workers))
        self.assertTrue(all(listener.close.called for listener in listeners))

    def test_two_cameras_and_independent_viewer_reconnects(self):
        mode = {'format': 'MJPG', 'width': 1920, 'height': 1080, 'fps': 30}
        listeners = [create_listener(0), create_listener(0)]
        stop = threading.Event()
        workers = []

        class Encoder:
            def __init__(self, command, stdout, **kwargs):
                device = command[command.index('-i') + 1]
                stdout.sendall(device.encode())
            def poll(self):
                return 0

        with patch('stream_picam.subprocess.Popen', side_effect=Encoder), redirect_stdout(io.StringIO()):
            try:
                for i, listener in enumerate(listeners):
                    worker = threading.Thread(target=stream_webcam,
                                              args=(f'camera-{i}', mode, listener.getsockname()[1], stop, listener))
                    worker.start()
                    workers.append(worker)
                # Both listeners exist at the same time. Reconnecting to one
                # leaves the other able to accept its own viewers.
                for i in (0, 1, 0, 1):
                    with socket.create_connection(('127.0.0.1', listeners[i].getsockname()[1]), timeout=2) as client:
                        self.assertEqual(client.recv(32), f'camera-{i}'.encode())
            finally:
                stop.set()
                for worker in workers:
                    worker.join(timeout=3)
                for listener in listeners:
                    listener.close()
        self.assertTrue(all(not worker.is_alive() for worker in workers))

    def test_shutdown_terminates_an_active_camera_encoder(self):
        mode = {'format': 'MJPG', 'width': 1920, 'height': 1080, 'fps': 30}
        listener = create_listener(0)
        port = listener.getsockname()[1]
        stop, started = threading.Event(), threading.Event()
        encoders = []

        class Encoder:
            def __init__(self, *args, **kwargs):
                self.running = True
                self.terminated = False
                encoders.append(self)
                started.set()
            def poll(self):
                return None if self.running else -15
            def terminate(self):
                self.terminated, self.running = True, False
            def wait(self, timeout=None):
                return -15

        with patch('stream_picam.subprocess.Popen', side_effect=Encoder), redirect_stdout(io.StringIO()):
            worker = threading.Thread(target=stream_webcam, args=('camera-0', mode, port, stop, listener))
            worker.start()
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=2):
                    self.assertTrue(started.wait(timeout=2))
                    stop.set()
                    worker.join(timeout=3)
            finally:
                stop.set()
                worker.join(timeout=3)
                listener.close()
        self.assertFalse(worker.is_alive())
        self.assertTrue(encoders[0].terminated)
