# -*- coding: utf-8 -*-
"""后台处理队列：扫描目录 -> 识别 -> 入库 -> 截图。"""
import json, os, psutil, queue, threading, time

from . import db
from .plate import PlateEngine, parse_start

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
VIDEOS = os.path.join(DATA, "videos")
SNAPS = os.path.join(DATA, "snapshots")
CONFIG = os.path.join(DATA, "config.json")

DEFAULT_CFG = {"province": "京", "step": 8, "conf": 0.5, "min_votes": 3,
               "roi": [120, 200, 1600, 720], "merge_gap": 180, "two_stage": False}

_q: "queue.Queue[tuple[int,str,str]]" = queue.Queue()
_started = False


def load_cfg():
    if os.path.exists(CONFIG):
        cfg = dict(DEFAULT_CFG)
        cfg.update(json.load(open(CONFIG, encoding="utf-8")))
        return cfg
    return dict(DEFAULT_CFG)


def save_cfg(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def _run(engine):
    while True:
        clip_id, path, name = _q.get()
        cfg = load_cfg()
        try:
            db.set_status(clip_id, "running", 0)
            proc = psutil.Process()
            t0, c0 = time.perf_counter(), sum(proc.cpu_times()[:2])
            events, meta = engine.process(
                path, cfg, on_progress=lambda p: db.set_status(clip_id, "running", p))
            db.clear_events(clip_id)
            for ev in events:
                snap = os.path.join(SNAPS, f"{meta['start']}_{int(ev['offset_sec'])}s_{ev['plate']}.jpg")
                engine.snapshot(path, ev["offset_sec"] * meta["fps"], ev["box"], snap)
                db.add_event(clip_id, meta["start"], ev, os.path.relpath(snap, DATA))
            wall = time.perf_counter() - t0
            cpu = sum(proc.cpu_times()[:2]) - c0
            db.finish_clip(clip_id, round(wall, 2), round(cpu, 2), meta["frames"], meta["fps"])
        except Exception as e:
            db.set_status(clip_id, "error", error=str(e)[:300])
        finally:
            _q.task_done()


def start():
    global _started
    if _started:
        return
    os.makedirs(SNAPS, exist_ok=True)
    os.makedirs(VIDEOS, exist_ok=True)
    engine = PlateEngine()
    threading.Thread(target=_run, args=(engine,), daemon=True).start()
    _started = True


def scan(directory=None):
    """把目录里未处理过的 mp4 加入队列，返回新增数量。"""
    directory = directory or VIDEOS
    start()
    n = 0
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(".mp4"):
            continue
        path = os.path.join(directory, name)
        start_s = parse_start(name)
        clip_id = db.add_clip(name, start_s)
        with db.conn() as c:
            st = c.execute("select status from clips where id=?", (clip_id,)).fetchone()["status"]
        if st in ("pending", "error"):
            _q.put((clip_id, path, name))
            n += 1
    return n


def pending():
    return _q.qsize()
