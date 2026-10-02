from pathlib import Path

import numpy as np

from platform_core import CentroidTracker, GovernanceRules, PlatformDatabase, RuleEngine


def det(x1, y1, x2, y2, label="bicycle", confidence=0.9):
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "label": label, "confidence": confidence}


def test_tracker_keeps_id_for_nearby_detection():
    tracker = CentroidTracker(max_distance=100)
    tracks, new_count = tracker.update([det(10, 10, 30, 30)])
    assert new_count == 1
    first_id = tracks[0]["id"]
    tracks, new_count = tracker.update([det(18, 12, 38, 32)])
    assert new_count == 0
    assert tracks[0]["id"] == first_id


def test_forbidden_zone_fires_only_on_entry():
    rules = GovernanceRules(forbidden_enabled=True, forbidden_x=0.5, forbidden_y=0,
                            forbidden_w=0.5, forbidden_h=1, event_cooldown=0)
    engine = RuleEngine(rules)
    tracker = CentroidTracker(max_distance=200)
    shape = (100, 100, 3)
    tracks, _ = tracker.update([det(10, 40, 30, 60)])
    assert engine.process(tracks, shape, "cam") == []
    tracks, _ = tracker.update([det(60, 40, 80, 60)])
    events = engine.process(tracks, shape, "cam")
    assert len(events) == 1 and events[0]["event_type"] == "禁行区域闯入"
    tracks, _ = tracker.update([det(62, 40, 82, 60)])
    assert engine.process(tracks, shape, "cam") == []


def test_wrong_way_event():
    rules = GovernanceRules(wrong_way_enabled=True, expected_direction="ltr", min_motion_px=10, event_cooldown=0)
    engine = RuleEngine(rules)
    tracker = CentroidTracker(max_distance=200)
    shape = (100, 200, 3)
    for x in [120, 105, 90]:
        tracks, _ = tracker.update([det(x, 30, x + 20, 50)])
        engine.process(tracks, shape, "cam")
    tracks, _ = tracker.update([det(72, 30, 92, 50)])
    events = engine.process(tracks, shape, "cam")
    assert any(e["event_type"] == "逆行预警" for e in events)


def test_database_roundtrip(tmp_path: Path):
    db = PlatformDatabase(tmp_path / "platform.db")
    did = db.add_device("东门", "rtsp://example", "校门")
    assert db.get_device(did)["name"] == "东门"
    eid = db.add_event({"device": "东门", "event_type": "逆行预警", "target_label": "bicycle", "track_id": 3, "confidence": .88})
    assert db.get_event(eid)["track_id"] == 3
    db.increment_stats(2, 10)
    assert db.dashboard_metrics()["flow_count"] >= 2
    db.close()
