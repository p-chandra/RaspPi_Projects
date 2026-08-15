## Test
To test if the camera is connected enter this command

`rpicam-hello --list-cameras`

If it is successful: It will output a list of available cameras, showing something like 0 : imx219 [3280x2464] or ov5647. This means the Pi sees the camera perfectly, knows its exact sensor model, and is ready to use it.

If it fails: It will return No cameras available.

Output
Available cameras
-----------------
0 : ov5647 [2592x1944 10-bit GBRG] (/base/soc/i2c0mux/i2c@1/ov5647@36)
    Modes: 'SGBRG10_CSI2P' : 640x480 [62.50 fps - (16, 0)/2560x1920 crop]
                             1296x972 [46.34 fps - (0, 0)/2592x1944 crop]
                             1920x1080 [32.81 fps - (348, 434)/1928x1080 crop]
                             2592x1944 [15.63 fps - (0, 0)/2592x1944 crop]


## Take a picture
To test if the camera is working, take a picture

`rpicam-jpeg -o test.jpg`

You can then grab the image from a new terminal using scp

`scp pi@IP_OF_YOUR_PI:~/test.jpg ~/Desktop/`

## Steam on VLC

`rpicam-vid -t 0 --inline --listen -o tcp://0.0.0.0:5000`

'-t 0' This sets the timeout duration. Usually, rpicam-vid records for a default number of seconds (like 5 seconds) and then turns off Setting -t 0 tells it to run indefinitely until you manually kill the command with Ctrl + C

'--inline' This inserts critical video headers (SPS/PPS synchronization frames) directly into the stream at regular intervals. Without this, if you open VLC after the stream has already started, VLC wouldn't have the necessary data to decode the video, resulting in a blank screen or an error. This makes it possible to connect and disconnect whenever you want

'--listen' By default, rpicam-vid likes to push video out to an address you give it. Adding --listen flips its behavior, putting the Pi into server mode. It sits quietly, listening and waiting for an incoming connection from a client (like VLC) before it begins transmitting data.

'-o tcp://0.0.0.0:5000'
This defines the output (-o) target:
- tcp:// specifies the transmission protocol to ensure no video packets are dropped over the network.
- 0.0.0.0 is network shorthand for "bind to all available network interfaces." It means the stream can be reached via the Pi's Wi-Fi IP address, its Ethernet IP address, or local host.
- :5000 is the specific networking port assigned to this stream.

## Kill the camera stream or socket
if your socket didn't close properly or the stream didn't end for whatever reason

`sudo killall rpicam-vid`
or
`sudo fuser -k 5000/tcp`

