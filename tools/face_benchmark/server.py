from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .geometry import parse_bbox, target_bbox_in_crop
from .store import connect_benchmark


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>人脸评测标注</title><style>
*{box-sizing:border-box}body{margin:0;background:#eef1f3;color:#18212a;font:14px system-ui,"Microsoft YaHei",sans-serif;letter-spacing:0}
button,input,select,textarea{font:inherit;letter-spacing:0}header{height:54px;background:#fff;border-bottom:1px solid #cdd4da;display:flex;align-items:center;gap:14px;padding:0 18px}
header strong{font-size:16px}.muted{color:#63717d}.filters{margin-left:auto;display:flex;gap:8px;align-items:center}.filters select,.jump input{height:34px;border:1px solid #aeb9c2;border-radius:4px;background:#fff;padding:0 8px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 380px;height:calc(100vh - 54px)}.viewer{position:relative;overflow:hidden;background:#272d32}
.media-stage{position:absolute;inset:18px;display:flex;align-items:center;justify-content:center}.viewer img{width:100%;height:100%;object-fit:contain}.empty{color:#dbe1e5}
.target-box{display:none;position:absolute;border:3px solid #48e092;box-shadow:0 0 0 1px rgba(0,0,0,.75),inset 0 0 0 1px rgba(0,0,0,.45);pointer-events:none}.view-tools{position:absolute;z-index:2;top:12px;left:12px;display:flex;align-items:center;gap:8px}.segmented{display:flex;background:#fff;border:1px solid #909ca5;border-radius:4px;overflow:hidden}.segmented button{min-height:32px;border:0;border-right:1px solid #b5bec5;border-radius:0;padding:5px 11px}.segmented button:last-child{border-right:0}.segmented button.active{background:#146b75;color:#fff}.target-key{display:flex;align-items:center;gap:6px;color:#fff;background:rgba(17,22,26,.82);padding:6px 8px;border-radius:4px}.target-swatch{width:13px;height:13px;border:2px solid #48e092}
aside{background:#fff;border-left:1px solid #cdd4da;padding:18px;overflow:auto}
.identity{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e1e6ea;padding-bottom:12px}h1{font-size:16px;margin:0}.badge{font-variant-numeric:tabular-nums;color:#53616d}
.row{margin:15px 0}label{display:block;font-weight:600;margin-bottom:6px}input,textarea{width:100%;padding:9px;border:1px solid #aeb9c2;border-radius:4px;background:#fff}textarea{height:70px;resize:vertical}
.search{display:grid;grid-template-columns:1fr 38px;gap:6px}.search button{font-size:17px}.people{border:1px solid #d5dce1;border-radius:4px;margin-top:6px;max-height:150px;overflow:auto}.people:empty{display:none}
.person-result{display:block;width:100%;border:0;border-bottom:1px solid #e6eaed;background:#fff;text-align:left;padding:9px}.person-result:hover,.person-result:focus{background:#eef5f8}.person-result:last-child{border-bottom:0}
.selected{padding:9px;background:#e7f0f2;border-left:3px solid #15707a;margin-top:8px}.references{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}.references img{width:100%;aspect-ratio:1;object-fit:cover;background:#e5e8ea}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:16px}button{min-height:36px;border:1px solid #9da9b3;background:#fff;border-radius:4px;padding:7px 10px;cursor:pointer;color:#18212a}
button:hover{background:#f0f3f5}button.primary{background:#146b75;color:#fff;border-color:#146b75}button.primary:hover{background:#0e5961}button:disabled{opacity:.45;cursor:default}
.navigation{display:grid;grid-template-columns:40px 1fr 40px;gap:8px;border-top:1px solid #e1e6ea;margin-top:18px;padding-top:14px}.jump{display:grid;grid-template-columns:1fr auto;gap:6px}.statusline{font-size:12px;color:#63717d;margin-top:10px;min-height:18px}
@media(max-width:820px){header{height:auto;min-height:54px;flex-wrap:wrap;padding:10px}.filters{margin-left:0;width:100%;overflow:auto}.layout{grid-template-columns:1fr;grid-template-rows:50vh auto;height:auto}.viewer{height:50vh}.media-stage{inset:12px}aside{border-left:0;border-top:1px solid #cdd4da}.references{grid-template-columns:repeat(3,1fr)}}
</style></head><body>
<header><strong>人脸评测标注</strong><span id="progress" class="muted"></span><div class="filters">
<select id="kind" aria-label="题型"><option value="face">身份题</option><option value="detection">检测题</option></select>
<select id="statusFilter" aria-label="标注状态"><option value="pending">待标注</option><option value="labeled">已标注复查</option><option value="skipped">已跳过</option><option value="all">全部状态</option></select>
<select id="split" aria-label="数据分区"><option value="all">全部分区</option><option value="calibration">Calibration</option><option value="holdout">Holdout</option></select>
</div></header>
<main class="layout"><section class="viewer"><div id="viewTools" class="view-tools"><div class="segmented" aria-label="图片视图"><button id="cropView" class="active" aria-pressed="true">裁剪图</button><button id="originalView" aria-pressed="false">原图</button></div><span class="target-key"><span class="target-swatch"></span>目标脸</span></div><div id="mediaStage" class="media-stage"><img id="image" alt="待标注图片"><span id="targetBox" class="target-box"></span><span id="empty" class="empty"></span></div></section><aside>
<div class="identity"><h1 id="title">标注项</h1><span id="itemState" class="badge"></span></div>
<div id="faceForm"><div class="row"><label for="personSearch">真实人物</label><div class="search"><input id="personSearch" autocomplete="off" placeholder="输入姓名"><button id="searchButton" title="搜索人物" aria-label="搜索人物">⌕</button></div><div id="people" class="people"></div><div id="selectedPerson"></div><div id="references" class="references"></div></div></div>
<div id="detectionForm"><div class="row"><label for="faceCount">真实人脸数</label><input id="faceCount" type="number" min="0" step="1"></div></div>
<div class="row"><label for="notes">备注</label><textarea id="notes" maxlength="2000"></textarea></div>
<div class="actions"><button id="save" class="primary">保存标注</button><button id="unknown">未知人物</button><button id="skip">跳过</button><button id="reload">放弃修改</button></div>
<div class="navigation"><button id="previous" title="上一项" aria-label="上一项">←</button><div class="jump"><input id="jumpId" type="number" min="1" placeholder="项目 ID"><button id="jump">跳转</button></div><button id="next" title="下一项" aria-label="下一项">→</button></div>
<div id="statusline" class="statusline"></div></aside></main>
<script>
const $=id=>document.getElementById(id);let items=[],index=-1,current=null,selectedPerson=null,viewMode='crop';
async function api(path,options){const response=await fetch(path,options);const value=await response.json().catch(()=>({error:'响应格式无效'}));if(!response.ok)throw new Error(value.error||'请求失败');return value}
function setMessage(value){$('statusline').textContent=value||''}
function params(){return new URLSearchParams({kind:$('kind').value,status:$('statusFilter').value,split:$('split').value})}
async function loadItems(preferId,preferIndex=0){setMessage('');const state=await api('/api/items?'+params());items=state.items;$('progress').textContent=`已处理 ${state.reviewed} / ${state.total}`;let target=preferId?items.findIndex(x=>x.id===preferId):-1;index=target>=0?target:(items.length?Math.min(preferIndex,items.length-1):-1);render()}
function setViewMode(mode){viewMode=mode;$('cropView').classList.toggle('active',mode==='crop');$('originalView').classList.toggle('active',mode==='original');$('cropView').setAttribute('aria-pressed',String(mode==='crop'));$('originalView').setAttribute('aria-pressed',String(mode==='original'));renderMedia()}
function positionTargetBox(){const box=$('targetBox'),image=$('image');if(!current||current.kind!=='face'||!image.naturalWidth||!image.naturalHeight)return box.style.display='none';const target=viewMode==='crop'?current.target_bbox_crop:current.target_bbox_original;if(!target)return box.style.display='none';const stage=$('mediaStage'),scale=Math.min(stage.clientWidth/image.naturalWidth,stage.clientHeight/image.naturalHeight),width=image.naturalWidth*scale,height=image.naturalHeight*scale,offsetX=(stage.clientWidth-width)/2,offsetY=(stage.clientHeight-height)/2;box.style.left=(offsetX+target[0]*scale)+'px';box.style.top=(offsetY+target[1]*scale)+'px';box.style.width=((target[2]-target[0])*scale)+'px';box.style.height=((target[3]-target[1])*scale)+'px';box.style.display='block'}
function renderMedia(){const face=current&&current.kind==='face';$('viewTools').style.display=face?'flex':'none';$('targetBox').style.display='none';if(!current)return;const path=face&&viewMode==='original'?current.original_path:current.image_path;$('image').src='/media/'+encodeURI(path)}
function render(){current=index>=0?items[index]:null;selectedPerson=null;$('people').replaceChildren();$('references').replaceChildren();$('selectedPerson').replaceChildren();$('personSearch').value='';$('faceCount').value='';$('notes').value='';
 const face=$('kind').value==='face';$('faceForm').style.display=face?'block':'none';$('detectionForm').style.display=face?'none':'block';$('unknown').style.display=face?'block':'none';$('previous').disabled=index<=0;$('next').disabled=index<0||index>=items.length-1;
 if(!current){$('title').textContent='没有符合条件的项目';$('itemState').textContent='';$('image').removeAttribute('src');$('image').style.display='none';$('targetBox').style.display='none';$('viewTools').style.display='none';$('empty').textContent='当前筛选无项目';return}
 $('image').style.display='block';$('empty').textContent='';renderMedia();$('title').textContent=`项目 #${current.id}`;$('itemState').textContent=`${index+1} / ${items.length} · ${current.status_label}`;$('jumpId').value=current.id;$('notes').value=current.notes||'';
 if(current.kind==='detection'&&current.true_face_count!==null)$('faceCount').value=current.true_face_count;if(current.kind==='face'&&current.truth_person_id!==null)selectPerson({source_person_id:current.truth_person_id,display_name:current.truth_person_name},false);if(current.kind==='face'&&current.truth_is_unknown)$('selectedPerson').textContent='当前标注：未知人物'}
async function searchPeople(){const query=$('personSearch').value.trim();$('people').replaceChildren();if(!query)return;const values=await api('/api/people?q='+encodeURIComponent(query));for(const person of values){const button=document.createElement('button');button.className='person-result';button.textContent=`${person.display_name}  #${person.source_person_id}`;button.onclick=()=>selectPerson(person,true);$('people').append(button)}}
async function selectPerson(person,loadReferences){selectedPerson=person;$('people').replaceChildren();$('selectedPerson').textContent='';const selected=document.createElement('div');selected.className='selected';selected.textContent=`${person.display_name}  #${person.source_person_id}`;$('selectedPerson').append(selected);$('references').replaceChildren();if(loadReferences){const samples=await api(`/api/people/${person.source_person_id}/samples`);for(const sample of samples){const img=document.createElement('img');img.src='/media/'+encodeURI(sample.image_path);img.alt=person.display_name;$('references').append(img)}}}
async function submit(body){if(!current)return;body.notes=$('notes').value;const oldId=current.id,oldIndex=index;await api(`/api/items/${current.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});await loadItems(oldId,oldIndex);setMessage('已保存')}
async function save(){if(!current)return;if(current.kind==='detection'){const value=Number($('faceCount').value);if(!Number.isInteger(value)||value<0)return setMessage('请输入有效的人脸数');return submit({status:'labeled',true_face_count:value})}if(!selectedPerson)return setMessage('请先选择真实人物');return submit({status:'labeled',truth_person_id:selectedPerson.source_person_id,truth_is_unknown:false})}
function move(delta){const next=index+delta;if(next>=0&&next<items.length){index=next;render()}}
$('image').onload=positionTargetBox;$('cropView').onclick=()=>setViewMode('crop');$('originalView').onclick=()=>setViewMode('original');window.addEventListener('resize',positionTargetBox);new ResizeObserver(positionTargetBox).observe($('mediaStage'));
$('searchButton').onclick=()=>searchPeople().catch(e=>setMessage(e.message));$('personSearch').onkeydown=e=>{if(e.key==='Enter')searchPeople().catch(x=>setMessage(x.message))};$('save').onclick=()=>save().catch(e=>setMessage(e.message));$('unknown').onclick=()=>submit({status:'labeled',truth_person_id:null,truth_is_unknown:true}).catch(e=>setMessage(e.message));$('skip').onclick=()=>submit({status:'skipped'}).catch(e=>setMessage(e.message));$('reload').onclick=render;$('previous').onclick=()=>move(-1);$('next').onclick=()=>move(1);$('jump').onclick=()=>{const id=Number($('jumpId').value);const found=items.findIndex(x=>x.id===id);if(found<0)return setMessage('当前筛选中没有该项目');index=found;render()};for(const id of ['kind','statusFilter','split'])$(id).onchange=()=>loadItems().catch(e=>setMessage(e.message));loadItems().catch(e=>setMessage(e.message));
</script></body></html>"""


def list_label_items(
    db: sqlite3.Connection,
    *,
    kind: str,
    status: str,
    split: str,
) -> dict[str, Any]:
    if kind not in {"face", "detection"}:
        raise ValueError("题型无效。")
    if status not in {"pending", "labeled", "skipped", "all"}:
        raise ValueError("标注状态无效。")
    if split not in {"calibration", "holdout", "all"}:
        raise ValueError("数据分区无效。")
    conditions = ["i.kind = ?"]
    parameters: list[object] = [kind]
    if status != "all":
        conditions.append("i.status = ?")
        parameters.append(status)
    if split != "all":
        conditions.append("i.split = ?")
        parameters.append(split)
    where = " AND ".join(conditions)
    rows = db.execute(
        f"""SELECT i.id, i.kind, i.split, i.image_path, i.original_path, i.status,
                   i.truth_person_id, i.truth_is_unknown, i.true_face_count, i.notes, i.updated_at,
                   i.bbox_json,
                   p.display_name AS truth_person_name
            FROM items i LEFT JOIN persons p ON p.source_person_id = i.truth_person_id
            WHERE {where} ORDER BY i.id""",
        parameters,
    ).fetchall()
    total_conditions = ["kind = ?"]
    total_parameters: list[object] = [kind]
    if split != "all":
        total_conditions.append("split = ?")
        total_parameters.append(split)
    total_where = " AND ".join(total_conditions)
    total = int(db.execute(f"SELECT COUNT(*) FROM items WHERE {total_where}", total_parameters).fetchone()[0])
    reviewed = int(db.execute(
        f"SELECT COUNT(*) FROM items WHERE {total_where} AND status != 'pending'", total_parameters
    ).fetchone()[0])
    status_labels = {"pending": "待标注", "labeled": "已标注", "skipped": "已跳过"}
    items = []
    for row in rows:
        value = dict(row)
        value["truth_is_unknown"] = bool(value["truth_is_unknown"]) if value["truth_is_unknown"] is not None else None
        value["status_label"] = status_labels[value["status"]]
        bbox_json = value.pop("bbox_json")
        if value["kind"] == "face":
            original_bbox = parse_bbox(bbox_json)
            value["target_bbox_original"] = list(original_bbox)
            value["target_bbox_crop"] = list(target_bbox_in_crop(original_bbox))
        items.append(value)
    return {"items": items, "total": total, "reviewed": reviewed}


def validate_annotation(
    db: sqlite3.Connection,
    item: sqlite3.Row,
    body: Any,
) -> tuple[str, int | None, int | None, int | None, str]:
    if not isinstance(body, dict):
        raise ValueError("请求内容必须是对象。")
    status = body.get("status")
    if status not in {"labeled", "skipped"}:
        raise ValueError("标注状态无效。")
    notes = str(body.get("notes") or "").strip()
    if len(notes) > 2000:
        raise ValueError("备注不能超过 2000 字。")
    if status == "skipped":
        return status, None, None, None, notes
    if item["kind"] == "detection":
        count = body.get("true_face_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("真实人脸数无效。")
        return status, None, None, count, notes
    is_unknown = body.get("truth_is_unknown")
    person_id = body.get("truth_person_id")
    if is_unknown is True:
        if person_id is not None:
            raise ValueError("未知人物标注不能同时指定人物。")
        return status, None, 1, None, notes
    if is_unknown is not False or isinstance(person_id, bool) or not isinstance(person_id, int):
        raise ValueError("已知人物标注必须明确选择真实人物。")
    person = db.execute(
        "SELECT 1 FROM persons WHERE source_person_id = ? AND is_unknown = 0", (person_id,)
    ).fetchone()
    if person is None:
        raise ValueError("真实人物无效。")
    return status, person_id, 0, None, notes


def save_annotation(db: sqlite3.Connection, item_id: int, body: Any) -> None:
    item = db.execute("SELECT id, kind FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise LookupError("标注项不存在。")
    status, person_id, is_unknown, face_count, notes = validate_annotation(db, item, body)
    db.execute(
        """UPDATE items SET status = ?, truth_person_id = ?, truth_is_unknown = ?,
           true_face_count = ?, notes = ?, updated_at = ? WHERE id = ?""",
        (status, person_id, is_unknown, face_count, notes, datetime.now().astimezone().isoformat(), item_id),
    )
    db.commit()


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

    def _serve_media(self, encoded_relative: str) -> None:
        relative = Path(unquote(encoded_relative))
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

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            payload = PAGE.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/items":
            try:
                with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
                    value = list_label_items(
                        db,
                        kind=query.get("kind", ["face"])[0],
                        status=query.get("status", ["pending"])[0],
                        split=query.get("split", ["all"])[0],
                    )
            except ValueError as exc:
                self._error(str(exc))
                return
            self._json(value)
            return
        if parsed.path == "/api/people":
            search = query.get("q", [""])[0].strip()
            if not search:
                self._json([])
                return
            with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
                rows = db.execute(
                    """SELECT source_person_id, display_name FROM persons
                       WHERE is_unknown = 0 AND display_name LIKE ? ESCAPE '\\'
                       ORDER BY display_name LIMIT 30""",
                    (f"%{search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%",),
                ).fetchall()
            self._json([dict(row) for row in rows])
            return
        if parsed.path.startswith("/api/people/") and parsed.path.endswith("/samples"):
            try:
                person_id = int(parsed.path.split("/")[3])
            except (ValueError, IndexError):
                self._error("人物 ID 无效。")
                return
            with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
                rows = db.execute(
                    "SELECT image_path FROM samples WHERE source_person_id = ? ORDER BY source_sample_id LIMIT 12",
                    (person_id,),
                ).fetchall()
            self._json([dict(row) for row in rows])
            return
        if parsed.path.startswith("/media/"):
            self._serve_media(parsed.path[len("/media/") :])
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
            if length <= 0 or length > 16_384:
                raise ValueError
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._error("请求格式无效。")
            return
        with connect_benchmark(self.snapshot_dir / "benchmark.db") as db:
            try:
                save_annotation(db, item_id, body)
            except LookupError as exc:
                self._error(str(exc), HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._error(str(exc))
                return
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
