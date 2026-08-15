import time
from picamera2 import Picamera2
from gpiozero import MotionSensor

# Set up the motion sensor on GPIO 17 pin 11
pir = MotionSensor(17)

# Set up the camera
picam = Picamera2()

# Configure the camera to default settings
config = picam.create_preview_configuration()
picam.configure(config)

# Start camera
picam.start()

count = 0

try:
   while True:
      if pir.motion_detected: # type: ignore
         print("Motion Detected")
         count += 1
         picam.capture_file(f"Raspberry-4-Projects/GPIO/images/image_{count}.jpg")
      else:
         print("No Motion Detected")
      time.sleep(0.5)  # Sleep for a short time to avoid excessive CPU usage
except KeyboardInterrupt:
   print("\nShutting down gracefully...")
finally:
   pir.close()
   picam.stop()
