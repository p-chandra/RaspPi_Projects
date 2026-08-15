import time
import board
import libcamera
import neopixel
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from gpiozero import MotionSensor

def clear_strip_blue():
    pixels.fill((0, 0, 255))
    pixels.show()

def clear_strip_white():
    pixels.fill((255, 255, 255))
    pixels.show()

def clear_strip():
    pixels.fill((0, 0, 0))
    pixels.show()

# Configure LED strip
pixel_pin = board.D18  # GPIO 18
num_pixels = 8         # Number of LEDs in your strip
ORDER = (1, 0, 2)      # GRB order: (Green, Red, Blue)
# ORDER = "GRB"        # Another way to initialize the pixel order using a string (uncomment if you prefer this method)

# Initialize the strip
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=0.2, auto_write=False, pixel_order=ORDER)

# Initialize the raspberry pi camera
picam = Picamera2()

# Initialize the motion sensor on GPIO 17 pin 11
pir = MotionSensor(17)

# Configure camera settings
video_config = picam.create_video_configuration() # Default video configuration
picam.configure(video_config)

# Create H.264 encoder
encoder = H264Encoder(bitrate=20_000_000)

# initializing count variable to keep track of the number of videos recorded
# later plan on creating timestamp as file name instead of count variable
count = 0

# light the leds blue to indicate the program is running and waiting for motion
clear_strip_blue()

try:
    print("Starting camera...")
    picam.start()
    time.sleep(2)
    print("Starting Motion Detection. Press Ctrl+C to stop.")

    while True:
       if pir.motion_detected: # type: ignore
          print("Motion Detected")
          clear_strip_white()
          count += 1
          output = FileOutput(f"Raspberry-4-Projects/GPIO/images/test_video{count}.h264")
          picam.start_recording(encoder, output)
          time.sleep(10)
          picam.stop_recording()
       else:
          print("No Motion Detected")
          clear_strip_blue()
       time.sleep(2)  # Sleep for a short time to avoid excessive CPU usage
except KeyboardInterrupt:
    print("\nShutting down gracefully...")

finally:
    picam.stop()
    pir.close()
    clear_strip()
    print("Done! Videos saved as test_video*.h264")

# Reference my LED strip code to run this script:
# source ~/my_env/bin/activate
# sudo ~/my_env/bin/python3 Raspberry-4-Projects/GPIO/main.py