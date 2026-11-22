# -*- coding: utf-8 -*-
"""FastAPI 入口：网页 + JSON API + 视频/截图静态服务。"""
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, worker

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")

app = FastAPI(title="工地车牌识别")


class ScanReq(BaseModel):
    directory: str | None = None


@app.on_event("startup")
def _startup():
    db.init()
    worker.start()


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/api/stats")
def api_stats():
    s = db.stats()
    s["pending"] = worker.pending()
    return s


@app.get("/api/passes")
def api_passes(plate: str = "", date: str = "", gap: int = 180):
    rows = db.passes(gap_sec=gap)
    if plate:
        rows = [r for r in rows if plate.lower() in r["plate"].lower()]
    if date:
        rows = [r for r in rows if r["ts"].startswith(date)]
    return rows


@app.get("/api/clips")
def api_clips():
    return db.clips()


@app.post("/api/scan")
def api_scan(req: ScanReq):
    if req.directory and not os.path.isdir(req.directory):
        raise HTTPException(400, "目录不存在")
    return {"queued": worker.scan(req.directory)}


@app.get("/api/config")
def api_get_config():
    return worker.load_cfg()


@app.post("/api/config")
def api_set_config(cfg: dict):
    worker.save_cfg(cfg)
    return worker.load_cfg()


@app.get("/video/{name}")
def video(name: str):
    path = os.path.join(DATA, "videos", name)
    if not os.path.abspath(path).startswith(os.path.join(DATA, "videos")):
        raise HTTPException(400)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


app.mount("/media", StaticFiles(directory=os.path.join(DATA)), name="media")
app.mount("/static", StaticFiles(directory=WEB), name="static")
