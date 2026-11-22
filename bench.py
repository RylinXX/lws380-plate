import json, os, sys, time, psutil
sys.path.insert(0, ".")
from app.plate import PlateEngine

cfg = {"province":"京","step":5,"conf":0.5,"min_votes":3,"roi":[120,200,1350,720],"two_stage":False}
eng = PlateEngine()
vids = [
 "/sdcard/DCIM/LWS380/VIDEO/75617647_Rec1795329490_20261122143810_1.mp4",
 "/sdcard/DCIM/LWS380/VIDEO/75617647_Rec1795289182_20261122032622_3.mp4",
 "/sdcard/DCIM/LWS380/VIDEO/75617647_Rec1795288972_20261122032252_3.mp4",
]
for v in vids:
    p = psutil.Process(); t0, c0 = time.perf_counter(), sum(p.cpu_times()[:2])
    ev, meta = eng.process(v, cfg)
    wall, cpu = time.perf_counter()-t0, sum(p.cpu_times()[:2])-c0
    dur = meta["frames"]/(meta["fps"] or 25)
    print(json.dumps({"clip":os.path.basename(v),"dur":round(dur,1),"wall":round(wall,1),
        "cpu":round(cpu,1),"ratio":round(cpu/dur,1),
        "events":[{"plate":e["plate"],"t":e["offset_sec"],"conf":e["conf"],"votes":e["votes"]} for e in ev]}, ensure_ascii=False), flush=True)
