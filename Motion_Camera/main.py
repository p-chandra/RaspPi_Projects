"""HC-SR501 motion on BCM GPIO 17 records five seconds from up to two USB webcams."""
from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from stream_picam import discover_cameras, stop_encoder, stream_command

PIR_GPIO_PIN = 17  # BCM numbering: physical header pin 11.
CLIP_SECONDS = 5
SENSOR_WARMUP_SECONDS = 30
CAPTURE_STARTUP_TIMEOUT_SECONDS = 20
USB_MOUNT = Path('/srv/pi-photos-primary')
RECORDINGS_DIR = USB_MOUNT / 'Surveillance'
MIN_FREE_BYTES = 512 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


def prepare_storage(output_dir=RECORDINGS_DIR, mount=USB_MOUNT):
    """Never fall back to writing footage on the Pi's SD card."""
    if not mount.is_mount():
        raise RuntimeError(f'PhotoDrive is not mounted at {mount}; recording skipped')
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(mount.resolve()):
        raise RuntimeError('Recording folder must be on the USB drive')
    output_dir.mkdir(parents=True, exist_ok=True)
    if not mount.is_mount():
        raise RuntimeError('USB drive disconnected while preparing recording storage')
    if shutil.disk_usage(output_dir).free < MIN_FREE_BYTES:
        raise RuntimeError('Less than 512 MiB free on the USB; recording skipped. Existing clips are kept.')
    return output_dir


def recording_command(device, mode, destination):
    # Reuse automatic capture settings and native compressed-video pass-through.
    # Replace the streaming output with a bounded five-second Matroska clip.
    return stream_command(device, mode)[:-1] + ['-t', str(CLIP_SECONDS), '-n', str(destination)]


def record_motion(cameras, stop_event, output_dir=RECORDINGS_DIR, mount=USB_MOUNT):
    """Launch both FFmpeg processes before waiting; publish completed clips only."""
    output_dir = prepare_storage(output_dir, mount)
    if not cameras:
        LOGGER.error('No supported USB webcams detected; no clips recorded')
        return []
    if len(cameras) < 2:
        LOGGER.warning('Only one webcam is available; recording that camera')
    event_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '_' + uuid.uuid4().hex[:8]
    recordings = []
    completed = []
    interrupted = None
    deadline = time.monotonic() + CLIP_SECONDS + CAPTURE_STARTUP_TIMEOUT_SECONDS
    try:
        for index, (device, mode) in enumerate(cameras[:2], 1):
            if stop_event.is_set():
                break
            final = output_dir / f'{event_id}_camera-{index}.mkv'
            partial = output_dir / f'.{event_id}_camera-{index}.partial.mkv'
            errors = tempfile.TemporaryFile()
            try:
                process = subprocess.Popen(recording_command(device, mode, partial), stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=errors, start_new_session=True)
            except OSError:
                errors.close()
                LOGGER.exception('Could not start camera %s (%s)', index, device)
                continue
            recordings.append((index, device, process, errors, partial, final))
            LOGGER.info('Recording camera %s: %s, %sx%s at %g fps', index, device,
                        mode['width'], mode['height'], mode['fps'])

        while any(item[2].poll() is None for item in recordings):
            if stop_event.is_set():
                interrupted = 'shutdown requested'
                break
            if not mount.is_mount():
                interrupted = 'USB drive disconnected'
                break
            if time.monotonic() >= deadline:
                interrupted = 'camera startup or capture timed out'
                break
            stop_event.wait(0.1)

        for index, device, process, errors, partial, final in recordings:
            completed_normally = process.poll() == 0
            if process.poll() is None:
                stop_encoder(process)
            if completed_normally and partial.is_file() and partial.stat().st_size > 0:
                if final.exists():
                    LOGGER.error('Destination already exists; retained partial clip for camera %s', index)
                    continue
                partial.rename(final)
                completed.append(final)
                LOGGER.info('Saved five-second clip: %s', final)
            else:
                errors.seek(0, 2)
                size = errors.tell()
                errors.seek(max(0, size - 2000))
                detail = errors.read().decode(errors='replace').strip()
                LOGGER.error('Camera %s (%s) recording incomplete: %s; FFmpeg exit %s. %s',
                             index, device, interrupted or 'capture failed', process.returncode, detail)
                if partial.exists():
                    LOGGER.warning('Partial clip retained: %s', partial)
    finally:
        for _, _, process, errors, _, _ in recordings:
            try:
                stop_encoder(process)
            finally:
                errors.close()
    return completed


def monitor_motion(sensor, stop_event, on_motion):
    while not stop_event.is_set():
        if not sensor.wait_for_motion(timeout=0.25) or stop_event.is_set():
            continue
        on_motion()
        # HC-SR501 can hold its output HIGH for a long time. Rearm only after
        # LOW, instead of producing overlapping or back-to-back duplicate clips.
        while not stop_event.is_set() and not sensor.wait_for_no_motion(timeout=0.25):
            pass


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    for executable, package in [('ffmpeg', 'ffmpeg'), ('v4l2-ctl', 'v4l-utils')]:
        if not shutil.which(executable):
            LOGGER.error('%s is required. Install: sudo apt install %s', executable, package)
            return 1
    try:
        from gpiozero import MotionSensor
    except ImportError:
        LOGGER.error('gpiozero is required. Install: sudo apt install python3-gpiozero python3-lgpio')
        return 1

    sensor = None
    stop_event = threading.Event()
    previous = {sig: signal.signal(sig, lambda signum, frame: stop_event.set())
                for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        prepare_storage()
        cameras = discover_cameras()
        if not cameras:
            LOGGER.error('No supported USB webcams available')
            return 1
        LOGGER.info('Found %s webcam(s). Clips: %s', len(cameras), RECORDINGS_DIR)
        sensor = MotionSensor(PIR_GPIO_PIN)
        LOGGER.info('HC-SR501 on GPIO %s (physical pin 11); warming up for %s seconds',
                    PIR_GPIO_PIN, SENSOR_WARMUP_SECONDS)
        if stop_event.wait(SENSOR_WARMUP_SECONDS):
            return 0
        LOGGER.info('Armed. Motion records five seconds per camera; Ctrl+C stops monitoring.')

        def on_motion():
            LOGGER.info('Motion detected')
            try:
                # Re-probe on each event to handle cameras reconnected between triggers.
                clips = record_motion(discover_cameras(), stop_event)
                LOGGER.info('Motion event complete: %s clip(s) saved', len(clips))
            except (OSError, RuntimeError):
                LOGGER.exception('Motion event could not be recorded')

        monitor_motion(sensor, stop_event, on_motion)
        return 0
    except (OSError, RuntimeError) as error:
        LOGGER.error('Motion recorder could not start: %s', error)
        return 1
    finally:
        stop_event.set()
        if sensor is not None:
            sensor.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        LOGGER.info('Motion monitoring stopped')


if __name__ == '__main__':
    raise SystemExit(main())
