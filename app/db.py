# -*- coding: utf-8 -*-
"""SQLite 存取。"""
import os, sqlite3, threading
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "plate.db")
_lock = threading.Lock()


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript("""
        create table if not exists clips(
          id integer primary key autoincrement,
          name text unique, start text, status text default 'pending',
          progress real default 0, error text, frames integer, fps real,
          created text default current_timestamp);
        create table if not exists events(
          id integer primary key autoincrement,
          clip_id integer, plate text, offset_sec real, ts text,
          conf real, votes integer, snapshot text, box text);
        create index if not exists idx_events_ts on events(ts);
        create index if not exists idx_events_plate on events(plate);
        """)


def clip_start_dt(start: str) -> datetime:
    try:
        return datetime.strptime(start, "%Y%m%d%H%M%S")
    except Exception:
        return datetime(1970, 1, 1)


def add_clip(name, start):
    with _lock, conn() as c:
        c.execute("insert or ignore into clips(name,start) values(?,?)", (name, start))
        return c.execute("select id from clips where name=?", (name,)).fetchone()["id"]


def set_status(clip_id, status, progress=None, error=None, frames=None, fps=None):
    with _lock, conn() as c:
        c.execute("""update clips set status=?, progress=coalesce(?,progress),
                     error=coalesce(?,error), frames=coalesce(?,frames), fps=coalesce(?,fps)
                     where id=?""", (status, progress, error, frames, fps, clip_id))


def add_event(clip_id, start, ev, snapshot):
    dt = clip_start_dt(start) + timedelta(seconds=ev["offset_sec"])
    with _lock, conn() as c:
        c.execute("""insert into events(clip_id,plate,offset_sec,ts,conf,votes,snapshot,box)
                     values(?,?,?,?,?,?,?,?)""",
                  (clip_id, ev["plate"], ev["offset_sec"], dt.strftime("%Y-%m-%d %H:%M:%S"),
                   ev["conf"], ev["votes"], snapshot, str(ev["box"])))


def clear_events(clip_id):
    with _lock, conn() as c:
        c.execute("delete from events where clip_id=?", (clip_id,))


def passes(gap_sec=180):
    """把同一车牌、时间相邻的事件合并成一次通行。"""
    with _lock, conn() as c:
        rows = c.execute("""select e.*, c.name clip_name from events e
                            join clips c on c.id=e.clip_id order by e.ts""").fetchall()
    out = []
    by_plate = {}
    for r in rows:
        dt = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        arr = by_plate.setdefault(r["plate"], [])
        if arr and (dt - arr[-1]["_last"]).total_seconds() <= gap_sec:
            p = arr[-1]
            p["_last"] = dt
            p["count"] += 1
            if r["conf"] > p["conf"]:
                p.update(conf=r["conf"], snapshot=r["snapshot"], ts=r["ts"],
                         clip=r["clip_name"], offset=r["offset_sec"], votes=r["votes"])
        else:
            arr.append({"_last": dt, "plate": r["plate"], "first_ts": r["ts"],
                        "last_ts": r["ts"], "count": 1, "conf": r["conf"],
                        "snapshot": r["snapshot"], "ts": r["ts"],
                        "clip": r["clip_name"], "offset": r["offset_sec"],
                        "votes": r["votes"]})
    for arr in by_plate.values():
        for p in arr:
            p.pop("_last", None)
            out.append(p)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def stats():
    with _lock, conn() as c:
        total = c.execute("select count(*) n from events").fetchone()["n"]
        plates = c.execute("select count(distinct plate) n from events").fetchone()["n"]
        clips = c.execute("select count(*) n from clips").fetchone()["n"]
        done = c.execute("select count(*) n from clips where status='done'").fetchone()["n"]
    return {"events": total, "plates": plates, "clips": clips, "done": done}


def clips():
    with _lock, conn() as c:
        return [dict(r) for r in c.execute("select * from clips order by start").fetchall()]
