import time, libcamera
from picamera2 import Picamera2, Preview


#Import the required libraries. We need classes from Picamera2.
#We also use the time to wait for the camera to adjust to the environment before saving the picture.
#Create a default configuration. We'll add some variables later, but for now, the default settings are fine.
#We start the preview window (you?ll see what the camera sees on your screen) and we also start the camera.
#We wait 2 seconds (sleep) and save the picture in the current folder (?test-python.jpg?).

picam = Picamera2()

#config = picam.create_preview_configuration()		#Default config
config = picam.create_preview_configuration(main={"size": (2592, 1944)})	#altered config for HD
#config["transform"] = libcamera.Transform(hflip=1, vflip=1)		        #verticle flip image

picam.configure(config)		#setting configs

#picam.start_preview(Preview.QTGL)		#Preview config but only works if you have a display plugin installed.
                                        #If you?re running this code on a headless setup, you can comment out 
                                        #the line above and the preview will not be shown.

picam.start()		                    #Start camera
time.sleep(2)		                    #Give camera 2 seconds before capture
picam.capture_file("Raspberry-4-Projects/GPIO/images/test-python.jpg")	#capture can name file

# Creating time lapse
#for i in range(1,10):
#    picam.capture_file(f"ts{i}.jpg")
#    print(f"Captured image {i}")
#    time.sleep(3)

picam.close()		#Close camera