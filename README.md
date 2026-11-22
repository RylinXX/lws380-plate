# 工地车牌识别（LWS380 片段）

把 LWS380 摄像头导出的 mp4 片段批量识别成「车牌 + 时间 + 截图」，带一个网页界面。

## 特点

- 适配 LWS380 片段格式：1920×2160，上下两幅画面，文件名含设备与起始时间
- 分块 + 高清模型 + 多帧投票 + 编辑距离合并，同屏多车不丢
- 跨片段合并：同一车牌在 3 分钟内出现多次算一次通行
- 输出事件表 + 车牌特写 + 整帧截图，网页里可回看源片段
- SQLite 存储，断点续跑

## 测试素材

`samples/` 下有 9 段真实片段（25MB，原始码流未转码），可直接用来跑通：

```bash
cp samples/*.mp4 data/videos/
```

详见 [samples/README.md](samples/README.md)（含 MD5 校验）。

## 快速开始

```bash
pip install -r requirements.txt
mkdir -p data/videos
cp /path/to/*.mp4 data/videos/
./run.sh
# 浏览器打开 http://<ip>:8000
```

首次识别会自动下载 HyperLPR3 模型（约 18MB）到 `~/.hyperlpr3`。

## 目录

```
app/plate.py    识别核心（分块/投票/合并）
app/worker.py   后台队列
app/db.py       SQLite
app/main.py     FastAPI + 静态服务
web/            前端（原生 JS）
data/videos/    输入片段
data/snapshots/ 输出截图
data/plate.db   结果库
```

## 配置

`data/config.json`：

```json
{"province":"京","step":5,"conf":0.5,"min_votes":3,"roi":null,"merge_gap":180}
```

- `roi`: `[x1,y1,x2,y2]` 只算门口区域，能省一半以上算力
- `step`: 每 N 帧检测一次
- `province`: 强制省份（同一车队都是京A时很有用）

## 模型与性能

- 检测：YOLOv5s 轻量版（3.9MB）+ 识别 CRNN（10.3MB），ONNX CPU 推理
- 本机（8 核 ARM）实测：

| 模式 | ROI | step | CPU/视频秒 | 精度 |
|---|---|---|---|---|
| accurate（默认） | 是 | 8 | ≈15 | 全，远处小车也能抓 |
| accurate | 是 | 5 | ≈22–30 | 全 |
| fast（两级） | 是 | 5 | ≈4–12 | 会漏远处小车（已验证丢过一辆） |

结论：**精度优先用 accurate 模式**；要吞吐再换 fast，接受漏检。

`two_stage: true` 开启快速模式，`roi` 是门口区域 `[x1,y1,x2,y2]`（相对上半幅），
机位不动配一次即可。

## 路线

- [x] 片段识别 + 投票 + 跨片段合并
- [x] Web 事件列表 / 截图 / 源片段回放
- [ ] ROI 配置界面
- [ ] 两级检测提速
- [ ] 夜间增强（CLAHE / 多尺度）
- [ ] 导出 CSV / 对接对象存储
