#!/usr/bin/env python3
import argparse
import socket
import threading
import time
from http import server

import cv2


HTML_PAGE = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Jetson Camera Stream</title>
    <style>
      body { font-family: sans-serif; background: #111; color: #eee; margin: 24px; }
      img { max-width: 100%; height: auto; border: 1px solid #444; }
      .meta { margin-top: 12px; color: #bbb; }
    </style>
  </head>
  <body>
    <h1>Jetson Camera Stream</h1>
    <img src="/stream.mjpg" alt="stream">
    <div class="meta">Endpoint: /stream.mjpg</div>
  </body>
</html>
"""


class CameraBuffer:
    def __init__(self, device, width, height, fps, quality):
        self.condition = threading.Condition()
        self.frame = None
        self.running = True
        self.capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not self.capture.isOpened():
            raise RuntimeError(f"Failed to open camera device: {device}")

        self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_FPS, fps)
        self.encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]

        self.worker = threading.Thread(target=self._reader, daemon=True)
        self.worker.start()

    def _reader(self):
        while self.running:
            ok, image = self.capture.read()
            if not ok or image is None:
                time.sleep(0.05)
                continue

            ok, encoded = cv2.imencode(".jpg", image, self.encode_params)
            if not ok:
                continue

            with self.condition:
                self.frame = encoded.tobytes()
                self.condition.notify_all()

    def get_frame(self):
        with self.condition:
            if self.frame is None:
                self.condition.wait(timeout=2.0)
            return self.frame

    def close(self):
        self.running = False
        self.worker.join(timeout=1.0)
        self.capture.release()


class StreamHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            content = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if self.path == "/snapshot.jpg":
            frame = self.server.camera.get_frame()
            if not frame:
                self.send_error(503, "No frame available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return

        if self.path != "/stream.mjpg":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.end_headers()

        try:
            while True:
                frame = self.server.camera.get_frame()
                if not frame:
                    continue
                self.wfile.write(b"--FRAME\r\n")
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(1.0 / max(self.server.fps, 1))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        return


class ThreadedHTTPServer(server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, camera, fps):
        super().__init__(address, handler)
        self.camera = camera
        self.fps = fps


def parse_args():
    parser = argparse.ArgumentParser(description="MJPEG USB camera stream for Jetson Nano")
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--quality", type=int, default=80)
    return parser.parse_args()


def main():
    args = parse_args()
    camera = CameraBuffer(args.device, args.width, args.height, args.fps, args.quality)
    httpd = ThreadedHTTPServer((args.host, args.port), StreamHandler, camera, args.fps)

    hostname = socket.gethostname()
    print(f"Camera stream ready on http://{hostname}:{args.port}/")
    print(f"Camera stream ready on http://127.0.0.1:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        camera.close()


if __name__ == "__main__":
    main()
