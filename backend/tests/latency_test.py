import cv2, time
t0 = time.time()
cap = cv2.VideoCapture("rtmp://49.233.71.82:9090/live/test live=1", cv2.CAP_FFMPEG)
t1 = time.time()
print(f"RTMP connect: {round((t1-t0)*1000, 1)} ms")
print(f"opened: {cap.isOpened()}")
if cap.isOpened():
    ok, frame = cap.read()
    t2 = time.time()
    print(f"first frame: {round((t2-t1)*1000, 1)} ms")
    print(f"shape: {frame.shape if ok else 'N/A'}")
else:
    print("no stream - push rtmp://49.233.71.82:9090/live/test first")
cap.release()
