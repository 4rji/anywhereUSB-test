import cv2
import threading
import time
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import db

NUM_CAMERAS = 8
# Umbral para considerar la cámara "lenta" (caída de fps > 30%)
FPS_DROP_THRESHOLD = 0.30
# Segundos sin frame antes de marcar como desconectada
DISCONNECT_TIMEOUT = 3.0
# Intervalo para guardar métricas en DB
METRICS_SAVE_INTERVAL = 10


@dataclass
class CameraState:
    camera_id: int
    cap: Optional[cv2.VideoCapture] = None
    frame: Optional[bytes] = None
    fps: float = 0.0
    bitrate_kbps: float = 0.0
    status: str = "DESCONECTADA"
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
        # Intentar abrir si no está abierta
        if state.cap is None or not state.cap.isOpened():
            cap = cv2.VideoCapture(state.camera_id, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if cap.isOpened():
                state.cap = cap
                state.last_frame_time = time.time()
                if prev_status != "OK":
                    db.save_event(state.camera_id, "CONEXION", "Cámara conectada")
            else:
                cap.release()
                with state.lock:
                    state.status = "DESCONECTADA"
                    state.fps = 0.0
                    state.bitrate_kbps = 0.0
                    if prev_status != "DESCONECTADA":
                        db.save_event(state.camera_id, "DESCONEXION", "No se pudo abrir")
                        prev_status = "DESCONECTADA"
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
                    state.status = "DESCONECTADA"
                    state.fps = 0.0
                    state.bitrate_kbps = 0.0
                    state.frame = None
                if prev_status != "DESCONECTADA":
                    db.save_event(state.camera_id, "DESCONEXION", f"Sin frames por {DISCONNECT_TIMEOUT}s")
                    prev_status = "DESCONECTADA"
            time.sleep(0.1)
            continue

        state.last_frame_time = now
        encoded = _encode_frame(frame)
        frame_size_kb = len(encoded) / 1024

        # Calcular FPS con ventana deslizante de 30 frames
        frame_times.append(now)
        if len(frame_times) > 30:
            frame_times.pop(0)
        if len(frame_times) >= 2:
            elapsed = frame_times[-1] - frame_times[0]
            fps = (len(frame_times) - 1) / elapsed if elapsed > 0 else 0.0
        else:
            fps = 0.0

        # Establecer baseline en los primeros 60 frames
        if state.baseline_fps == 0.0 and fps > 0 and len(frame_times) >= 30:
            state.baseline_fps = fps

        bitrate = fps * frame_size_kb * 8  # kbps

        # Determinar estado
        if state.baseline_fps > 0 and fps < state.baseline_fps * (1 - FPS_DROP_THRESHOLD):
            status = "LENTO"
        else:
            status = "OK"

        with state.lock:
            state.frame = encoded
            state.fps = round(fps, 1)
            state.bitrate_kbps = round(bitrate, 1)
            state.status = status

        # Guardar evento si cambia el estado
        if status != prev_status and prev_status is not None:
            db.save_event(state.camera_id, f"ESTADO_{status}", f"fps={fps:.1f}")
        prev_status = status

        # Guardar métricas en DB cada METRICS_SAVE_INTERVAL segundos
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
