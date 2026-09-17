import time
import numpy as np


def create_item_state(now, zone, zone_count):
    return {
        "first_seen":      now,
        "last_seen":       now,
        "current_zone":    zone,
        "first_zone":      zone,   # zone where item first appeared — entry time unknown
        "zone_entry_time": now,
        "zone_dwell":      {i: 0.0 for i in range(zone_count)},
        "completed":       False,
        "cycle_time":      0.0,
    }


def update_item_state(item_states, detections, frame_width, now, zone_count):
    active_ids = set()

    if detections.tracker_id is not None and len(detections) > 0:
        for i in range(len(detections)):
            tid  = int(detections.tracker_id[i])
            active_ids.add(tid)

            x1, y1, x2, y2 = detections.xyxy[i].astype(int)
            cx   = (x1 + x2) / 2
            zone = int(cx / frame_width * zone_count)
            zone = max(0, min(zone_count - 1, zone))

            if tid not in item_states:
                item_states[tid] = create_item_state(now, zone, zone_count)
            else:
                state   = item_states[tid]
                elapsed = now - state["last_seen"]

                state["zone_dwell"][state["current_zone"]] += elapsed

                if zone != state["current_zone"]:
                    state["current_zone"]    = zone
                    state["zone_entry_time"] = now

                state["last_seen"] = now

    return item_states, active_ids


def mark_completed(item_states, active_ids, zone_dwell_history, now, timeout=1.5):
    for tid, state in item_states.items():
        if tid not in active_ids and not state["completed"]:
            if now - state["last_seen"] > timeout:
                state["completed"]  = True
                state["cycle_time"] = state["last_seen"] - state["first_seen"]

                # Skip only the first zone — item appeared mid-belt so we
                # don't know when it actually entered. All other zones are valid
                # because we saw the item cross into them from the previous zone.
                first_z = state["first_zone"]
                for z, dwell in state["zone_dwell"].items():
                    if dwell > 0.1 and z != first_z:
                        zone_dwell_history.setdefault(z, []).append(dwell)

    return item_states, zone_dwell_history


def compute_throughput(item_states, now, window=60):
    recent = [
        s for s in item_states.values()
        if s["completed"] and now - s["last_seen"] < window
    ]
    return round(len(recent) / window * 60, 1)


def compute_bottleneck(zone_dwell_history, zone_count, zone_names):
    # Build EMA per zone from permanent history
    zone_avgs = {}
    for z in range(zone_count):
        values = zone_dwell_history.get(z, [])
        if len(values) >= 2:
            ema = values[0]
            for v in values[1:]:
                ema = 0.8 * ema + 0.2 * v
            zone_avgs[z] = round(ema, 2)

    if len(zone_avgs) < 2:
        return {
            "zone": -1, "zone_name": "", "avg_dwell": 0.0,
            "zone_avgs": {str(z): 0.0 for z in range(zone_count)}
        }

    bottleneck_zone  = max(zone_avgs, key=zone_avgs.get)
    bottleneck_dwell = zone_avgs[bottleneck_zone]

    others      = [v for z, v in zone_avgs.items() if z != bottleneck_zone]
    other_mean  = sum(others) / len(others) if others else 0

    zone_avgs_str = {str(z): zone_avgs.get(z, 0.0) for z in range(zone_count)}

    # Only fire if slowest zone is 1.5x slower than average of others
    if other_mean == 0 or bottleneck_dwell / other_mean < 2.0:
        return {
            "zone": -1, "zone_name": "", "avg_dwell": 0.0,
            "zone_avgs": zone_avgs_str
        }

    return {
        "zone":      bottleneck_zone,
        "zone_name": zone_names[bottleneck_zone],
        "avg_dwell": bottleneck_dwell,
        "zone_avgs": zone_avgs_str
    }


def compute_cycle_times(item_states):
    times = [
        s["cycle_time"] for s in item_states.values()
        if s["completed"] and s["cycle_time"] > 0
    ]
    if not times:
        return {"mean": 0.0, "p90": 0.0, "min": 0.0, "max": 0.0}

    sorted_times = sorted(times)
    p90_index    = max(0, int(len(sorted_times) * 0.9) - 1)
    return {
        "mean": round(sum(times) / len(times), 2),
        "p90":  round(sorted_times[p90_index], 2),
        "min":  round(sorted_times[0], 2),
        "max":  round(sorted_times[-1], 2),
    }


def compute_alerts(bottleneck, item_states, zone_count, zone_names):
    alerts = []

    if bottleneck["zone"] >= 0:
        alerts.append(
            f"Bottleneck at {bottleneck['zone_name']} — "
            f"{bottleneck['avg_dwell']}s avg dwell"
        )

    # Jam alert — more than 3 active items in same zone
    zone_counts = {}
    for state in item_states.values():
        if not state["completed"]:
            z = state["current_zone"]
            zone_counts[z] = zone_counts.get(z, 0) + 1

    for z, count in zone_counts.items():
        if count >= 3:
            name = zone_names[z] if z < len(zone_names) else f"Zone {z}"
            alerts.append(f"Jam at {name} — {count} items queued")

    return alerts


def build_metrics_snapshot(
    item_states, zone_dwell_history,
    frame_number, zone_count, zone_names, now
):
    bottleneck  = compute_bottleneck(zone_dwell_history, zone_count, zone_names)
    cycle_times = compute_cycle_times(item_states)
    throughput  = compute_throughput(item_states, now)
    alerts      = compute_alerts(bottleneck, item_states, zone_count, zone_names)

    active_items = [
        {
            "id":    tid,
            "zone":  state["current_zone"],
            "dwell": round(now - state["zone_entry_time"], 1),
        }
        for tid, state in item_states.items()
        if not state["completed"]
    ]

    return {
        "frame":              frame_number,
        "active_items":       len(active_items),
        "completed_items":    sum(1 for s in item_states.values() if s["completed"]),
        "throughput_per_min": throughput,
        "bottleneck":         bottleneck,
        "cycle_time":         cycle_times,
        "alerts":             alerts,
        "items":              active_items,
    }