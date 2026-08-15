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
