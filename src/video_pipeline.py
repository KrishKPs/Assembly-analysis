import time
import json
import numpy as np
import cv2
from ultralytics import YOLO
import supervision as sv
from .analytics import update_item_state, mark_completed, build_metrics_snapshot

WHITE  = (255, 255, 255)
YELLOW = (0,   255, 255)
RED    = (0,     0, 255)
BLACK  = (0,     0,   0)

FONT  = cv2.FONT_HERSHEY_SIMPLEX
HUD_H = 30

# 10-colour BGR palette — indexed by zone index
_ZONE_COLORS = [
    (255, 140,  50),
    ( 50, 220,  50),
    (220,  50, 220),
    (  0, 200, 255),
    (255,  50, 150),
    ( 50, 220, 220),
    (200, 200,  50),
    ( 50, 150, 255),
    (150, 255,  50),
    (255, 150, 200),
]

CALIB_FRAMES = 30


# ── Zone names ──────────────────────────────────────────────────────────────

def get_zone_names(count):
    presets = {
        3: ["Intake", "Process", "Output"],
        4: ["Intake", "Station A", "Station B", "Output"],
        5: ["Intake", "Station A", "Station B", "QC", "Output"],
    }
    if count in presets:
        return presets[count]
    stations = [f"Station {chr(65 + i)}" for i in range(count - 3)]
    return ["Intake"] + stations + ["QC", "Output"]


# ── Calibration ─────────────────────────────────────────────────────────────

def _make_calibration(frame_height):
    return {
        "done":        False,
        "n":           0,
        "box_widths":  [],
        "motion_rows": np.zeros(frame_height, dtype=np.float64),
        "prev_gray":   None,
        "zone_count":  6,
        "zone_names":  get_zone_names(6),
        "belt_top":    0,
        "belt_bottom": frame_height,
    }


def _ingest_calib_frame(calib, frame, detections, frame_width, frame_height):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if calib["prev_gray"] is not None:
        diff = cv2.absdiff(calib["prev_gray"], gray)
        calib["motion_rows"] += diff.sum(axis=1).astype(np.float64)
    calib["prev_gray"] = gray

    if detections.tracker_id is not None and len(detections) > 0:
        for box in detections.xyxy:
            calib["box_widths"].append(float(box[2] - box[0]))

    calib["n"] += 1

    if calib["n"] >= CALIB_FRAMES:
        _finalize_calibration(calib, frame_width, frame_height)


def _finalize_calibration(calib, frame_width, frame_height):
    motion = calib["motion_rows"]

    if motion.max() > 0:
        kernel   = max(3, frame_height // 20) | 1
        smoothed = np.convolve(motion, np.ones(kernel) / kernel, mode="same")
        peak     = smoothed.max()
        rows     = np.where(smoothed > peak * 0.25)[0]
        if len(rows) >= max(5, int(frame_height * 0.03)):
            calib["belt_top"]    = max(0,              int(rows[0])  - 8)
            calib["belt_bottom"] = min(frame_height-1, int(rows[-1]) + 8)
        else:
            calib["belt_top"]    = 0
            calib["belt_bottom"] = frame_height
    else:
        calib["belt_top"]    = 0
        calib["belt_bottom"] = frame_height

    # Enforce minimum belt height (15% of frame)
    min_h = int(frame_height * 0.15)
    if calib["belt_bottom"] - calib["belt_top"] < min_h:
        cy = (calib["belt_top"] + calib["belt_bottom"]) // 2
        calib["belt_top"]    = max(0, cy - min_h // 2)
        calib["belt_bottom"] = min(frame_height - 1, cy + min_h // 2)

    if calib["box_widths"]:
        avg_w = float(np.mean(calib["box_widths"]))
        zc    = int(frame_width / (avg_w * 1.5))
        calib["zone_count"] = max(3, min(10, zc))
    else:
        calib["zone_count"] = 6

    calib["zone_names"] = get_zone_names(calib["zone_count"])
    calib["done"]       = True

    print(
        f"[calibration] belt rows {calib['belt_top']}–{calib['belt_bottom']} of {frame_height} | "
        f"zones: {calib['zone_count']} {calib['zone_names']}"
    )


# ── Detection helpers ────────────────────────────────────────────────────────

def _open_video(source):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {source}")
    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    print(f"Opened {source}  {w}x{h} @ {fps:.1f} fps")
    return cap, w, h, fps


def _detect(model, frame):
    return sv.Detections.from_ultralytics(model(frame, verbose=False)[0])


def _track(tracker, dets):
    return tracker.update_with_detections(dets)


def _filter(dets, belt_top, belt_bottom):
    """Keep only non-person items whose center Y falls within the belt band."""
    if dets.tracker_id is None or len(dets) == 0:
        return dets
    mask = []
    for i in range(len(dets)):
        x1, y1, x2, y2 = dets.xyxy[i]
        cy  = (y1 + y2) / 2
        cls = dets.data["class_name"][i]
        mask.append(cls != "person" and belt_top <= cy <= belt_bottom)
    return dets[np.array(mask)]


# ── Drawing ──────────────────────────────────────────────────────────────────

def _hud(frame, snapshot):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, h - HUD_H), (w, h), BLACK, -1)
    left = f"frame: {snapshot['frame']}  |  items: {snapshot['active_items']}  |  Q to quit"
    cv2.putText(frame, left, (10, h - 10), FONT, 0.5, WHITE, 1, cv2.LINE_AA)

    bn = snapshot["bottleneck"]
    if bn["avg_dwell"] > 0:
        label = f"BOTTLENECK: {bn['zone_name']}"
        (tw, _), _ = cv2.getTextSize(label, FONT, 0.5, 1)
        tx = w - tw - 15
        cv2.circle(frame, (tx - 14, h - 14), 5, RED, -1, cv2.LINE_AA)
        cv2.putText(frame, label, (tx, h - 10), FONT, 0.5, RED, 1, cv2.LINE_AA)


def _build_clean(raw, dets, item_states, snapshot, calib):
    h, w  = raw.shape[:2]
    zc    = calib["zone_count"]
    names = calib["zone_names"]
    bt    = calib["belt_top"]
    bb    = calib["belt_bottom"]
    zw    = w / zc

    frame = (raw * 0.4).astype(np.uint8)

    for i in range(1, zc):
        x = int(i * zw)
        cv2.line(frame, (x, bt), (x, bb), WHITE, 2, cv2.LINE_AA)

    for i, name in enumerate(names):
        cv2.putText(frame, name, (int(i * zw) + 8, max(bt - 6, 18)),
                    FONT, 0.6, YELLOW, 1, cv2.LINE_AA)

    if dets.tracker_id is not None:
        for i, tid in enumerate(dets.tracker_id):
            x1, y1, x2, y2 = map(int, dets.xyxy[i])
            cls = dets.data["class_name"][i]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(frame, f"#{int(tid)} {cls}", (x1, max(y1 - 6, 14)),
                        FONT, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

    _hud(frame, snapshot)
    return frame


def _build_anim(raw, dets, item_states, snapshot, now, calib):
    h, w  = raw.shape[:2]
    zc    = calib["zone_count"]
    names = calib["zone_names"]
    bt    = calib["belt_top"]
    bb    = calib["belt_bottom"]
    zw    = w / zc
    bn    = snapshot["bottleneck"]["zone"] if snapshot["bottleneck"]["avg_dwell"] > 0 else -1

    frame   = np.zeros((h, w, 3), dtype=np.uint8)
    overlay = frame.copy()

    for i in range(zc):
        x0    = int(i * zw)
        x1    = int((i + 1) * zw) if i < zc - 1 else w
        color = RED if i == bn else _ZONE_COLORS[i % len(_ZONE_COLORS)]
        cv2.rectangle(overlay, (x0, bt), (x1, bb), color, -1)
    cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)

    cv2.rectangle(frame, (0, bt), (w, bb), (26, 26, 26), -1)
    cv2.line(frame, (0, bt), (w, bt), (51, 51, 51), 1)
    cv2.line(frame, (0, bb), (w, bb), (51, 51, 51), 1)

    for i in range(1, zc):
        x = int(i * zw)
        cv2.line(frame, (x, bt), (x, bb), WHITE, 2, cv2.LINE_AA)

    for i, name in enumerate(names):
        color = RED if i == bn else YELLOW
        cv2.putText(frame, name, (int(i * zw) + 8, max(bt - 6, 18)),
                    FONT, 0.6, color, 1, cv2.LINE_AA)
        if i == bn:
            cv2.putText(frame, "BOTTLENECK", (int(i * zw) + 8, max(bt - 22, 14)),
                        FONT, 0.45, RED, 1, cv2.LINE_AA)

    if dets.tracker_id is not None:
        for i, tid in enumerate(dets.tracker_id):
            tid   = int(tid)
            x1, y1, x2, y2 = map(int, dets.xyxy[i])
            state = item_states.get(tid)
            zone  = state["current_zone"] if state else 0
            color = RED if zone == bn else _ZONE_COLORS[zone % len(_ZONE_COLORS)]
            cls   = dets.data["class_name"][i]

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
            cv2.putText(frame, f"#{tid} {cls}", (x1, max(y1 - 6, 14)),
                        FONT, 0.5, color, 1, cv2.LINE_AA)

            if state:
                dwell = now - state["zone_entry_time"]
                txt   = f"{dwell:.1f}s"
                (tw, th), _ = cv2.getTextSize(txt, FONT, 0.5, 1)
                cx = x1 + (x2 - x1 - tw) // 2
                cy = y1 + (y2 - y1 + th) // 2
                cv2.putText(frame, txt, (cx, cy), FONT, 0.5, color, 1, cv2.LINE_AA)

    _hud(frame, snapshot)
    return frame


# ── Main entry point ─────────────────────────────────────────────────────────

def run(source, clean_path="output/clean.mp4", anim_path="output/animated.mp4",
        on_snapshot=None, headless=False):

    model   = YOLO("yolov8n.pt")
    tracker = sv.ByteTrack()
    cap, w, h, fps = _open_video(source)

    fourcc       = cv2.VideoWriter_fourcc(*"mp4v")
    writer_clean = cv2.VideoWriter(clean_path, fourcc, fps, (w, h))
    writer_anim  = cv2.VideoWriter(anim_path,  fourcc, fps, (w, h))

    calib              = _make_calibration(h)
    item_states        = {}
    zone_dwell_history = {}
    frame_number       = 0
    last_print         = 0.0

    print(f"Calibrating on first {CALIB_FRAMES} frames ...")
    print(f"Output: {clean_path}  |  {anim_path}")

    while True:
        ok, raw = cap.read()
        if not ok:
            print("End of video.")
            break

        now          = time.time()
        frame_number += 1

        # ── Calibration phase ──────────────────────────────────────────
        if not calib["done"]:
            dets = _detect(model, raw)
            dets = _track(tracker, dets)
            if dets.tracker_id is not None and len(dets) > 0:
                mask = np.array([c != "person" for c in dets.data["class_name"]])
                dets = dets[mask]

            _ingest_calib_frame(calib, raw, dets, w, h)

            if not headless:
                prog = raw.copy()
                pct  = int(calib["n"] / CALIB_FRAMES * 100)
                cv2.putText(prog, f"Calibrating {calib['n']}/{CALIB_FRAMES} ({pct}%)",
                            (20, 50), FONT, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.imshow("Calibrating", prog)
                cv2.waitKey(1)

            if calib["done"] and not headless:
                cv2.destroyWindow("Calibrating")
            continue

        # ── Normal processing ──────────────────────────────────────────
        dets = _detect(model, raw)
        dets = _track(tracker, dets)
        dets = _filter(dets, calib["belt_top"], calib["belt_bottom"])

        zc    = calib["zone_count"]
        names = calib["zone_names"]

        item_states, active_ids    = update_item_state(item_states, dets, w, now, zc)
        item_states, zone_dwell_history = mark_completed(
            item_states, active_ids, zone_dwell_history, now
        )
        snapshot = build_metrics_snapshot(
            item_states, zone_dwell_history,
            frame_number, zc, names, now
        )
        snapshot["zones"] = {
            "count":       zc,
            "names":       names,
            "belt_top":    calib["belt_top"],
            "belt_bottom": calib["belt_bottom"],
        }

        if on_snapshot is not None:
            on_snapshot(snapshot)

        if now - last_print >= 1.0:
            brief = {k: snapshot[k] for k in
                     ("throughput_per_min", "active_items", "bottleneck", "cycle_time")}
            print(f"[analytics] frame {frame_number}  {json.dumps(brief)}")
            last_print = now

        clean = _build_clean(raw, dets, item_states, snapshot, calib)
        anim  = _build_anim(raw, dets, item_states, snapshot, now, calib)

        writer_clean.write(clean)
        writer_anim.write(anim)

        if not headless:
            cv2.imshow("Clean", clean)
            cv2.imshow("Animated", anim)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    writer_clean.release()
    writer_anim.release()
    if not headless:
        cv2.destroyAllWindows()

    print(f"\nSaved: {clean_path}")
    print(f"Saved: {anim_path}")
