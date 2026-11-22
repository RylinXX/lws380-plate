const $ = (s) => document.querySelector(s);
let rows = [];

async function j(url, opt) {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function refresh() {
  const s = await j("/api/stats");
  $("#stPass").textContent = s.clips ? "-" : "-";
  $("#stPlate").textContent = s.plates;
  $("#stClip").textContent = `${s.done}/${s.clips}`;
  $("#stQueue").textContent = s.pending;

  const params = new URLSearchParams();
  const d = $("#fDate").value, p = $("#fPlate").value.trim();
  if (d) params.set("date", d);
  if (p) params.set("plate", p);
  rows = await j("/api/passes?" + params.toString());
  $("#stPass").textContent = rows.length;
  render();
}

function fmt(ts) { return ts ? ts.slice(5, 16) : "-"; }

function render() {
  const list = $("#list");
  if (!rows.length) {
    list.innerHTML = `<div class="empty">还没有数据。把片段放进 data/videos，点右上角「扫描新片段」。</div>`;
    return;
  }
  list.innerHTML = rows.map((r, i) => `
    <div class="row" data-i="${i}">
      <img src="/media/${r.snapshot}" loading="lazy" alt="">
      <div>
        <div class="plate">${r.plate}</div>
        <div class="meta">${fmt(r.first_ts)} · 片段 ${r.clip} · 置信度 ${(r.conf * 100).toFixed(0)}%</div>
      </div>
      <div class="badge">${r.count} 次</div>
    </div>`).join("");
  list.querySelectorAll(".row").forEach((el) => {
    el.onclick = () => openModal(rows[+el.dataset.i]);
  });
}

function openModal(r) {
  $("#mPlate").textContent = r.plate;
  $("#mMeta").textContent = `${r.first_ts} · ${r.clip} · 偏移 ${r.offset}s · 票数 ${r.votes}`;
  $("#mSnap").src = "/media/" + r.snapshot;
  $("#mFull").src = "/media/" + r.snapshot.replace(".jpg", "_full.jpg");
  const v = $("#mVideo");
  v.src = "/video/" + encodeURIComponent(r.clip) + "#t=" + r.offset;
  $("#mVideoCap").textContent = "源片段（从识别时间点开始）";
  $("#modal").classList.remove("hidden");
}

$("#btnClose").onclick = () => {
  $("#modal").classList.add("hidden");
  $("#mVideo").pause();
};
$("#modal").onclick = (e) => { if (e.target.id === "modal") $("#btnClose").click(); };

$("#btnUp").onclick = () => $("#fileInput").click();
$("#fileInput").onchange = () => uploadFiles($("#fileInput").files);

async function uploadFiles(files) {
  if (!files || !files.length) return;
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  $("#hint").textContent = `上传 ${files.length} 个文件…`;
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    $("#hint").textContent = `已上传 ${j.saved.length} 个，加入队列 ${j.queued}`;
    setTimeout(refresh, 1200);
  } catch (e) {
    $("#hint").textContent = "上传失败：" + e.message;
  }
}

let dragN = 0;
document.addEventListener("dragenter", (e) => { e.preventDefault(); dragN++; $("#drop").classList.remove("hidden"); });
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("dragleave", () => { if (--dragN <= 0) $("#drop").classList.add("hidden"); });
document.addEventListener("drop", (e) => {
  e.preventDefault(); dragN = 0; $("#drop").classList.add("hidden");
  uploadFiles(e.dataTransfer.files);
});

$("#btnScan").onclick = async () => {
  $("#hint").textContent = "已加入队列，处理中…";
  const r = await j("/api/scan", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  });
  $("#hint").textContent = `新增 ${r.queued} 个片段`;
  setTimeout(refresh, 1500);
};
$("#fDate").onchange = refresh;
$("#fPlate").oninput = () => { clearTimeout(window._t); window._t = setTimeout(refresh, 300); };
$("#btnClear").onclick = () => { $("#fDate").value = ""; $("#fPlate").value = ""; refresh(); };

refresh();
setInterval(refresh, 5000);
