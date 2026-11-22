# -*- coding: utf-8 -*-
"""车牌识别核心：片段 -> 车牌事件。"""
import collections, os, re
import cv2
import hyperlpr3 as lpr3

COLS, ROWS, OVERLAP = 3, 2, 0.15


def parse_start(path):
    m = re.search(r"_(\d{14})_", os.path.basename(path))
    return m.group(1) if m else "unknown"


def tiles(img, roi=None):
    h, w = img.shape[:2]
    if roi:
        x1, y1, x2, y2 = roi
        img = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        yield (x1, y1), cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        return
    tw, th = w // COLS, h // ROWS
    ox, oy = int(tw * OVERLAP), int(th * OVERLAP)
    for r in range(ROWS):
        for c in range(COLS):
            x1 = max(0, c * tw - ox); x2 = min(w, (c + 1) * tw + ox)
            y1 = max(0, r * th - oy); y2 = min(h, (r + 1) * th + oy)
            yield (x1, y1), cv2.resize(img[y1:y2, x1:x2], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def _dist(x, y):
    return 9 if len(x) != len(y) else sum(1 for p, q in zip(x, y) if p != q)


class PlateEngine:
    def __init__(self, level=lpr3.DETECT_LEVEL_HIGH):
        self.catcher = lpr3.LicensePlateCatcher(detect_level=level)

    def process(self, video, cfg, on_progress=None):
        """返回 (events, meta)。events: plate/offset_sec/conf/votes/box。"""
        start = parse_start(video)
        cap = cv2.VideoCapture(video)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        top_h = H // 2
        roi = cfg.get("roi")
        step = max(1, int(cfg.get("step", 5)))
        conf_min = float(cfg.get("conf", 0.5))
        province = cfg.get("province", "")

        groups = {}
        prev_gray, last_hit = None, -10 ** 9
        for i in range(0, n, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = cap.read()
            if not ok:
                break
            top = fr[:top_h]
            small = cv2.cvtColor(cv2.resize(top, (320, 180)), cv2.COLOR_BGR2GRAY)
            moved = True
            if prev_gray is not None:
                moved = cv2.absdiff(small, prev_gray).mean() > 2.0
            prev_gray = small
            if not moved and (i - last_hit) > fps * 20:
                continue
            hit = False
            for (tx, ty), img in tiles(top, roi):
                for txt, conf, typ, box in self.catcher(img):
                    if float(conf) < conf_min:
                        continue
                    t = txt.replace("·", "").replace(" ", "")
                    m = re.search(r"([A-Z][A-Z0-9]{5})$", t)
                    if not m:
                        continue
                    suf = m.group(1)
                    x1, y1, x2, y2 = [int(v) for v in box]
                    full = [x1 // 2 + tx, y1 // 2 + ty, x2 // 2 + tx, y2 // 2 + ty]
                    g = groups.setdefault(suf, {"votes": 0, "texts": collections.Counter(),
                                                "best": (0, i, full)})
                    g["votes"] += 1
                    g["texts"][t] += 1
                    hit = True
                    if float(conf) > g["best"][0]:
                        g["best"] = (float(conf), i, full)
            if hit:
                last_hit = i
            if on_progress and i % (step * 20) == 0:
                on_progress(i / max(n, 1))

        merged = []
        for suf, g in sorted(groups.items(), key=lambda kv: -kv[1]["votes"]):
            for m in merged:
                if _dist(suf, m["suffix"]) <= 2:
                    m["votes"] += g["votes"]; m["texts"].update(g["texts"])
                    if g["best"][0] > m["best"][0]:
                        m["best"] = g["best"]
                    break
            else:
                merged.append({"suffix": suf, "votes": g["votes"],
                               "texts": collections.Counter(g["texts"]), "best": g["best"]})

        events = []
        for m in merged:
            if m["votes"] < int(cfg.get("min_votes", 3)):
                continue
            conf, i, box = m["best"]
            events.append({
                "plate": (province or "?") + m["suffix"],
                "offset_sec": round(i / fps, 2),
                "conf": round(conf, 3),
                "votes": m["votes"],
                "box": box,
            })
        return events, {"start": start, "fps": fps, "frames": n, "height": H}

    def snapshot(self, video, frame_idx, box, path, pad=24):
        cap = cv2.VideoCapture(video)
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_idx)))
        ok, fr = cap.read()
        if not ok:
            return False
        x1, y1, x2, y2 = box
        crop = fr[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
        cv2.imwrite(path, cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4))
        cv2.imwrite(path.replace(".jpg", "_full.jpg"), fr[:H // 2])
        return True
