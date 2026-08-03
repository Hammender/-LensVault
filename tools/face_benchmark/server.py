from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from .store import connect_benchmark


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>人脸评测标注</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#1f2933;font:14px system-ui,sans-serif}
header{height:52px;background:#fff;border-bottom:1px solid #d9dee5;display:flex;align-items:center;gap:18px;padding:0 20px}
header strong{font-size:16px}.muted{color:#697582}.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;height:calc(100vh - 52px)}
.viewer{display:flex;align-items:center;justify-content:center;padding:18px;overflow:hidden}.viewer img{max-width:100%;max-height:100%;object-fit:contain;background:#111}
aside{background:#fff;border-left:1px solid #d9dee5;padding:18px;overflow:auto}h2{font-size:16px;margin:0 0 16px}.row{margin:12px 0}
label{display:block;font-weight:600;margin-bottom:6px}input,textarea{width:100%;padding:9px;border:1px solid #b8c1cc;border-radius:4px}textarea{height:68px}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}button{border:1px solid #9da8b5;background:#fff;border-radius:4px;padding:9px;cursor:pointer}
button.primary{background:#1769aa;color:#fff;border-color:#1769aa}.meta{font-size:12px;line-height:1.7;color:#596673;border-top:1px solid #e3e7eb;margin-top:18px;padding-top:14px;word-break:break-all}
@media(max-width:760px){.layout{grid-template-columns:1fr;grid-template-rows:52vh auto;height:auto}.viewer{height:52vh}aside{border-left:0;border-top:1px solid #d9dee5}}
</style></head><body>
<header><strong>人脸评测标注</strong><span id="progress" class="muted"></span><button onclick="setKind('face')">人脸</button><button onclick="setKind('detection')">检测</button></header>
<main class="layout"><section class="viewer"><img id="image" alt="待标注图片"></section><aside><h2 id="title"></h2>
<div id="faceForm"><div class="row"><label for="person">真实人物</label><input id="person" list="people" autocomplete="off"><datalist id="people"></datalist></div></div>
<div id="detectionForm"><div class="row"><label for="faceCount">真实人脸数</label><input id="faceCount" type="number" min="0"></div></div>
<div class="row"><label for="notes">备注</label><textarea id="notes"></textarea></div>
<div class="actions"><button class="primary" onclick="saveKnown()">保存</button><button id="unknown" onclick="saveUnknown()">未知人物</button><button onclick="skip()">跳过</button><button onclick="loadNext()">下一项</button></div>
<div id="meta" class="meta"></div></aside></main>
<script>
let kind='face', current=null, people=[];
async function api(path, options){const r=await fetch(path,options);if(!r.ok)throw new Error(await r.text());return r.json()}
async function init(){people=await api('/api/people');document.getElementById('people').innerHTML=people.map(p=>`<option value="${p.source_person_id} | ${esc(p.display_name)}">`).join('');await loadNext()}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function setKind(value){kind=value;await loadNext()}
async function loadNext(){const state=await api(`/api/next?kind=${kind}`);current=state.item;document.getElementById('progress').textContent=`${state.labeled} / ${state.total}`;
 document.getElementById('faceForm').style.display=kind==='face'?'block':'none';document.getElementById('detectionForm').style.display=kind==='detection'?'block':'none';document.getElementById('unknown').style.display=kind==='face'?'block':'none';
 document.getElementById('person').value='';document.getElementById('faceCount').value='';document.getElementById('notes').value='';
 if(!current){document.getElementById('title').textContent='已完成';document.getElementById('image').removeAttribute('src');document.getElementById('meta').textContent='';return}
 document.getElementById('title').textContent=`${current.sample_bucket} · ${current.split}`;document.getElementById('image').src=`/media/${current.image_path}`;
 const m=JSON.parse(current.metadata_json);document.getElementById('meta').textContent=Object.entries(m).filter(x=>x[1]!==null).map(x=>`${x[0]}: ${Array.isArray(x[1])?x[1].join(', '):x[1]}`).join('\n')}
async function submit(body){if(!current)return;body.notes=document.getElementById('notes').value;await api(`/api/items/${current.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});await loadNext()}
async function saveKnown(){if(kind==='detection'){const n=Number(document.getElementById('faceCount').value);if(!Number.isInteger(n)||n<0)return alert('请输入真实人脸数');return submit({status:'labeled',true_face_count:n})}
 const id=Number(document.getElementById('person').value.split('|')[0].trim());if(!people.some(p=>p.source_person_id===id))return alert('请选择人物');return submit({status:'labeled',truth_person_id:id,truth_is_unknown:false})}
function saveUnknown(){return submit({status:'labeled',truth_person_id:null,truth_is_unknown:true})}function skip(){return submit({status:'skipped'})}init().catch(e=>alert(e.message));
</script></body></html>"""


class LabelHandler(BaseHTTPRequestHandler):
    snapshot_dir: Path

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            payload = PAGE.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/people":
            with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
                rows = db.execute("SELECT source_person_id, display_name FROM persons WHERE is_unknown = 0 ORDER BY display_name").fetchall()
            self._json([dict(row) for row in rows])
            return
        if parsed.path == "/api/next":
            kind = "detection" if parsed.query == "kind=detection" else "face"
            with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
                item = db.execute("SELECT * FROM items WHERE kind = ? AND status = 'pending' ORDER BY id LIMIT 1", (kind,)).fetchone()
                total = int(db.execute("SELECT COUNT(*) FROM items WHERE kind = ?", (kind,)).fetchone()[0])
                labeled = int(db.execute("SELECT COUNT(*) FROM items WHERE kind = ? AND status != 'pending'", (kind,)).fetchone()[0])
            self._json({"item": dict(item) if item else None, "total": total, "labeled": labeled})
            return
        if parsed.path.startswith("/media/"):
            relative = Path(unquote(parsed.path[len("/media/") :]))
            target = (self.snapshot_dir / relative).resolve()
            if self.snapshot_dir.resolve() not in target.parents or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/items/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            item_id = int(parsed.path.rsplit("/", 1)[1])
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._error("请求格式无效。")
            return
        with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
            item = db.execute("SELECT kind FROM items WHERE id = ?", (item_id,)).fetchone()
            if item is None:
                self._error("标注项不存在。", HTTPStatus.NOT_FOUND)
                return
            status = body.get("status")
            if status not in {"labeled", "skipped"}:
                self._error("标注状态无效。")
                return
            truth_person_id = body.get("truth_person_id")
            truth_is_unknown = body.get("truth_is_unknown")
            true_face_count = body.get("true_face_count")
            if item["kind"] == "face" and status == "labeled":
                if truth_is_unknown is not True:
                    person = db.execute("SELECT 1 FROM persons WHERE source_person_id = ? AND is_unknown = 0", (truth_person_id,)).fetchone()
                    if person is None:
                        self._error("真实人物无效。")
                        return
            if item["kind"] == "detection" and status == "labeled" and (not isinstance(true_face_count, int) or true_face_count < 0):
                self._error("真实人脸数无效。")
                return
            db.execute(
                """UPDATE items SET status = ?, truth_person_id = ?, truth_is_unknown = ?,
                   true_face_count = ?, notes = ?, updated_at = ? WHERE id = ?""",
                (status, truth_person_id, int(bool(truth_is_unknown)) if truth_is_unknown is not None else None,
                 true_face_count, str(body.get("notes") or ""), datetime.now().astimezone().isoformat(), item_id),
            )
            db.commit()
        self._json({"ok": True})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(snapshot_dir: Path, host: str, port: int) -> None:
    snapshot_dir = snapshot_dir.resolve()
    if not (snapshot_dir / "benchmark.db").is_file():
        raise RuntimeError(f"评测快照无效：{snapshot_dir}")
    handler = type("SnapshotLabelHandler", (LabelHandler,), {"snapshot_dir": snapshot_dir})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"标注工具：http://{host}:{port}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
