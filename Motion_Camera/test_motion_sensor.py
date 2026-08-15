from gpiozero import MotionSensor
from signal import pause

# Set up the motion sensor on GPIO 17 pin 11
pir = MotionSensor(17)

def motion_function():
	print("Motion Detected")

def no_motion_function():
	print("No Motion Detected")

pir.when_motion = motion_function
pir.when_no_motion = no_motion_function

pause()

# 1. MotionSensor(17) created
#    └─ Spawns background thread monitoring GPIO pin 17

# 2. pir.when_motion = motion_function
#    └─ Registers callback in gpiozero's event handler

# 3. pause()
#    └─ Blocks main program
#       └─ Background thread keeps running
#          └─ Listens for GPIO changes
#             ├─ Detects motion? → Calls motion_function()
#             └─ Detects no motion? → Calls no_motion_function()