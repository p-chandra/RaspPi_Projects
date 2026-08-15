import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

# 1. Initialize the camera
picam = Picamera2()

# 2. Configure camera settings
video_config = picam.create_video_configuration()
picam.configure(video_config)

# 3. Create H.264 encoder
encoder = H264Encoder(bitrate=20_000_000)

# 4. Save as RAW H.264 stream
output = FileOutput("Raspberry-4-Projects/GPIO/images/test_video.h264")

# 5. Start the camera
print("Starting camera...")
picam.start()

# 6. Start recording
print("Recording video for 10 seconds...")
picam.start_recording(encoder, output)

# 7. Record duration
time.sleep(10)

# 8. Stop recording
print("Finishing recording and saving file...")
picam.stop_recording()

# 9. Stop camera
picam.stop()

print("Done! Video saved as test_video.h264")