import glob
import shutil
import subprocess
import time


def detect_picameras():
    """Ask the Raspberry Pi camera tools to list connected Pi cameras."""
    if not shutil.which("rpicam-hello"):
        print("rpicam-hello is not installed; skipping Pi camera detection.")
        return False

    result = subprocess.run(
        ["rpicam-hello", "--list-cameras"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    print(output or "No Raspberry Pi cameras detected.")
    return result.returncode == 0 and "No cameras available" not in output


def detect_webcams():
    """List webcams exposed through Linux's V4L2 interface."""
    devices = sorted(glob.glob("/dev/video*"))
    if not devices:
        print("No webcams detected.")
        return []

    print("V4L2 video devices detected:")
    if shutil.which("v4l2-ctl"):
        # v4l2-ctl prints friendly webcam names and their /dev/video paths.
        subprocess.run(["v4l2-ctl", "--list-devices"], check=False)
    else:
        print("  " + "\n  ".join(devices))
        print("Install v4l-utils to display friendly webcam names.")
    return devices


def stream_webcam(device):
    """Stream a V4L2 webcam and accept a new viewer after disconnects."""
    if not shutil.which("ffmpeg"):
        print("FFmpeg is required to stream a webcam. Install it with:")
        print("  sudo apt install ffmpeg")
        return

    command = [
        "ffmpeg",
        "-f",
        "v4l2",
        "-i",
        device,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-f",
        "mpegts",
        "tcp://0.0.0.0:5000?listen=1",
    ]

    print(f"Streaming webcam {device} on tcp://0.0.0.0:5000")
    print("Open tcp://<raspberry-pi-ip>:5000 in VLC. Press Ctrl+C to stop.")

    try:
        while True:
            print("Waiting for a viewer to connect...")
            result = subprocess.run(command, check=False)
            print(f"Viewer disconnected (FFmpeg exit code {result.returncode}).")
            print("Restarting the stream for the next connection...")
            # Avoid a tight restart loop if the camera is briefly unavailable.
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nWebcam stream stopped.")


def main():
    has_picamera = detect_picameras()
    webcams = detect_webcams()

    if not has_picamera:
        if webcams:
            stream_webcam(webcams[0])
        else:
            print("No camera available; stream was not started.")
        return
    if not shutil.which("rpicam-vid"):
        print("rpicam-vid is not installed; stream was not started.")
        return

    # Stream the Raspberry Pi camera on TCP port 5000 until Ctrl+C is pressed.
    subprocess.run(
        [
            "rpicam-vid",
            "-t",
            "0",
            "--inline",
            "--listen",
            "-o",
            "tcp://0.0.0.0:5000",
        ],
        check=False,
    )


if __name__ == "__main__":
    main()
