import cv2

cam = cv2.VideoCapture(1)
#cam = cv2.VideoCapture("/dev/video1") #same thing as above

while True:
   ret, image = cam.read()
   cv2.imshow('ImageTest',image)
   k = cv2.waitKey(1)
   if k != -1:
      break

cv2.imwrite('Raspberry-4-Projects/GPIO/images/testimage.jpg', image)
cam.release()
cv2.destroyAllWindows()
