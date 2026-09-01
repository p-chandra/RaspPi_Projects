import time
from datetime import datetime

from picamera2 import Picamera2
from gpiozero import MotionSensor

# PIR sensor on GPIO 17
pir = MotionSensor(17)

# Camera 0 - Pi Camera
pi_camera = Picamera2(0)
pi_config = pi_camera.create_still_configuration()
pi_camera.configure(pi_config)

# Camera 1 - USB Webcam
webcam = Picamera2(1)
webcam_config = webcam.create_still_configuration()
webcam.configure(webcam_config)

# Start both cameras
pi_camera.start()
webcam.start()

# Allow cameras to initialize
time.sleep(2)

IMAGE_DIR = "/home/p-c/Documents/RaspPi_Projects/Motion_Camera/images"

try:
    while True:
        print("Waiting for motion...")
        pir.wait_for_motion()

        print("Motion Detected!")

        # Same timestamp for both images
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        pi_filename = f"{IMAGE_DIR}/picam_{timestamp}.jpg"
        webcam_filename = f"{IMAGE_DIR}/webcam_{timestamp}.jpg"

        # Capture from Pi Camera
        pi_camera.capture_file(pi_filename)
        print(f"Pi Camera: {pi_filename}")

        # Capture from webcam
        webcam.capture_file(webcam_filename)
        print(f"Webcam:    {webcam_filename}")

        # Wait for PIR to reset
        pir.wait_for_no_motion()

        print("Motion ended")

except KeyboardInterrupt:
    print("\nShutting down gracefully...")

finally:
    pir.close()
    pi_camera.stop()
    webcam.stop()