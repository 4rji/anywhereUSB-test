import cv2
import threading
import time
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import db

NUM_CAMERAS = 7
# Threshold for considering a camera slow (FPS drop > 30%)
FPS_DROP_THRESHOLD = 0.30
# Seconds without a frame before marking the camera disconnected
DISCONNECT_TIMEOUT = 3.0
# Interval for saving metrics to the database
METRICS_SAVE_INTERVAL = 10


@dataclass
class CameraState:
    camera_id: int
    cap: Optional[cv2.VideoCapture] = None
    frame: Optional[bytes] = None
    fps: float = 0.0
    bitrate_kbps: float = 0.0
    status: str = "DISCONNECTED"
    baseline_fps: float = 0.0
    last_frame_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


cameras: list[CameraState] = [CameraState(camera_id=i) for i in range(NUM_CAMERAS)]


def _encode_frame(frame) -> bytes:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes()


def _camera_thread(state: CameraState):
    last_save = time.time()
    prev_status = None
    frame_times = []

    while True:
        # Try to open the camera if it is not already open
        if state.cap is None or not state.cap.isOpened():
            cap = cv2.VideoCapture(state.camera_id, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if cap.isOpened():
                state.cap = cap
                state.last_frame_time = time.time()
                if prev_status != "OK":
                    db.save_event(state.camera_id, "CONNECTION", "Camera connected")
            else:
                cap.release()
                with state.lock:
                    state.status = "DISCONNECTED"
                    state.fps = 0.0
                    state.bitrate_kbps = 0.0
                    if prev_status != "DISCONNECTED":
                        db.save_event(state.camera_id, "DISCONNECTION", "Unable to open camera")
                        prev_status = "DISCONNECTED"
                time.sleep(2)
                continue

        ret, frame = state.cap.read()
        now = time.time()

        if not ret:
            elapsed_without_frame = now - state.last_frame_time
            if elapsed_without_frame > DISCONNECT_TIMEOUT:
                state.cap.release()
                state.cap = None
                with state.lock:
                    state.status = "DISCONNECTED"
                    state.fps = 0.0
                    state.bitrate_kbps = 0.0
                    state.frame = None
                if prev_status != "DISCONNECTED":
                    db.save_event(state.camera_id, "DISCONNECTION", f"No frames for {DISCONNECT_TIMEOUT}s")
                    prev_status = "DISCONNECTED"
            time.sleep(0.1)
            continue

        state.last_frame_time = now
        encoded = _encode_frame(frame)
        frame_size_kb = len(encoded) / 1024

        # Calculate FPS with a sliding 30-frame window
        frame_times.append(now)
        if len(frame_times) > 30:
            frame_times.pop(0)
        if len(frame_times) >= 2:
            elapsed = frame_times[-1] - frame_times[0]
            fps = (len(frame_times) - 1) / elapsed if elapsed > 0 else 0.0
        else:
            fps = 0.0

        # Establish a baseline after the first 30 stable frames
        if state.baseline_fps == 0.0 and fps > 0 and len(frame_times) >= 30:
            state.baseline_fps = fps

        bitrate = fps * frame_size_kb * 8  # kbps

        # Determine status
        if state.baseline_fps > 0 and fps < state.baseline_fps * (1 - FPS_DROP_THRESHOLD):
            status = "SLOW"
        else:
            status = "OK"

        with state.lock:
            state.frame = encoded
            state.fps = round(fps, 1)
            state.bitrate_kbps = round(bitrate, 1)
            state.status = status

        # Save an event when the status changes
        if status != prev_status and prev_status is not None:
            db.save_event(state.camera_id, f"STATUS_{status}", f"fps={fps:.1f}")
        prev_status = status

        # Save metrics to the database every METRICS_SAVE_INTERVAL seconds
        if now - last_save >= METRICS_SAVE_INTERVAL:
            db.save_metrics(state.camera_id, fps, bitrate, status)
            last_save = now


def start_all():
    db.init_db()
    for state in cameras:
        t = threading.Thread(target=_camera_thread, args=(state,), daemon=True)
        t.start()


def get_frame(camera_id: int) -> Optional[bytes]:
    state = cameras[camera_id]
    with state.lock:
        return state.frame


def get_all_stats() -> list[dict]:
    result = []
    for state in cameras:
        with state.lock:
            result.append({
                "id": state.camera_id,
                "fps": state.fps,
                "bitrate_kbps": state.bitrate_kbps,
                "status": state.status,
            })
    return result
