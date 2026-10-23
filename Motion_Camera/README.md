## HC-SR501 motion-triggered recording

`main.py` monitors the existing HC-SR501 on **BCM GPIO 17 (physical header pin 11)**. It waits 30 seconds for sensor warm-up, then each motion event starts a **five-second recording from both detected USB webcams concurrently**. Camera settings are detected automatically using the same helpers as the streaming script; no resolution or frame-rate flags are needed.

On the Pi, after pulling the code:

```sh
sudo apt install ffmpeg v4l-utils python3-gpiozero python3-lgpio
~/usb-photos.sh -connect
cd ~/Documents/RaspPi_Projects/Motion_Camera
python3 main.py
```

Use the system Python or a virtual environment created with `--system-site-packages` so it can import the Pi's gpiozero/lgpio packages. Run as a user with GPIO and video access (the configured `p-c` user belongs to those groups). The program does not change the existing sensor wiring.

Clips are saved to **`Personal/Surveillance`**, currently `/srv/pi-photos-primary/Surveillance` on PhotoDrive. It is separate from `Photos` and `Videos`. Each event creates two UTC-timestamped `.mkv` files ending in `_camera-1.mkv` and `_camera-2.mkv`; both share the same event identifier. Matroska preserves the cameras' native MJPEG/H.264/HEVC video without additional lossy encoding and plays in VLC. No audio is recorded. Camera opening adds startup latency; each clip contains five seconds of video after its camera starts.

The PIR must return LOW before another event is armed. Motion during a recording does not create overlapping clips or extend the five-second duration. If one camera fails, a successful clip from the other is retained and an error identifies the missing recording. Reconnected cameras are detected again on the next event. With only one camera available, the program logs a warning and records that camera.

The USB must be mounted; recording never deliberately falls back to the SD card. New recordings are refused below 512 MiB free, and no existing clips are automatically deleted. Failed/interrupted clips remain as hidden `.partial.mkv` files for inspection; they are not presented as complete five-second recordings. A stuck camera is terminated after the five-second clip budget plus 20 seconds of startup allowance. Ctrl+C or SIGTERM stops the recorder, terminates active FFmpeg processes and releases GPIO.

Stop `stream_picam.py` before running `main.py`; these independent programs open the webcams directly and cannot share an active camera capture. Pi Photos can keep running. Stop the motion recorder before disconnecting the USB. Scheduled photo backups currently cover the photo library, not `Surveillance`.

Local validation uses mocked GPIO/processes and temporary files, without activating the real sensor or recording real cameras:

```sh
python3 -m unittest -v test_motion_recording test_stream_modes
```

The 17 checks cover concurrent camera launch, five-second FFmpeg output settings, per-camera failures, shutdown/timeouts, PIR HIGH/LOW rearming, storage guards and the existing streaming behavior. A real motion-triggered two-camera recording remains to be checked after deployment to the Pi.

## Automatic USB webcam streaming

Run `python3 stream_picam.py` without options. Install `ffmpeg` and `v4l-utils` first. The script discovers up to **two USB webcams**, queries each camera's advertised modes, and starts independent streams on **ports 5000 and 5001**. It prefers the highest-resolution native compressed mode supporting at least 30 fps, using the highest available frame rate at that resolution. A slower camera uses its fastest advertised compressed mode. Raw-only webcams use software H.264 encoding at a modest resolution to limit Pi CPU use.

With the connected cameras' current stable USB identifiers, the **C920 is assigned port 5000** and automatically selects **1920×1080 at 30 fps**; the **Insta360 X4 is assigned port 5001** and selects **2880×1440 at 30 fps**, according to its advertised webcam modes. The script prints each camera's device identifier, port and selected mode at startup. Native MJPEG/H.264/HEVC is passed through without re-encoding and carried in Matroska over TCP. Open `tcp://192.168.0.162:5000` and `tcp://192.168.0.162:5001` in separate VLC windows on the local network, or use `100.117.156.54` instead on a device with its own Tailscale connection. Windows does not inherit WSL's Tailscale connection. Port assignment follows discovery order; with only one camera connected it uses port 5000.

Each camera accepts one viewer at a time; **both cameras can stream concurrently**. Capture starts after its viewer connects and waits for another viewer after disconnection. A reconnect on one stream leaves the other running. Ctrl+C or SIGTERM stops both listeners and their FFmpeg processes. Both ports are reserved before starting capture workers to avoid partially starting when a port is already in use. The script does not record video or audio. Restart it after swapping webcams so it detects the new devices and modes; no resolution or frame-rate options are needed. Native MJPEG at full HD used roughly 50–70 Mbps in the earlier single-camera test; simultaneous streams share USB and network capacity. Nine local tests cover mode selection, the two-camera limit, independent reconnects, and encoder shutdown: `python3 -m unittest -v test_stream_modes`.

If the Pi has uncommitted Motion_Camera changes from earlier deployments, preserve them before pulling your WSL commit:

```sh
cd ~/Documents/RaspPi_Projects
git stash push -u -m "before-two-camera-update" -- Motion_Camera
git pull
python3 Motion_Camera/stream_picam.py
```

The stash preserves the earlier version; do not apply it over the new script unless you intend to merge or restore that version.

## Other project setup notes

Install Python3 pip and venv if you don't have them

`sudo apt install python3-pip python3-venv minicom screen -y`

`cd ~`

`mkdri my_env`

Create a virtual environment (recommended for modern Raspberry Pi OS)

System site packages are system libraryies that are available to all Python environments. By using --system-site-packages, you can access these libraries from within your virtual environment without having to install them separately.

`python3 -m venv ~/my_env --system-site-packages`

Activate the virtual environment
`source ~/my_env/bin/activate`

Install the required libraries for controlling the WS2812 LED strip

`~/my_env/bin/pip install rpi_ws281x adafruit-circuitpython-neopixel mpremote`

Run the script with sudo to access GPIO pins

`sudo ~/my_env/bin/python3 Raspberry-4-Projects/GPIO/test_led_sensor.py`

If you have a micro controller plugged in, check with `ls /dev/ttyACM*`. If the output matches then you're good to go. Open MicroPython REPL with `mpremote connect auto repl`. To exit press `'CTRL + ]'` and to upload a file to the microcontroller `mpremote fs cp blink.py :` and to run `mpremote run blink.py`
