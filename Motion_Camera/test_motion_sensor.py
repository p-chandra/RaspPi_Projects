from gpiozero import MotionSensor
from time import sleep

# Set up motion sensor on GPIO17 (physical pin 11)
pir = MotionSensor(17)

while True:
    if pir.motion_detected:
        print("Motion Detected")
    else:
        print("No Motion Detected")

    sleep(1)
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