# Camera Connection and Frame Capture

## Overview

The system captures frames from 7 connected USB cameras and serves them in real time through a Flask server. Each camera runs in its own thread so all streams can be captured simultaneously without blocking.

## Physical Connection

- 7 USB cameras connected through AnywhereUSB or directly to the USB port
- Cameras are detected automatically in Windows using sequential indices

## Camera Detection

### Device Indices

In `camera_manager.py`:

```python
NUM_CAMERAS = 7
```

- Each USB camera receives a device index from 0 to 6
- These indices are opened in Windows with `cv2.VideoCapture(index, cv2.CAP_DSHOW)`
- The capture threads are created from `range(NUM_CAMERAS)`
- If you add or replace cameras, update `NUM_CAMERAS` and the camera-opening logic in `camera_manager.py`

## Frame Capture

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FLASK SERVER                        │
├─────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ Thread 0 │  │ Thread 1 │  │ Thread N │ (7 threads)  │
│  │ Camera 0 │  │ Camera 1 │  │ Camera N │              │
│  └──────────┘  └──────────┘  └──────────┘               │
│       ↓             ↓              ↓                    │
│  ┌────────────────────────────────────────┐             │
│  │         Camera State (CameraState)     │             │
│  │  - frame (JPEG bytes)                  │             │
│  │  - fps, bitrate_kbps                   │             │
│  │  - status (OK/SLOW/DISCONNECTED)      │             │
│  └────────────────────────────────────────┘             │
│       ↑             ↑              ↑                    │
│  /stream/0    /stream/1      /stream/N  (MJPEG)        │
│  /api/stats   /api/events              (JSON)          │
└─────────────────────────────────────────────────────────┘
```

### Capture Flow Per Thread

1. **Open the camera**
   ```python
   cap = cv2.VideoCapture(state.device_index, cv2.CAP_DSHOW)
   cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
   cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
   ```
   - Opens the device using its configured index
   - Sets the default resolution to 640x480

2. **Read frames continuously**
   ```python
   ret, frame = state.cap.read()
   ```
   - Runs in a tight loop at maximum speed
   - Reconnects automatically if a read fails

3. **Encode to JPEG**
   ```python
   _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
   encoded = buf.tobytes()
   ```
   - Converts each frame to JPEG to reduce size
   - Uses quality 70 as a balance between clarity and bandwidth

4. **Calculate metrics**
   ```python
   fps = (frames_captured - 1) / elapsed_time
   bitrate = fps * frame_size_kb * 8
   ```
   - FPS is calculated using a sliding window of 30 frames
   - Bitrate is estimated from JPEG frame size

5. **Write metrics to the queue**
   ```python
   _metrics_queue.put(("metric", camera_id, fps, bitrate, status))
   ```
   - Database writes go to a background queue
   - Capture threads never wait on the database

## Browser Streaming

### MJPEG

```
GET /stream/0
─────────────────
Content-Type: multipart/x-mixed-replace; boundary=frame

--frame
Content-Type: image/jpeg

[JPEG BYTES]
--frame
Content-Type: image/jpeg

[JPEG BYTES]
...
```

- Each JPEG frame is sent sequentially
- The browser decodes and displays the stream automatically
- Update rate is roughly 1-11 FPS per camera depending on hardware

### JSON API

```
GET /api/stats
─────────────────────────────────────────
[
  {"id": 0, "fps": 1.0, "bitrate_kbps": 249.4, "status": "OK"},
  {"id": 1, "fps": 10.9, "bitrate_kbps": 602.6, "status": "OK"},
  ...
]
```

- Updates every 2 seconds in the client
- No locks are needed for reads because state access is protected in Python

## Camera Status

| Status | Meaning | Condition |
|--------|---------|-----------|
| OK | Working normally | FPS >= 70% of baseline |
| SLOW | Degraded performance | FPS < 70% of baseline |
| DISCONNECTED | No signal | No frames for 3+ seconds |

## Troubleshooting

### "Black images only"
- Verify that the cameras are connected
- Verify that `NUM_CAMERAS` matches the actual setup
- Physically power-cycle the cameras

### "Fetch pending in the browser"
- Open Developer Tools and check the console for CORS errors
- Make sure `flask-cors` is installed
- Verify with `curl http://localhost:5000/api/stats`

### "Slow performance / low FPS"
- USB cameras share limited bandwidth
- 7 simultaneous cameras can saturate the USB bus
- Reduce resolution or increase JPEG compression if needed

### "Locked database"
- Metric writes are serialized with a database lock
- If problems continue, increase `METRICS_SAVE_INTERVAL`

## Key Files

| File | Purpose |
|------|---------|
| `camera_manager.py` | Frame capture, threads, and camera state |
| `app.py` | Flask server and HTTP routes |
| `db.py` | Metric and event storage |
| `templates/dashboard.html` | Browser UI |
| `README.md` | Project overview and screenshots |

## Example: Adding an 8th Camera

1. Update `NUM_CAMERAS` in `camera_manager.py`:
   ```python
   NUM_CAMERAS = 8
   ```
2. Make sure the hardware exposes the extra camera index.
3. Restart the server.
