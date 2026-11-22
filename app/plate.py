# -*- coding: utf-8 -*-
"""车牌识别核心：片段 -> 车牌事件。

两种模式：
- two_stage=True（默认）：ROI 内小模型粗筛 -> 候选裁剪放大 -> 大模型精读
- two_stage=False：全画面分块 + 大模型（旧逻辑，精度略高但慢 5 倍）
"""
import collections, os, re
import cv2
import hyperlpr3 as lpr3

COLS, ROWS, OVERLAP = 3, 2, 0.15
PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"


def parse_start(path):
    m = re.search(r"_(\d{14})_", os.path.basename(path))
    return m.group(1) if m else "unknown"


def parse_plate(text):
    """把 OCR 原始串规整成 (省, 6位)。容忍中间夹字符，如 '粤A1UP937' -> 粤AUP937。"""
    t = re.sub(r"[^0-9A-Z\u4e00-\u9fa5]", "", (text or "").upper())
    m = re.search(rf"([{PROVINCES}])([A-Z])", t)
    if not m:
        return None
    rest = re.sub(r"[^0-9A-Z]", "", t[m.end():])
    if len(rest) < 5:
        return None
    return m.group(1), m.group(2) + rest[-5:]


def tiles(img):
    h, w = img.shape[:2]
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
    def __init__(self):
        self.low = lpr3.LicensePlateCatcher(detect_level=lpr3.DETECT_LEVEL_LOW)
        self.high = lpr3.LicensePlateCatcher(detect_level=lpr3.DETECT_LEVEL_HIGH)

    def _detect_two_stage(self, roi_img, conf_min, margin=14, scale=3):
        """返回 [(box_in_roi, text, conf)]。"""
        out = []
        for txt, conf, typ, box in self.low(roi_img):
            if float(conf) < max(0.25, conf_min * 0.6):
                continue
            x1, y1, x2, y2 = [int(v) for v in box]
            crop = roi_img[max(0, y1 - margin):y2 + margin, max(0, x1 - margin):x2 + margin]
            if crop.size == 0:
                continue
            big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            best = (float(conf), txt, [x1, y1, x2, y2])
            for t2, c2, ty2, b2 in self.high(big):
                if float(c2) > best[0]:
                    # 精读框映射回 ROI 坐标
                    bx1 = int(b2[0] / scale) + max(0, x1 - margin)
                    by1 = int(b2[1] / scale) + max(0, y1 - margin)
                    bx2 = int(b2[2] / scale) + max(0, x1 - margin)
                    by2 = int(b2[3] / scale) + max(0, y1 - margin)
                    best = (float(c2), t2, [bx1, by1, bx2, by2])
            out.append((best[2], best[1], best[0]))
        return out

    def _detect_tiles(self, img, conf_min):
        out = []
        for (tx, ty), tile in tiles(img):
            for txt, conf, typ, box in self.high(tile):
                if float(conf) < conf_min:
                    continue
                x1, y1, x2, y2 = [int(v) for v in box]
                out.append(([x1 // 2 + tx, y1 // 2 + ty, x2 // 2 + tx, y2 // 2 + ty], txt, float(conf)))
        return out

    def process(self, video, cfg, on_progress=None):
        start = parse_start(video)
        cap = cv2.VideoCapture(video)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        top_h = H // 2
        roi = cfg.get("roi")
        step = max(1, int(cfg.get("step", 8)))
        conf_min = float(cfg.get("conf", 0.5))
        province = cfg.get("province", "")
        two_stage = bool(cfg.get("two_stage", True))

        groups = {}
        prev_gray, last_hit = None, -10 ** 9
        for i in range(0, n, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, fr = cap.read()
            if not ok:
                break
            top = fr[:top_h]
            if roi:
                rx1, ry1, rx2, ry2 = roi
                work = top[max(0, ry1):min(top_h, ry2), max(0, rx1):min(top.shape[1], rx2)]
                ox, oy = max(0, rx1), max(0, ry1)
            else:
                work, ox, oy = top, 0, 0

            small = cv2.cvtColor(cv2.resize(work, (320, 180)), cv2.COLOR_BGR2GRAY)
            moved = True
            if prev_gray is not None:
                moved = cv2.absdiff(small, prev_gray).mean() > 2.0
            prev_gray = small
            if not moved and (i - last_hit) > fps * 20:
                continue

            dets = (self._detect_two_stage(work, conf_min) if two_stage
                    else self._detect_tiles(work, conf_min))
            if dets:
                last_hit = i
            for box, txt, conf in dets:
                parsed = parse_plate(txt)
                if not parsed:
                    continue
                prov, suf = parsed
                full = [box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy]
                g = groups.setdefault(suf, {"votes": 0, "texts": collections.Counter(),
                                            "best": (0, i, full), "prov": collections.Counter()})
                g["votes"] += 1
                g["texts"][prov + suf] += 1
                g["prov"][prov] += 1
                if conf > g["best"][0]:
                    g["best"] = (conf, i, full)
            if on_progress and i % (step * 20) == 0:
                on_progress(i / max(n, 1))

        merged = []
        for suf, g in sorted(groups.items(), key=lambda kv: -kv[1]["votes"]):
            for m in merged:
                if _dist(suf, m["suffix"]) <= 2:
                    m["votes"] += g["votes"]; m["texts"].update(g["texts"]); m["prov"].update(g["prov"])
                    if g["best"][0] > m["best"][0]:
                        m["best"] = g["best"]
                    break
            else:
                merged.append({"suffix": suf, "votes": g["votes"],
                               "texts": collections.Counter(g["texts"]),
                               "prov": collections.Counter(g["prov"]), "best": g["best"]})

        events = []
        for m in merged:
            if m["votes"] < int(cfg.get("min_votes", 3)):
                continue
            conf, i, box = m["best"]
            prov = province or (m["prov"].most_common(1)[0][0] if m["prov"] else "?")
            events.append({"plate": prov + m["suffix"], "offset_sec": round(i / fps, 2),
                           "conf": round(conf, 3), "votes": m["votes"], "box": box})
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
