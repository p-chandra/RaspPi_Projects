import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from gpiozero import MotionSensor
from signal import pause


# 1. Initialize the camera and  GPIO pin for motion sensor
picam = Picamera2()
pir = MotionSensor(17)

# 2. Configure camera settings
video_config = picam.create_video_configuration()
picam.configure(video_config)

# 3. Create H.264 encoder
encoder = H264Encoder(bitrate=20_000_000)

count = 0

try:
    print("Starting camera...")
    picam.start()
    time.sleep(10)  # Sleep for a short time to avoid excessive CPU usage

    while True:
       if pir.motion_detected: # type: ignore
          print("Motion Detected")
          count += 1
          output = FileOutput(f"Raspberry-4-Projects/GPIO/images/test_video{count}.h264")
          picam.start_recording(encoder, output)
          time.sleep(10)
          picam.stop_recording()
       else:
          print("No Motion Detected")
       time.sleep(1)  # Sleep for a short time to avoid excessive CPU usage

except KeyboardInterrupt:
    print("\nShutting down gracefully...")

finally:
    picam.stop()
    pir.close()
    print("Done! Videos saved as test_video*.h264")