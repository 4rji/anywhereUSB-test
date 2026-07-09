import time
from flask import Flask, Response, render_template, jsonify
import camera_manager
import db

app = Flask(__name__)


def _mjpeg_generator(camera_id: int):
    while True:
        frame = camera_manager.get_frame(camera_id)
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        else:
            # Black placeholder when the camera is offline
            import numpy as np
            import cv2
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(
                blank,
                f"CAM {camera_id} - NO SIGNAL",
                (120, 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (80, 80, 80),
                2,
            )
            _, buf = cv2.imencode(".jpg", blank)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
        time.sleep(0.033)  # ~30fps max


@app.route("/")
def index():
    return render_template("dashboard.html", num_cameras=camera_manager.NUM_CAMERAS)


@app.route("/stream/<int:camera_id>")
def stream(camera_id: int):
    if camera_id < 0 or camera_id >= camera_manager.NUM_CAMERAS:
        return "Invalid camera", 404
    return Response(
        _mjpeg_generator(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/stats")
def stats():
    return jsonify(camera_manager.get_all_stats())


@app.route("/api/events")
def events():
    return jsonify(db.get_recent_events(50))


@app.route("/api/history/<int:camera_id>")
def history(camera_id: int):
    return jsonify(db.get_metrics_history(camera_id, 100))


if __name__ == "__main__":
    camera_manager.start_all()
    print("Dashboard available at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
