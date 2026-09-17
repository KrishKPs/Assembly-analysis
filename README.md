# Assembly Line Analyzer

Computer-vision analytics for a conveyor belt. **YOLOv8** detects items, **ByteTrack** (via Supervision) gives each one a persistent ID, and an analytics engine turns those tracks into operational metrics streamed live to a React dashboard.

## What it measures

- **Throughput:** items per minute
- **Items on belt:** active vs. completed
- **Bottleneck:** the zone with the longest average dwell time (Intake → Station A/B/C → QC → Output)
- **Cycle time:** mean, p90, min and max per item
- **Alerts:** slow stations and jams (queued items)

## Layout

```
src/video_pipeline.py  detect → track → zone → annotate; writes clean + animated videos
src/analytics.py       throughput, dwell, cycle-time and alert logic (pure functions)
src/server.py          FastAPI; runs the pipeline in a thread and streams metrics on ws://…/ws/metrics
dashboard/             React + Recharts dark industrial dashboard
test_analytics.py      tests for the analytics engine
```

## Run it

Put a conveyor-belt video at `input/4156510-hd_1920_1080_30fps.mp4` (or change `SOURCE` in `src/server.py`). YOLO weights (`yolov8n.pt`) download automatically on first run.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdir -p input output

python main.py          # process the video offline → output/clean.mp4, output/animated.mp4
python run_server.py    # or: live mode, websocket on :8000

cd dashboard && npm install && npm run dev   # dashboard
```

Tests: `python test_analytics.py`

## Stack

Python · Ultralytics YOLOv8 · Supervision (ByteTrack) · OpenCV · FastAPI WebSockets · React · Vite · Recharts
