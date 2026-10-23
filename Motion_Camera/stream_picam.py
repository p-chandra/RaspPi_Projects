"""Automatically stream up to two USB webcams on TCP ports 5000 and 5001."""
import glob
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import threading

FORMATS = {
    'H264': ('h264', True), 'HEVC': ('hevc', True),
    'MJPG': ('mjpeg', True), 'JPEG': ('mjpeg', True),
    'YUYV': ('yuyv422', False), 'UYVY': ('uyvy422', False),
    'NV12': ('nv12', False), 'RGB3': ('rgb24', False),
}


def detect_webcams():
    """Return USB capture nodes, preferring stable USB device identifiers."""
    devices = sorted(glob.glob('/dev/v4l/by-id/usb-*-video-index0'))
    resolved = {str(Path(device).resolve()) for device in devices}
    for path in sorted(glob.glob('/dev/video*')):
        node = Path('/sys/class/video4linux') / Path(path).name
        if str(Path(path).resolve()) in resolved or '/usb' not in str((node / 'device').resolve()):
            continue
        # Capture and metadata nodes can belong to the same physical webcam.
        if (node / 'index').exists() and (node / 'index').read_text().strip() != '0':
            continue
        devices.append(path)
        resolved.add(str(Path(path).resolve()))
    return devices


def parse_modes(output):
    modes = []
    pixel_format = size = None
    for line in output.splitlines():
        match = re.search(r"\[\d+\]: '([^']+)'", line)
        if match:
            pixel_format, size = match.group(1), None
            continue
        match = re.search(r'Size: Discrete (\d+)x(\d+)', line)
        if not match:
            match = re.search(r'Size: (?:Stepwise|Continuous) \d+x\d+ - (\d+)x(\d+)', line)
        if match:
            size = tuple(map(int, match.groups()))
            continue
        match = re.search(r'Interval: Discrete [\d.]+s \(([\d.]+) fps\)', line)
        fps = float(match.group(1)) if match else None
        if fps is None:
            match = re.search(r'Interval: (?:Stepwise|Continuous) ([\d.]+)s', line)
            if match and float(match.group(1)) > 0:
                fps = 1 / float(match.group(1))
        if pixel_format in FORMATS and size and fps and fps > 0:
            modes.append({'format': pixel_format, 'width': size[0], 'height': size[1], 'fps': fps})
    return modes


def choose_mode(modes):
    """Prefer maximum resolution at 30+ fps and native compressed video."""
    if not modes:
        raise ValueError('No supported USB webcam capture modes found')
    compressed = [mode for mode in modes if FORMATS[mode['format']][1]]
    if compressed:
        candidates = compressed
    else:
        # Bound software H.264 encoding work on a Pi for raw-only webcams.
        candidates = [m for m in modes if m['width'] * m['height'] <= 1280 * 720]
        if not candidates:
            smallest = min(m['width'] * m['height'] for m in modes)
            candidates = [m for m in modes if m['width'] * m['height'] == smallest]
    smooth = [m for m in candidates if m['fps'] >= 29.9]
    priority = {'H264': 3, 'HEVC': 2, 'MJPG': 1, 'JPEG': 1}
    if smooth:
        return max(smooth, key=lambda m: (m['width'] * m['height'], m['fps'], priority.get(m['format'], 0)))
    return max(candidates, key=lambda m: (m['fps'], m['width'] * m['height'], priority.get(m['format'], 0)))


def stream_command(device, mode):
    input_format, compressed = FORMATS[mode['format']]
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'warning', '-stats',
               '-fflags', '+discardcorrupt', '-f', 'v4l2', '-input_format', input_format,
               '-video_size', f"{mode['width']}x{mode['height']}", '-framerate', f"{mode['fps']:g}",
               '-i', device, '-an']
    if compressed:
        command += ['-c:v', 'copy']
    else:
        command += ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                    '-pix_fmt', 'yuv420p', '-crf', '18']
    return command + ['-f', 'matroska', '-flush_packets', '1', 'pipe:1']


def create_listener(port):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('0.0.0.0', port))
        listener.listen(1)
        listener.settimeout(0.5)
        return listener
    except BaseException:
        listener.close()
        raise


def stop_encoder(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def stream_webcam(device, mode, port, stop_event, listener):
    label = f'[Camera on port {port}]'
    print(f"{label} USB webcam: {device}")
    print(f"{label} Automatically selected: {mode['width']}x{mode['height']} at {mode['fps']:g} fps ({mode['format']})")
    if FORMATS[mode['format']][1]:
        print(f'{label} Passing camera-compressed video through without re-encoding.')
    print(f'{label} Open tcp://<raspberry-pi-ip>:{port} in VLC.')
    process = None
    try:
        with listener:
            while not stop_event.is_set():
                print(f'{label} Waiting for a viewer to connect...')
                while not stop_event.is_set():
                    try:
                        connection, address = listener.accept()
                        break
                    except socket.timeout:
                        continue
                else:
                    break
                with connection:
                    if stop_event.is_set():
                        break
                    print(f'{label} Viewer connected: {address[0]}')
                    # Open the camera only after a viewer connects, avoiding stale
                    # buffered frames and timestamp gaps while waiting for VLC.
                    try:
                        process = subprocess.Popen(stream_command(device, mode), stdin=subprocess.DEVNULL,
                                                   stdout=connection, start_new_session=True)
                        while process.poll() is None and not stop_event.wait(0.2):
                            pass
                        stop_encoder(process)
                        print(f'{label} Stream ended (FFmpeg exit code {process.poll()}).')
                    except OSError as error:
                        print(f'{label} Could not start capture: {error}')
                    finally:
                        stop_encoder(process)
                        process = None
                stop_event.wait(0.25)
    except OSError as error:
        print(f'{label} Listener stopped: {error}')
    finally:
        stop_encoder(process)


def discover_cameras():
    """Probe up to two USB cameras, shared by streaming and motion recording."""
    cameras = []
    for device in detect_webcams():
        try:
            result = subprocess.run(['v4l2-ctl', '-d', device, '--list-formats-ext'],
                                    capture_output=True, text=True, timeout=10, check=True)
            mode = choose_mode(parse_modes(result.stdout))
        except (subprocess.SubprocessError, ValueError) as error:
            print(f'Skipping USB device {device}: {error}')
            continue
        cameras.append((device, mode))
        if len(cameras) == 2:
            break
    return cameras


def main():
    for executable, package in [('ffmpeg', 'ffmpeg'), ('v4l2-ctl', 'v4l-utils')]:
        if not shutil.which(executable):
            print(f'{executable} is required. Install it with: sudo apt install {package}')
            return
    cameras = discover_cameras()
    if not cameras:
        print('No supported USB webcam available; stream was not started.')
        return
    stop_event = threading.Event()
    previous_handler = signal.signal(signal.SIGTERM, lambda signum, frame: stop_event.set())
    listeners, workers = [], []
    try:
        # Reserve both ports before starting workers, so a busy port cannot leave
        # a partially started background stream behind.
        for index in range(len(cameras)):
            listeners.append(create_listener(5000 + index))
        for index, (device, mode) in enumerate(cameras):
            worker = threading.Thread(target=stream_webcam,
                                      args=(device, mode, 5000 + index, stop_event, listeners[index]),
                                      name=f'webcam-{index + 1}')
            worker.start()
            workers.append(worker)
        print('Press Ctrl+C to stop all webcam streams.')
        while any(worker.is_alive() for worker in workers):
            for worker in workers:
                worker.join(timeout=0.25)
    except KeyboardInterrupt:
        print('\nStopping webcam streams...')
    except OSError as error:
        print(f'Could not start webcam listeners: {error}')
    finally:
        stop_event.set()
        for worker in workers:
            worker.join()
        for listener in listeners:
            listener.close()
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == '__main__':
    main()
