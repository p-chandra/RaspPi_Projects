import subprocess
import glob
import os

# Find all .h264 files in the images directory
images_dir = os.path.dirname(os.path.abspath(__file__))
h264_files = glob.glob(os.path.join(images_dir, '*.h264'))

if not h264_files:
    print("No .h264 files found in the current directory.")
else:
    print(f"Found {len(h264_files)} .h264 file(s). Starting conversion...")
    for h264_file in h264_files:
        # Generate output filename by replacing .h264 with .mp4
        mp4_file = os.path.splitext(h264_file)[0] + '.mp4'
        print(f"\nConverting: {h264_file} → {mp4_file}")
        
        # Run ffmpeg to convert the file
        result = subprocess.run(['ffmpeg', '-i', h264_file, '-c:v', 'copy', mp4_file])
        
        if result.returncode == 0:
            print(f"✓ Successfully converted {h264_file}")
        else:
            print(f"✗ Failed to convert {h264_file}")
    
    print("\nConversion complete!")