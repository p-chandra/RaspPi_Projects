import subprocess

# Testing a simple command
subprocess.run(["echo", "Hello from Python"])

# Testing a command with arguments
subprocess.run(["ls", "-l"])

# Run a complex bash string (requires shell=True)
subprocess.run("echo 'Hello from Bash' | grep Hello", shell=True)

# Testing a command and capturing its output.
# Capture_output=True is used to capture the output of the command (which is initially bytes).
# Text=True is used to get the output as a string instead of bytes(b'Hello from Python'). 
result = subprocess.run(["echo", "Hello from Python"], capture_output=True, text=True)
print(result.stdout)

# Testing a command that lists cameras (requires rpicam-hello to be installed)
subprocess.run(["rpicam-hello", "--list-cameras"])

# Run the rpicam-vid command to stream video from the Raspberry Pi camera. This command will start streaming video on TCP port 5000, and it will run indefinitely until you stop it manually (e.g., by pressing Ctrl+C in the terminal).
subprocess.run(["rpicam-vid", "-t", "0", "--inline", "--listen", "-o", "tcp://0.0.0.0:5000"])

# Use VLC to view the stream from the Raspberry Pi camera. This command will open VLC and connect to the stream on TCP port 5000.
#subprocess.run(["vlc", "tcp://localhost:5000"])