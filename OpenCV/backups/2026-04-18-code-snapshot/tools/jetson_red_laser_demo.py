#!/usr/bin/env python3
import argparse
import json
import socket
import subprocess
import threading
import time
from http import server
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np


HTML_PAGE = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Jetson Laser Demo + Color Calibration</title>
    <style>
      body { font-family: sans-serif; background: #111; color: #eee; margin: 24px; }
      img { max-width: 100%; height: auto; border: 1px solid #444; display: block; }
      .meta { margin-top: 12px; color: #bbb; }
      .actions { margin: 16px 0; display: flex; flex-wrap: wrap; gap: 8px; }
      button { padding: 8px 12px; border: 1px solid #555; background: #1d1d1d; color: #eee; cursor: pointer; }
      button:hover { background: #2c2c2c; }
      pre { background: #161616; padding: 12px; border: 1px solid #333; overflow: auto; white-space: pre-wrap; }
      code { color: #9fe8a4; }
    </style>
  </head>
  <body>
    <h1>Jetson Laser Demo + Color Calibration</h1>
    <img src="/stream.mjpg" alt="stream">
    <div class="meta" id="meta">Loading status...</div>
    <div class="actions">
      <button onclick="captureSample('white_paper')">采样白纸</button>
      <button onclick="captureSample('black_tape')">采样黑胶布</button>
      <button onclick="captureSample('red_laser')">采样红激光</button>
      <button onclick="captureSample('green_laser')">采样绿激光</button>
      <button onclick="resetSamples()">清空样本</button>
    </div>
    <div class="meta" id="sampleResult">No sample captured yet.</div>
    <h2>Calibration Summary</h2>
    <pre id="calibration">Loading calibration data...</pre>
    <script>
      async function refreshStatus() {
        try {
          const response = await fetch('/status.json');
          const status = await response.json();
          const redPos = status.red && status.red.detected
            ? `x=${status.red.x}, y=${status.red.y}, area=${status.red.area}`
            : 'not found';
          const greenPos = status.green && status.green.detected
            ? `x=${status.green.x}, y=${status.green.y}, area=${status.green.area}`
            : 'not found';
          const blackFrame = status.black_frame && status.black_frame.detected
            ? `area=${status.black_frame.area}`
            : 'not found';
          document.getElementById('meta').innerHTML =
            `FPS: <code>${status.fps.toFixed(1)}</code> | ` +
            `Red laser: <code>${redPos}</code> | ` +
            `Green laser: <code>${greenPos}</code> | ` +
            `Black midline: <code>${blackFrame}</code> | ` +
            `Frame: <code>${status.width}x${status.height}</code>`;
        } catch (error) {
          document.getElementById('meta').textContent = 'Status fetch failed';
        }
      }

      async function refreshCalibration() {
        try {
          const response = await fetch('/calibration.json');
          const data = await response.json();
          document.getElementById('calibration').textContent = JSON.stringify(data, null, 2);
        } catch (error) {
          document.getElementById('calibration').textContent = 'Calibration fetch failed';
        }
      }

      async function captureSample(label) {
        try {
          const response = await fetch(`/sample?label=${label}`, { method: 'POST' });
          const data = await response.json();
          document.getElementById('sampleResult').textContent =
            `Captured ${label}: ROI mean BGR=${data.sample.roi_mean_bgr.join(', ')} | hotspot mean BGR=${data.sample.hotspot_mean_bgr.join(', ')}`;
          refreshCalibration();
        } catch (error) {
          document.getElementById('sampleResult').textContent = `Capture failed for ${label}`;
        }
      }

      async function resetSamples() {
        try {
          await fetch('/reset_samples', { method: 'POST' });
          document.getElementById('sampleResult').textContent = 'Samples cleared.';
          refreshCalibration();
        } catch (error) {
          document.getElementById('sampleResult').textContent = 'Failed to clear samples.';
        }
      }

      refreshStatus();
      refreshCalibration();
      setInterval(refreshStatus, 250);
      setInterval(refreshCalibration, 1000);
    </script>
  </body>
</html>
"""


class LaserTracker:
    def __init__(self, args):
        self.args = args
        self.condition = threading.Condition()
        self.frame_bytes = None
        self.raw_frame = None
        self.status = {
            "detected": False,
            "x": None,
            "y": None,
            "area": 0,
            "red": {"detected": False, "x": None, "y": None, "area": 0},
            "green": {"detected": False, "x": None, "y": None, "area": 0},
            "black_frame": {"detected": False, "area": 0, "corners": []},
            "fps": 0.0,
            "width": args.width,
            "height": args.height,
            "timestamp": time.time(),
        }
        self.samples_lock = threading.Lock()
        self.samples = {label: [] for label in self.args.sample_labels}
        self.sample_seq = 0
        self.running = True
        self._configure_camera_controls()
        self.capture = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
        if not self.capture.isOpened():
            raise RuntimeError(f"Failed to open camera device: {args.device}")

        self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        self.capture.set(cv2.CAP_PROP_FPS, args.fps)

        self.encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), args.quality]
        self.frame_index = 0
        self.black_frame_detection = None
        self.worker = threading.Thread(target=self._reader, daemon=True)
        self.worker.start()

    def _get_center_roi_bounds(self, frame):
        h, w = frame.shape[:2]
        size = min(self.args.sample_roi_size, h, w)
        half = size // 2
        cx = w // 2
        cy = h // 2
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(w, x0 + size)
        y1 = min(h, y0 + size)
        return x0, y0, x1, y1

    def _scale_corners(self, corners, scale):
        pts = np.array(corners, dtype=np.float32)
        center = pts.mean(axis=0, keepdims=True)
        return center + (pts - center) * float(scale)

    def _order_quad(self, corners):
        pts = np.array(corners, dtype=np.float32).reshape(-1, 2)
        center = pts.mean(axis=0, keepdims=True)
        angles = np.arctan2(pts[:, 1] - center[0, 1], pts[:, 0] - center[0, 0])
        pts = pts[np.argsort(angles)]
        start = int(np.argmin(pts[:, 0] + pts[:, 1]))
        return np.roll(pts, -start, axis=0)

    def _quad_size(self, corners):
        pts = self._order_quad(corners)
        width = max(
            np.linalg.norm(pts[1] - pts[0]),
            np.linalg.norm(pts[2] - pts[3]),
        )
        height = max(
            np.linalg.norm(pts[3] - pts[0]),
            np.linalg.norm(pts[2] - pts[1]),
        )
        return max(int(round(width)), 32), max(int(round(height)), 32)

    def _corners_to_roi(self, corners, frame_shape, pad=0, scale=1.0):
        h, w = frame_shape[:2]
        pts = self._scale_corners(corners, scale)
        x0 = max(0, int(np.floor(pts[:, 0].min())) - int(pad))
        y0 = max(0, int(np.floor(pts[:, 1].min())) - int(pad))
        x1 = min(w, int(np.ceil(pts[:, 0].max())) + int(pad))
        y1 = min(h, int(np.ceil(pts[:, 1].max())) + int(pad))
        return x0, y0, x1, y1

    def _offset_detection(self, detection, x0, y0):
        if detection is None:
            return None
        shifted = dict(detection)
        shifted["x"] += int(x0)
        shifted["y"] += int(y0)
        return shifted

    def _get_laser_search_roi(self, frame_shape):
        h, w = frame_shape[:2]
        black = self.black_frame_detection
        if not black or not black.get("detected") or not black.get("corners"):
            return 0, 0, w, h
        return self._corners_to_roi(
            black["corners"],
            frame_shape,
            pad=self.args.laser_roi_pad,
            scale=self.args.laser_roi_scale,
        )

    def _quad_center(self, corners):
        pts = np.array(corners, dtype=np.float32).reshape(-1, 2)
        center = pts.mean(axis=0)
        return float(center[0]), float(center[1])

    def _detect_inner_box_from_outer(self, frame, outer_box):
        ordered_outer = self._order_quad(outer_box).astype(np.float32)
        warp_w, warp_h = self._quad_size(ordered_outer)
        dst = np.array(
            [
                [0.0, 0.0],
                [warp_w - 1.0, 0.0],
                [warp_w - 1.0, warp_h - 1.0],
                [0.0, warp_h - 1.0],
            ],
            dtype=np.float32,
        )
        transform = cv2.getPerspectiveTransform(ordered_outer, dst)
        inverse_transform = cv2.getPerspectiveTransform(dst, ordered_outer)
        warped = cv2.warpPerspective(frame, transform, (warp_w, warp_h))
        if warped.size == 0:
            return None

        warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        warped_gray = cv2.GaussianBlur(warped_gray, (5, 5), 0)
        otsu_value, _ = cv2.threshold(
            warped_gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        white_threshold = max(float(self.args.white_l_threshold), float(otsu_value))
        _, white_mask = cv2.threshold(
            warped_gray,
            white_threshold,
            255,
            cv2.THRESH_BINARY,
        )
        if self.args.white_close_kernel > 1:
            kernel = np.ones((self.args.white_close_kernel, self.args.white_close_kernel), np.uint8)
            white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)

        margin_x = max(2, int(round(warp_w * self.args.white_border_margin_ratio)))
        margin_y = max(2, int(round(warp_h * self.args.white_border_margin_ratio)))
        white_mask[:margin_y, :] = 0
        white_mask[-margin_y:, :] = 0
        white_mask[:, :margin_x] = 0
        white_mask[:, -margin_x:] = 0

        contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        warp_area = float(warp_w * warp_h)
        outer_aspect = max(float(warp_w), float(warp_h)) / max(1.0, min(float(warp_w), float(warp_h)))
        best_inner = None
        best_score = -1.0
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < warp_area * self.args.white_min_relative_area:
                continue
            if area > warp_area * self.args.white_max_relative_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w < 8 or h < 8:
                continue

            aspect = max(float(w), float(h)) / max(1.0, min(float(w), float(h)))
            if aspect < outer_aspect * 0.75 or aspect > outer_aspect * 1.35:
                continue

            cx = x + (w * 0.5)
            cy = y + (h * 0.5)
            center_dist = np.hypot(cx - (warp_w * 0.5), cy - (warp_h * 0.5)) / max(
                np.hypot(warp_w, warp_h),
                1.0,
            )
            score = area / (1.0 + (3.0 * center_dist))
            if score <= best_score:
                continue

            inner_quad = np.array(
                [
                    [x, y],
                    [x + w - 1, y],
                    [x + w - 1, y + h - 1],
                    [x, y + h - 1],
                ],
                dtype=np.float32,
            )
            inner_global = cv2.perspectiveTransform(inner_quad.reshape(1, -1, 2), inverse_transform)[0]
            best_inner = self._order_quad(inner_global)
            best_score = score

        return best_inner

    def _compute_sample(self, frame, label):
        x0, y0, x1, y1 = self._get_center_roi_bounds(frame)
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            raise RuntimeError("Sample ROI is empty")

        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        roi_bgr_mean = roi.reshape(-1, 3).mean(axis=0)
        roi_lab_mean = lab.reshape(-1, 3).mean(axis=0)
        roi_hsv_mean = hsv.reshape(-1, 3).mean(axis=0)

        l_channel = lab[:, :, 0].astype(np.float32)
        flat_l = l_channel.reshape(-1)
        hotspot_count = max(8, int(flat_l.size * self.args.hotspot_ratio))
        hotspot_idx = np.argpartition(flat_l, -hotspot_count)[-hotspot_count:]

        flat_bgr = roi.reshape(-1, 3).astype(np.float32)
        flat_lab = lab.reshape(-1, 3).astype(np.float32)
        hotspot_bgr = flat_bgr[hotspot_idx]
        hotspot_lab = flat_lab[hotspot_idx]

        hotspot_b = hotspot_bgr[:, 0]
        hotspot_g = hotspot_bgr[:, 1]
        hotspot_r = hotspot_bgr[:, 2]
        hotspot_red_score = (2.0 * hotspot_r) - hotspot_g - hotspot_b
        hotspot_green_score = (2.0 * hotspot_g) - hotspot_r - hotspot_b

        sample = {
            "label": label,
            "timestamp": time.time(),
            "roi_bounds": [int(x0), int(y0), int(x1), int(y1)],
            "roi_mean_bgr": [round(float(v), 2) for v in roi_bgr_mean],
            "roi_mean_lab": [round(float(v), 2) for v in roi_lab_mean],
            "roi_mean_hsv": [round(float(v), 2) for v in roi_hsv_mean],
            "hotspot_count": int(hotspot_count),
            "hotspot_mean_bgr": [round(float(v), 2) for v in hotspot_bgr.mean(axis=0)],
            "hotspot_mean_lab": [round(float(v), 2) for v in hotspot_lab.mean(axis=0)],
            "hotspot_red_score_mean": round(float(hotspot_red_score.mean()), 2),
            "hotspot_red_score_p10": round(float(np.percentile(hotspot_red_score, 10)), 2),
            "hotspot_green_score_mean": round(float(hotspot_green_score.mean()), 2),
            "hotspot_green_score_p10": round(float(np.percentile(hotspot_green_score, 10)), 2),
            "hotspot_red_channel_p10": round(float(np.percentile(hotspot_r, 10)), 2),
            "hotspot_green_channel_p10": round(float(np.percentile(hotspot_g, 10)), 2),
            "hotspot_red_minus_green_p10": round(float(np.percentile(hotspot_r - hotspot_g, 10)), 2),
            "hotspot_red_minus_blue_p10": round(float(np.percentile(hotspot_r - hotspot_b, 10)), 2),
            "hotspot_green_minus_red_p10": round(float(np.percentile(hotspot_g - hotspot_r, 10)), 2),
            "hotspot_green_minus_blue_p10": round(float(np.percentile(hotspot_g - hotspot_b, 10)), 2),
            "hotspot_a_mean": round(float(hotspot_lab[:, 1].mean()), 2),
            "hotspot_b_mean": round(float(hotspot_lab[:, 2].mean()), 2),
            "hotspot_l_mean": round(float(hotspot_lab[:, 0].mean()), 2),
        }
        return sample

    def capture_sample(self, label):
        if label not in self.samples:
            raise ValueError(f"Unsupported label: {label}")
        with self.condition:
            frame = None if self.raw_frame is None else self.raw_frame.copy()
        if frame is None:
            raise RuntimeError("No frame available")

        sample = self._compute_sample(frame, label)
        with self.samples_lock:
            self.sample_seq += 1
            sample["id"] = self.sample_seq
            self.samples[label].append(sample)
        return sample

    def reset_samples(self):
        with self.samples_lock:
            self.samples = {label: [] for label in self.args.sample_labels}
            self.sample_seq = 0

    def _mad_mask(self, values, zmax=3.5):
        arr = np.array(values, dtype=np.float32)
        if arr.size < 3:
            return np.ones(arr.shape, dtype=bool)
        median = np.median(arr)
        mad = np.median(np.abs(arr - median))
        if mad < 1e-6:
            return np.ones(arr.shape, dtype=bool)
        robust_z = 0.6745 * (arr - median) / mad
        return np.abs(robust_z) <= zmax

    def _robust_subset(self, samples, label):
        if not samples:
            return [], []

        if label == "red_laser":
            prelim = [
                s
                for s in samples
                if s["hotspot_red_score_mean"] > 0
                and s["hotspot_green_score_mean"] < 0
                and s["hotspot_a_mean"] > 128
            ]
            features = [
                "hotspot_red_score_mean",
                "hotspot_red_score_p10",
                "hotspot_red_channel_p10",
                "hotspot_a_mean",
            ]
        elif label == "green_laser":
            prelim = [
                s
                for s in samples
                if s["hotspot_green_score_mean"] > 0
                and s["hotspot_red_score_mean"] < 0
                and s["hotspot_a_mean"] < 128
            ]
            features = [
                "hotspot_green_score_mean",
                "hotspot_green_score_p10",
                "hotspot_green_channel_p10",
                "hotspot_a_mean",
            ]
        elif label == "white_paper":
            prelim = [s for s in samples if s["roi_mean_lab"][0] >= 80]
            features = ["hotspot_l_mean"]
        elif label == "black_tape":
            prelim = [s for s in samples if s["roi_mean_lab"][0] <= 140]
            features = ["roi_mean_lab[0]"]
        else:
            prelim = list(samples)
            features = []

        if len(prelim) < 3 or not features:
            prelim_ids = {s["id"] for s in prelim}
            rejected = [s for s in samples if s["id"] not in prelim_ids]
            return prelim, rejected

        votes = np.zeros(len(prelim), dtype=np.int32)
        for feature in features:
            if feature == "roi_mean_lab[0]":
                values = [float(s["roi_mean_lab"][0]) for s in prelim]
            else:
                values = [float(s[feature]) for s in prelim]
            votes += self._mad_mask(values).astype(np.int32)

        min_votes = max(1, len(features) - 1)
        kept = [sample for sample, vote in zip(prelim, votes) if vote >= min_votes]
        kept_ids = {s["id"] for s in kept}
        rejected = [s for s in samples if s["id"] not in kept_ids]
        return kept, rejected

    def _safe_percentile(self, values, q):
        if not values:
            return None
        return round(float(np.percentile(np.array(values, dtype=np.float32), q)), 2)

    def get_calibration_summary(self):
        with self.samples_lock:
            samples = {label: list(items) for label, items in self.samples.items()}

        counts = {label: len(items) for label, items in samples.items()}
        latest = {label: (items[-1] if items else None) for label, items in samples.items()}
        filtered = {}
        rejected = {}
        suggestions = {}

        for label, items in samples.items():
            kept, dropped = self._robust_subset(items, label)
            filtered[label] = kept
            rejected[label] = dropped

        red = filtered["red_laser"]
        green = filtered["green_laser"]
        white = filtered["white_paper"]
        black = filtered["black_tape"]

        if red:
            raw_score = self._safe_percentile([s["hotspot_red_score_p10"] for s in red], 10)
            raw_min_red = self._safe_percentile([s["hotspot_red_channel_p10"] for s in red], 10)
            raw_delta_rg = self._safe_percentile([s["hotspot_red_minus_green_p10"] for s in red], 10)
            raw_delta_rb = self._safe_percentile([s["hotspot_red_minus_blue_p10"] for s in red], 10)
            suggestions["red_detector"] = {
                "score_threshold": raw_score,
                "min_red": raw_min_red,
                "min_delta_rg": max(
                    0.0,
                    raw_delta_rg or 0.0,
                ),
                "min_delta_rb": max(
                    0.0,
                    raw_delta_rb or 0.0,
                ),
                "lab_a_mean": self._safe_percentile([s["hotspot_a_mean"] for s in red], 50),
                # Hotspot quantiles are a good lower bound for calibration, but
                # runtime detection needs extra margin so the halo pixels are kept.
                "runtime_score_threshold": max(4.0, round((raw_score or 0.0) - 1.0, 2)),
                "runtime_min_red": max(140.0, round((raw_min_red or 0.0) - 60.0, 2)),
                "runtime_min_delta_rg": max(2.0, round((raw_delta_rg or 0.0) - 1.0, 2)),
                "runtime_min_delta_rb": max(0.0, round((raw_delta_rb or 0.0) - 1.0, 2)),
                "used_sample_ids": [s["id"] for s in red],
            }

        if green:
            raw_score = self._safe_percentile([s["hotspot_green_score_p10"] for s in green], 10)
            raw_min_green = self._safe_percentile([s["hotspot_green_channel_p10"] for s in green], 10)
            raw_delta_gr = self._safe_percentile([s["hotspot_green_minus_red_p10"] for s in green], 10)
            raw_delta_gb = self._safe_percentile([s["hotspot_green_minus_blue_p10"] for s in green], 10)
            raw_a_mean = self._safe_percentile([s["hotspot_a_mean"] for s in green], 50)
            suggestions["green_detector"] = {
                "score_threshold": raw_score,
                "min_green": raw_min_green,
                "min_delta_gr": raw_delta_gr,
                "min_delta_gb": raw_delta_gb,
                "lab_a_mean": raw_a_mean,
                "runtime_score_threshold": min(-4.0, round((raw_score or 0.0) - 2.0, 2)),
                "runtime_min_green": max(150.0, round((raw_min_green or 0.0) - 40.0, 2)),
                "runtime_min_delta_gr": max(-4.0, round((raw_delta_gr or 0.0) - 2.0, 2)),
                "runtime_min_delta_gb": max(-4.0, round((raw_delta_gb or 0.0) - 2.0, 2)),
                "runtime_lab_a_max": min(122.0, round((raw_a_mean or 128.0) + 10.0, 2)),
                "used_sample_ids": [s["id"] for s in green],
            }

        if white:
            suggestions["white_background"] = {
                "lab_l_mean": self._safe_percentile([s["roi_mean_lab"][0] for s in white], 50),
                "lab_a_mean": self._safe_percentile([s["roi_mean_lab"][1] for s in white], 50),
                "lab_b_mean": self._safe_percentile([s["roi_mean_lab"][2] for s in white], 50),
                "used_sample_ids": [s["id"] for s in white],
            }

        if black:
            suggestions["black_tape"] = {
                "lab_l_mean": self._safe_percentile([s["roi_mean_lab"][0] for s in black], 50),
                "hsv_v_mean": self._safe_percentile([s["roi_mean_hsv"][2] for s in black], 50),
                "used_sample_ids": [s["id"] for s in black],
            }

        return {
            "counts": counts,
            "accepted_counts": {label: len(items) for label, items in filtered.items()},
            "rejected_counts": {label: len(items) for label, items in rejected.items()},
            "rejected_ids": {label: [s["id"] for s in items] for label, items in rejected.items()},
            "latest": latest,
            "suggestions": suggestions,
        }

    def _run_v4l2(self, *extra):
        cmd = ["v4l2-ctl", "-d", self.args.device, *extra]
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

    def _configure_camera_controls(self):
        if self.args.manual_exposure is not None:
            self._run_v4l2("-c", "exposure_auto=1")
            self._run_v4l2("-c", f"exposure_absolute={self.args.manual_exposure}")
        if not self.args.keep_auto_white_balance:
            self._run_v4l2("-c", "white_balance_temperature_auto=0")
        if self.args.white_balance is not None:
            self._run_v4l2("-c", f"white_balance_temperature={self.args.white_balance}")
        if self.args.gain is not None:
            self._run_v4l2("-c", f"gain={self.args.gain}")
        if self.args.power_line_frequency is not None:
            self._run_v4l2("-c", f"power_line_frequency={self.args.power_line_frequency}")

    def _pick_best_component(self, frame, raw_mask, metric, color_name):
        mask_u8 = (raw_mask.astype(np.uint8) * 255)
        if self.args.morph_kernel > 1:
            kernel = np.ones((self.args.morph_kernel, self.args.morph_kernel), np.uint8)
            mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
            mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_DILATE, kernel)

        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)

        best = None
        best_peak = -1.0
        best_mean = -1.0
        for label in range(1, count):
            component_mask = labels == label
            raw_component_mask = component_mask & raw_mask
            raw_area = int(np.count_nonzero(raw_component_mask))
            if raw_area < self.args.min_area or raw_area > self.args.max_area:
                continue

            left = stats[label, cv2.CC_STAT_LEFT]
            top = stats[label, cv2.CC_STAT_TOP]
            width = stats[label, cv2.CC_STAT_WIDTH]
            height = stats[label, cv2.CC_STAT_HEIGHT]
            crop = frame[top : top + height, left : left + width]
            crop_mask = raw_component_mask[top : top + height, left : left + width]
            if crop.size == 0 or not np.any(crop_mask):
                continue

            lab_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
            a_mean = float(lab_crop[:, :, 1][crop_mask].mean())
            if color_name == "red" and a_mean < self.args.red_lab_a_min:
                continue
            if color_name == "green" and a_mean > self.args.green_lab_a_max:
                continue

            raw_metric = metric[raw_component_mask].astype(np.float32)
            if raw_metric.size == 0:
                continue

            peak_score = float(raw_metric.max())
            mean_score = float(raw_metric.mean())
            if peak_score < best_peak or (peak_score == best_peak and mean_score <= best_mean):
                continue

            ys, xs = np.where(raw_component_mask)
            weights = np.maximum(raw_metric, 1.0)
            x = int(round(float((xs * weights).sum() / weights.sum())))
            y = int(round(float((ys * weights).sum() / weights.sum())))

            best_peak = peak_score
            best_mean = mean_score
            best = {
                "x": x,
                "y": y,
                "area": raw_area,
                "peak": peak_score,
                "mean": mean_score,
                "lab_a_mean": round(a_mean, 2),
            }

        if best is None:
            return None, mask_u8

        return {"x": best["x"], "y": best["y"], "area": best["area"]}, mask_u8

    def _detect_lasers(self, frame):
        roi_x0, roi_y0, roi_x1, roi_y1 = self._get_laser_search_roi(frame.shape)
        work = frame[roi_y0:roi_y1, roi_x0:roi_x1]
        if work.size == 0:
            work = frame
            roi_x0 = roi_y0 = 0

        bgr = work.astype(np.int16)
        blue = bgr[:, :, 0]
        green = bgr[:, :, 1]
        red = bgr[:, :, 2]
        red_score = (2 * red) - green - blue
        green_score = (2 * green) - red - blue

        red_mask = (
            (red_score >= self.args.score_threshold)
            & (red >= self.args.min_red)
            & ((red - green) >= self.args.min_delta_rg)
            & ((red - blue) >= self.args.min_delta_rb)
        )
        green_mask = (
            (green_score >= self.args.green_score_threshold)
            & (green >= self.args.min_green)
            & ((green - red) >= self.args.min_delta_gr)
            & ((green - blue) >= self.args.min_delta_gb)
        )

        red_metric = red_score.astype(np.float32)
        green_metric = green.astype(np.float32)

        red_detection, _ = self._pick_best_component(work, red_mask, red_metric, "red")
        green_detection, _ = self._pick_best_component(work, green_mask, green_metric, "green")
        return (
            self._offset_detection(red_detection, roi_x0, roi_y0),
            self._offset_detection(green_detection, roi_x0, roi_y0),
        )

    def _detect_black_frame(self, frame):
        full_refresh = (
            self.black_frame_detection is None
            or not self.black_frame_detection.get("detected")
            or not self.black_frame_detection.get("corners")
            or self.frame_index % max(self.args.black_full_refresh_interval, 1) == 0
        )
        if full_refresh:
            roi_x0, roi_y0, roi_x1, roi_y1 = 0, 0, frame.shape[1], frame.shape[0]
        else:
            roi_x0, roi_y0, roi_x1, roi_y1 = self._corners_to_roi(
                self.black_frame_detection["corners"],
                frame.shape,
                pad=self.args.black_roi_pad,
                scale=self.args.black_roi_scale,
            )

        crop = frame[roi_y0:roi_y1, roi_x0:roi_x1]
        if crop.size == 0:
            crop = frame
            roi_x0 = roi_y0 = 0

        scale = float(self.args.black_detect_scale)
        if scale <= 0.0 or scale > 1.0:
            scale = 1.0

        if scale < 0.999:
            work = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            work = crop

        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(
            gray,
            int(self.args.black_l_threshold),
            255,
            cv2.THRESH_BINARY_INV,
        )

        if self.args.black_close_kernel > 1:
            kernel = np.ones((self.args.black_close_kernel, self.args.black_close_kernel), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        if self.args.black_dilate_kernel > 1:
            kernel = np.ones((self.args.black_dilate_kernel, self.args.black_dilate_kernel), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = float(mask.shape[0] * mask.shape[1])
        best = None
        best_score = -1.0
        if self.black_frame_detection and self.black_frame_detection.get("detected") and self.black_frame_detection.get("corners"):
            ref_cx, ref_cy = self._quad_center(self.black_frame_detection["corners"])
        else:
            ref_cx = frame.shape[1] * 0.5
            ref_cy = frame.shape[0] * 0.5

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < frame_area * self.args.black_min_area_ratio:
                continue
            if area > frame_area * self.args.black_max_area_ratio:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue

            approx = cv2.approxPolyDP(contour, self.args.black_poly_epsilon * perimeter, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                box = approx[:, 0, :]
            else:
                rect = cv2.minAreaRect(contour)
                box = cv2.boxPoints(rect)

            box = np.array(box, dtype=np.float32)
            rect_area = float(cv2.contourArea(box))
            if rect_area <= 1.0:
                continue

            fill_ratio = area / rect_area
            if fill_ratio < self.args.black_min_fill_ratio:
                continue

            inner_box = self._scale_corners(box, self.args.black_inner_scale)
            inner_box_i32 = np.round(inner_box).astype(np.int32)
            inner_mask = np.zeros(mask.shape, dtype=np.uint8)
            cv2.fillConvexPoly(inner_mask, inner_box_i32, 255)
            inner_pixels = gray[inner_mask == 255]
            if inner_pixels.size == 0:
                continue

            inner_l_mean = float(inner_pixels.mean())
            if inner_l_mean < self.args.black_inner_l_min:
                continue

            score = area * min(fill_ratio, 1.0)
            if score <= best_score:
                continue

            if scale < 0.999:
                scaled_box = np.round(box / scale).astype(np.int32)
            else:
                scaled_box = np.round(box).astype(np.int32)
            scaled_box[:, 0] += int(roi_x0)
            scaled_box[:, 1] += int(roi_y0)

            outer_box = self._order_quad(scaled_box)
            side_a = float(np.linalg.norm(outer_box[1] - outer_box[0]))
            side_b = float(np.linalg.norm(outer_box[2] - outer_box[1]))
            short_side = max(1.0, min(side_a, side_b))
            aspect_ratio = max(side_a, side_b) / short_side
            if aspect_ratio < self.args.black_min_aspect or aspect_ratio > self.args.black_max_aspect:
                continue
            cand_cx, cand_cy = self._quad_center(outer_box)
            center_dist = np.hypot(cand_cx - ref_cx, cand_cy - ref_cy) / max(np.hypot(frame.shape[1], frame.shape[0]), 1.0)
            if not full_refresh and center_dist > self.args.black_max_track_shift:
                continue
            inner_box_global = self._detect_inner_box_from_outer(frame, outer_box)
            if inner_box_global is not None:
                center_box = 0.5 * (outer_box + inner_box_global)
            else:
                center_box = self._scale_corners(outer_box, self.args.black_midline_scale)

            candidate_score = score / (1.0 + self.args.black_center_penalty * center_dist)
            if inner_box_global is not None:
                candidate_score *= 1.12
            if candidate_score <= best_score:
                continue

            best_score = candidate_score
            best = {
                "detected": True,
                "area": int(round(cv2.contourArea(center_box))),
                "corners": np.round(center_box).astype(np.int32).tolist(),
                "outer_corners": np.round(outer_box).astype(np.int32).tolist(),
                "inner_corners": [] if inner_box_global is None else np.round(inner_box_global).astype(np.int32).tolist(),
                "aspect_ratio": round(aspect_ratio, 3),
                "center_dist": round(float(center_dist), 3),
                "fill_ratio": round(float(fill_ratio), 3),
                "inner_l_mean": round(inner_l_mean, 2),
            }

        if best is None:
            return {"detected": False, "area": 0, "corners": []}

        return best

    def _overlay(self, frame, red_detection, green_detection, fps):
        h, w = frame.shape[:2]
        cv2.putText(
            frame,
            f"FPS: {fps:.1f}",
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        if red_detection:
            x = red_detection["x"]
            y = red_detection["y"]
            cv2.circle(frame, (x, y), 10, (0, 0, 255), 2)
            cv2.line(frame, (x - 15, y), (x + 15, y), (0, 0, 255), 1)
            cv2.line(frame, (x, y - 15), (x, y + 15), (0, 0, 255), 1)
            cv2.putText(
                frame,
                f"RED: ({x}, {y}) area={red_detection['area']}",
                (12, 58),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        else:
            cv2.putText(
                frame,
                "RED: not found",
                (12, 58),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )

        if green_detection:
            x = green_detection["x"]
            y = green_detection["y"]
            cv2.circle(frame, (x, y), 10, (0, 255, 0), 2)
            cv2.line(frame, (x - 15, y), (x + 15, y), (0, 255, 0), 1)
            cv2.line(frame, (x, y - 15), (x, y + 15), (0, 255, 0), 1)
            cv2.putText(
                frame,
                f"GREEN: ({x}, {y}) area={green_detection['area']}",
                (12, 88),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        else:
            cv2.putText(
                frame,
                "GREEN: not found",
                (12, 88),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 160, 0),
                2,
                cv2.LINE_AA,
            )

        black_frame = self.black_frame_detection
        if black_frame and black_frame.get("detected") and black_frame.get("corners"):
            if black_frame.get("outer_corners"):
                outer = np.array(black_frame["outer_corners"], dtype=np.int32).reshape(-1, 1, 2)
                cv2.polylines(frame, [outer], True, (0, 165, 255), 1)
            if black_frame.get("inner_corners"):
                inner = np.array(black_frame["inner_corners"], dtype=np.int32).reshape(-1, 1, 2)
                cv2.polylines(frame, [inner], True, (220, 220, 220), 1)
            corners = np.array(black_frame["corners"], dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(frame, [corners], True, (255, 200, 0), 2)
            cv2.putText(
                frame,
                f"BLACK MIDLINE: area={black_frame['area']}",
                (12, 118),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 200, 0),
                2,
                cv2.LINE_AA,
            )
        else:
            cv2.putText(
                frame,
                "BLACK MIDLINE: not found",
                (12, 118),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (120, 120, 0),
                2,
                cv2.LINE_AA,
            )

        x0, y0, x1, y1 = self._get_center_roi_bounds(frame)
        cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 0), 1)
        cv2.putText(
            frame,
            "Sample ROI",
            (x0, max(18, y0 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 0),
            1,
            cv2.LINE_AA,
        )

        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (80, 80, 80), 1)
        return frame

    def _reader(self):
        last_time = time.perf_counter()
        fps = 0.0

        while self.running:
            ok, frame = self.capture.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue

            now = time.perf_counter()
            delta = max(now - last_time, 1e-6)
            current_fps = 1.0 / delta
            fps = current_fps if fps == 0.0 else (0.9 * fps + 0.1 * current_fps)
            last_time = now

            self.frame_index += 1
            if (
                self.black_frame_detection is None
                or self.frame_index % max(self.args.black_detect_interval, 1) == 0
            ):
                self.black_frame_detection = self._detect_black_frame(frame)
            red_detection, green_detection = self._detect_lasers(frame)
            overlay = self._overlay(frame.copy(), red_detection, green_detection, fps)

            ok, encoded = cv2.imencode(".jpg", overlay, self.encode_params)
            if not ok:
                continue

            status = {
                "detected": bool(red_detection),
                "x": red_detection["x"] if red_detection else None,
                "y": red_detection["y"] if red_detection else None,
                "area": red_detection["area"] if red_detection else 0,
                "red": {
                    "detected": bool(red_detection),
                    "x": red_detection["x"] if red_detection else None,
                    "y": red_detection["y"] if red_detection else None,
                    "area": red_detection["area"] if red_detection else 0,
                },
                "green": {
                    "detected": bool(green_detection),
                    "x": green_detection["x"] if green_detection else None,
                    "y": green_detection["y"] if green_detection else None,
                    "area": green_detection["area"] if green_detection else 0,
                },
                "black_frame": dict(self.black_frame_detection or {"detected": False, "area": 0, "corners": []}),
                "fps": float(fps),
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "sample_roi": list(self._get_center_roi_bounds(frame)),
                "timestamp": time.time(),
            }

            with self.condition:
                self.raw_frame = frame.copy()
                self.frame_bytes = encoded.tobytes()
                self.status = status
                self.condition.notify_all()

    def get_frame(self):
        with self.condition:
            if self.frame_bytes is None:
                self.condition.wait(timeout=2.0)
            return self.frame_bytes

    def get_status(self):
        with self.condition:
            return dict(self.status)

    def close(self):
        self.running = False
        self.worker.join(timeout=1.0)
        self.capture.release()


class DemoHandler(server.BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            content = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            return
        if parsed.path == "/snapshot.jpg":
            frame = self.server.tracker.get_frame()
            if not frame:
                self.send_error(503, "No frame available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            return
        if parsed.path in ("/status.json", "/calibration.json"):
            payload = (
                self.server.tracker.get_status()
                if parsed.path == "/status.json"
                else self.server.tracker.get_calibration_summary()
            )
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/sample":
            label = parse_qs(parsed.query).get("label", [None])[0]
            if not label:
                self._send_json({"error": "missing label"}, status=400)
                return
            try:
                sample = self.server.tracker.capture_sample(label)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=503)
                return
            self._send_json({"ok": True, "sample": sample})
            return

        if parsed.path == "/reset_samples":
            self.server.tracker.reset_samples()
            self._send_json({"ok": True})
            return

        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            content = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path == "/status.json":
            self._send_json(self.server.tracker.get_status())
            return

        if parsed.path == "/calibration.json":
            self._send_json(self.server.tracker.get_calibration_summary())
            return

        if parsed.path == "/snapshot.jpg":
            frame = self.server.tracker.get_frame()
            if not frame:
                self.send_error(503, "No frame available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return

        if parsed.path != "/stream.mjpg":
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
                frame = self.server.tracker.get_frame()
                if not frame:
                    continue
                self.wfile.write(b"--FRAME\r\n")
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(1.0 / max(self.server.stream_fps, 1))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        return


class DemoServer(server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, tracker, stream_fps):
        super().__init__(address, handler)
        self.tracker = tracker
        self.stream_fps = stream_fps


def parse_args():
    parser = argparse.ArgumentParser(description="Red laser detection demo for Jetson Nano")
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--quality", type=int, default=80)
    parser.add_argument("--manual-exposure", type=int, default=150)
    parser.add_argument("--keep-auto-white-balance", action="store_true")
    parser.add_argument("--white-balance", type=int, default=4000)
    parser.add_argument("--gain", type=int, default=0)
    parser.add_argument("--power-line-frequency", type=int, default=1)
    parser.add_argument("--score-threshold", type=int, default=6)
    parser.add_argument("--min-red", type=int, default=170)
    parser.add_argument("--min-delta", type=int, default=None)
    parser.add_argument("--min-delta-rg", type=int, default=4)
    parser.add_argument("--min-delta-rb", type=int, default=0)
    parser.add_argument("--red-lab-a-min", type=int, default=130)
    parser.add_argument("--green-score-threshold", type=int, default=-6)
    parser.add_argument("--min-green", type=int, default=160)
    parser.add_argument("--min-delta-gr", type=int, default=-2)
    parser.add_argument("--min-delta-gb", type=int, default=-2)
    parser.add_argument("--green-lab-a-max", type=int, default=122)
    parser.add_argument("--min-area", type=int, default=1)
    parser.add_argument("--max-area", type=int, default=800)
    parser.add_argument("--morph-kernel", type=int, default=3)
    parser.add_argument("--laser-roi-scale", type=float, default=0.86)
    parser.add_argument("--laser-roi-pad", type=int, default=12)
    parser.add_argument("--black-detect-interval", type=int, default=8)
    parser.add_argument("--black-full-refresh-interval", type=int, default=40)
    parser.add_argument("--black-detect-scale", type=float, default=0.4)
    parser.add_argument("--black-l-threshold", type=int, default=85)
    parser.add_argument("--black-close-kernel", type=int, default=5)
    parser.add_argument("--black-dilate-kernel", type=int, default=3)
    parser.add_argument("--black-min-area-ratio", type=float, default=0.01)
    parser.add_argument("--black-max-area-ratio", type=float, default=0.94)
    parser.add_argument("--black-poly-epsilon", type=float, default=0.035)
    parser.add_argument("--black-min-fill-ratio", type=float, default=0.45)
    parser.add_argument("--black-min-aspect", type=float, default=1.1)
    parser.add_argument("--black-max-aspect", type=float, default=2.4)
    parser.add_argument("--black-midline-scale", type=float, default=0.94)
    parser.add_argument("--black-center-penalty", type=float, default=2.0)
    parser.add_argument("--black-max-track-shift", type=float, default=0.22)
    parser.add_argument("--black-roi-scale", type=float, default=1.12)
    parser.add_argument("--black-roi-pad", type=int, default=28)
    parser.add_argument("--black-inner-scale", type=float, default=0.72)
    parser.add_argument("--black-inner-l-min", type=float, default=80.0)
    parser.add_argument("--black-refine-roi-scale", type=float, default=1.08)
    parser.add_argument("--black-refine-pad", type=int, default=18)
    parser.add_argument("--white-l-threshold", type=int, default=100)
    parser.add_argument("--white-close-kernel", type=int, default=5)
    parser.add_argument("--white-border-margin-ratio", type=float, default=0.045)
    parser.add_argument("--white-min-area-ratio", type=float, default=0.08)
    parser.add_argument("--white-min-relative-area", type=float, default=0.2)
    parser.add_argument("--white-max-relative-area", type=float, default=0.9)
    parser.add_argument("--white-poly-epsilon", type=float, default=0.03)
    parser.add_argument("--black-outer-expand", type=float, default=1.08)
    parser.add_argument("--sample-roi-size", type=int, default=48)
    args = parser.parse_args()
    if args.min_delta is not None:
        args.min_delta_rg = args.min_delta
        args.min_delta_rb = args.min_delta
    args.sample_labels = ["white_paper", "black_tape", "red_laser", "green_laser"]
    args.hotspot_ratio = 0.08
    return args


def main():
    args = parse_args()
    tracker = LaserTracker(args)
    httpd = DemoServer((args.host, args.port), DemoHandler, tracker, args.fps)
    hostname = socket.gethostname()
    print(f"Red laser demo ready on http://{hostname}:{args.port}/")
    print(f"Red laser demo ready on http://127.0.0.1:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        tracker.close()


if __name__ == "__main__":
    main()
