import time
import json
import numpy as np
from src.analytics import update_item_state, build_metrics_snapshot

FRAME_WIDTH = 1920


class FakeDetections:
    """Minimal stub that matches the fields analytics.py reads."""
    def __init__(self, tracker_ids, x_centers):
        self.tracker_id = np.array(tracker_ids, dtype=int)
        # Build xyxy from x_centers — height doesn't matter for zone math
        self.xyxy = np.array(
            [[x - 20, 400, x + 20, 480] for x in x_centers], dtype=float
        )


def simulate():
    item_states   = {}
    alert_state   = {}
    frame_number  = 0

    # Each entry: (tracker_id, x_positions_per_frame)
    # Items travel left→right across 1920px over ~6 frames each
    # 5 items staggered so they don't all arrive at once
    items = {
        1: [160, 480, 800, 1120, 1440, 1760, None],   # fast item (~0.3s cycle)
        2: [160, 320, 640, 960,  None],                # exits early
        3: [160, 480, 800, 1120, 1440, 1760, None],
        4: [160, 480, 960, None],
        5: [160, 320, 480, 640, 800,  960, 1120, 1440, 1760, None],  # slow item
    }

    # To trigger a jam: push 4 items into Station A simultaneously at frame 3
    jam_frame = {
        6: 480,
        7: 500,
        8: 520,
        9: 540,
    }

    base_time = time.time()

    max_frames = max(len(v) for v in items.values()) + 5
    for f in range(max_frames):
        current_time = base_time + f * 0.033  # ~30fps

        # Build active detections for this frame
        active_ids   = []
        active_xs    = []

        for tid, positions in items.items():
            if f < len(positions) and positions[f] is not None:
                active_ids.append(tid)
                active_xs.append(positions[f])

        # Inject jam items at frame 3
        if f == 3:
            for tid, x in jam_frame.items():
                active_ids.append(tid)
                active_xs.append(x)

        if active_ids:
            det = FakeDetections(active_ids, active_xs)
        else:
            det = FakeDetections([], [])

        item_states = update_item_state(item_states, det, FRAME_WIDTH, current_time)
        frame_number += 1

    # One final pass with empty detections so all items time out as completed
    time.sleep(2.1)
    item_states = update_item_state(
        item_states, FakeDetections([], []), FRAME_WIDTH, time.time()
    )

    completed_items = {k: v for k, v in item_states.items() if v["completed"]}

    snapshot = build_metrics_snapshot(
        item_states, completed_items, frame_number, alert_state
    )

    print("\n=== Metrics Snapshot ===")
    print(json.dumps(snapshot, indent=2))

    print("\n=== Item States ===")
    for tid, state in item_states.items():
        ct = state["last_seen"] - state["first_seen"]
        print(
            f"  ID {tid:>2} | zone_dwell={state['zone_dwell']} "
            f"| cycle={ct:.2f}s | completed={state['completed']}"
        )


if __name__ == "__main__":
    simulate()
