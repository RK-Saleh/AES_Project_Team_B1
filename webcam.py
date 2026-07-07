import cv2

# Initialize the camera (0 represents /dev/video0)
cap = cv2.VideoCapture(0)

# Check if the webcam is opened correctly
if not cap.isOpened():
    print("Error: Could not open webcam.")
    exit()

print("Press 'q' to quit the video feed.")

while True:
    # Read a frame from the camera
    ret, frame = cap.read()

    # If frame is read correctly, ret is True
    if not ret:
        print("Error: Can't receive frame. Exiting ...")
        break

    # Display the resulting frame
    cv2.imshow('Raspberry Pi Webcam Feed', frame)

    # Wait for 1 ms and check if the 'q' key is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release the camera and close all windows
cap.release()
cv2.destroyAllWindows()