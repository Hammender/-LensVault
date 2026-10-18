import { useEffect, useState } from "react";
import { ArrowLeft, Download, Trash2 } from "lucide-react";
import { deleteFaceCase, exportFaceCases, getFaceCase, listFaceCases, updateFaceCaseNotes } from "../api/faceCases";
import { useConfirm } from "../components/ConfirmDialog";
import FaceCaseImage from "../components/FaceCaseImage";
import { caseAnswerLabels, caseAnswerSummary, caseIssueLabels, casePath } from "../lib/faceCases";
import { formatDate } from "../lib/utils";
import type { CaseAnswerType, CaseFilters, CaseIssueType, FaceCase, FaceCaseDetail } from "../types/faceCases";
import "../components/FaceCases.css";

type Props = { canEdit: boolean; canDelete: boolean; onBack: () => void; onOpenPhoto: (id: number) => void };
const emptyFilters: CaseFilters = { correct_person_name: "", issue_type: "", embedding_version: "", answer_type: "" };
const fromHash = () => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("case");
const score = (value: number | null | undefined) => value == null ? "未记录" : value.toFixed(4);
const rejectionLabels: Record<string, string> = { below_threshold: "低于分数阈值", insufficient_margin: "候选分差不足", no_candidate: "没有候选", candidate_not_found: "候选人物不存在" };
const sampleStatusLabels: Record<string, string> = { ready: "可用", pending: "待处理", no_face: "未检测到人脸", multi_face: "多人脸", low_quality: "质量不足", error: "处理失败" };
const qualityLabels: Record<string, string> = { good: "良好", warning: "有告警", rejected: "不合格" };

export default function FaceRecognitionCases({ canEdit, canDelete, onBack, onOpenPhoto }: Props) {
  const confirm = useConfirm();
  const [draft, setDraft] = useState<CaseFilters>({ ...emptyFilters });
  const [filters, setFilters] = useState<CaseFilters>({ ...emptyFilters });
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<FaceCase[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(fromHash);
  const [detail, setDetail] = useState<FaceCaseDetail | null>(null);
  const [notes, setNotes] = useState("");
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const change = () => setSelectedId(fromHash());
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    void listFaceCases(filters, offset).then((result) => {
      if (!active) return;
      if (result.total > 0 && offset >= result.total) { setOffset(Math.floor((result.total - 1) / 24) * 24); return; }
      setItems(result.items); setTotal(result.total);
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "案例列表加载失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, offset, version]);
  useEffect(() => {
    let active = true;
    setDetail(null); setDetailLoading(Boolean(selectedId));
    if (selectedId) void getFaceCase(selectedId).then((result) => {
      if (active) { setDetail(result); setNotes(result.notes); }
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "案例详情加载失败"); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [selectedId, version]);

  function open(id: string | null) {
    setError(""); setNotice(""); setSelectedId(id);
    window.location.hash = casePath(id ?? undefined);
  }
  async function download(ids?: string[]) {
    setBusy(true); setError(""); setNotice("");
    try {
      const { blob, filename } = await exportFaceCases(filters, ids);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = filename;
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
      setNotice("案例包已导出");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "导出失败"); }
    finally { setBusy(false); }
  }
  async function remove(item: FaceCaseDetail) {
    if (!await confirm({ title: "删除识别异常案例", message: "将删除此案例及其独立存档原图。图库图片、人物和样本库不会被删除。", confirmLabel: "删除案例", tone: "danger" })) return;
    setBusy(true); setError("");
    try {
      await deleteFaceCase(item.id); setSelectedIds((ids) => ids.filter((id) => id !== item.id)); open(null);
      setNotice("案例已删除");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "删除未完成，可重试"); }
    finally { setVersion((value) => value + 1); setBusy(false); }
  }
  async function saveNotes() {
    if (!detail) return;
    setBusy(true); setError("");
    try { setDetail(await updateFaceCaseNotes(detail.id, notes)); setVersion((value) => value + 1); setNotice("备注已保存"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "备注保存失败"); }
    finally { setBusy(false); }
  }
  const snapshot = detail?.snapshot;
  const recognition = snapshot?.recognition;
  return <main className="panel face-cases">
    <header className="face-case-heading"><div><button type="button" className="ghost-button" onClick={onBack}><ArrowLeft size={16} />返回图库</button><h2>识别异常案例</h2><p>记录漏认、错认与路人误认，供后续复盘与测评。</p></div>
      <div className="face-case-actions"><button disabled={busy || loading || total === 0} onClick={() => void download()}><Download size={16} />导出筛选结果（{total}）</button><button className="ghost-button" disabled={busy || selectedIds.length === 0} onClick={() => void download(selectedIds)}>导出勾选（{selectedIds.length}）</button></div></header>
    <form className="face-case-filters" onSubmit={(event) => { event.preventDefault(); setOffset(0); setFilters({ ...draft }); setSelectedIds([]); setError(""); }}>
      <label>相关人物<input placeholder="搜索正确人物或被排除人物" value={draft.correct_person_name} maxLength={256} onChange={(event) => setDraft({ ...draft, correct_person_name: event.target.value })} /></label>
      <label>人工结论<select value={draft.answer_type ?? ""} onChange={(event) => setDraft({ ...draft, answer_type: event.target.value as CaseAnswerType | "" })}><option value="">全部结论</option>{Object.entries(caseAnswerLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>异常类型<select value={draft.issue_type} onChange={(event) => setDraft({ ...draft, issue_type: event.target.value as CaseIssueType | "" })}><option value="">全部类型</option>{Object.entries(caseIssueLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>向量版本<input placeholder="完整版本号" value={draft.embedding_version} maxLength={64} onChange={(event) => setDraft({ ...draft, embedding_version: event.target.value })} /></label>
      <button disabled={busy}>筛选</button><button type="button" className="ghost-button" disabled={busy} onClick={() => { setDraft({ ...emptyFilters }); setFilters({ ...emptyFilters }); setOffset(0); setSelectedIds([]); }}>重置</button>
    </form>
    {error && <p className="inline-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className={`face-case-workspace${selectedId ? " has-detail" : ""}`}>
      <section aria-label="异常案例列表" aria-busy={loading}>
        <div className="face-case-list-head"><span>{loading ? "加载中…" : `${total} 条案例`}</span><button className="ghost-button" disabled={busy || !selectedIds.length} onClick={() => setSelectedIds([])}>清空勾选</button></div>
        {!loading && items.length === 0 && <div className="empty-card"><h3>还没有符合条件的案例</h3><p>遇到难以理解的识别结果时，在图片详情的「人脸」页选择「记录识别异常」。</p></div>}
        <div className="face-case-grid">{items.map((item) => <article className={`face-case-card${selectedId === item.id ? " active" : ""}`} key={item.id}>
          <label className="face-case-selection"><input type="checkbox" aria-label={`勾选 ${caseAnswerSummary(item)} 的案例`} checked={selectedIds.includes(item.id)} disabled={busy} onChange={(event) => setSelectedIds((ids) => event.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} />勾选</label>
          <button className="face-case-card-open" type="button" disabled={busy} onClick={() => open(item.id)}>
            {item.status === "active" ? <img src={item.thumbnail_url} alt={`${caseAnswerSummary(item)} 的异常案例`} loading="lazy" /> : <div className="face-case-deleting">待清理 · 可重试删除</div>}
            <span className="face-case-card-text"><strong>{caseAnswerSummary(item)}</strong><span>{caseAnswerLabels[item.answer_type]} · {caseIssueLabels[item.issue_type]}</span><small>{item.embedding_version ?? "版本未记录"}</small><small>{formatDate(item.created_at)}</small>{item.notes && <span className="face-case-note-preview">{item.notes}</span>}</span>
          </button>
        </article>)}</div>
        <div className="face-case-actions"><button disabled={busy || loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 24))}>上一页</button><span>{Math.floor(offset / 24) + 1} / {Math.max(1, Math.ceil(total / 24))}</span><button disabled={busy || loading || offset + 24 >= total} onClick={() => setOffset(offset + 24)}>下一页</button></div>
      </section>
      {selectedId && <aside className="face-case-detail" aria-label="异常案例详情" aria-busy={detailLoading}>
        <div className="face-case-heading"><h3>{detailLoading ? "加载案例…" : detail ? caseAnswerSummary(detail) : "案例无法加载"}</h3><button type="button" className="ghost-button" disabled={busy} onClick={() => open(null)}>关闭详情</button></div>
        {detail && snapshot && recognition && <>
          {detail.status === "active" ? <FaceCaseImage url={detail.original_url} width={snapshot.photo.display_width} height={snapshot.photo.display_height} face={recognition} /> : <p className="inline-error">{detail.cleanup_error ?? "案例正在清理，请重试删除"}</p>}
          <dl className="face-case-facts"><dt>人工结论</dt><dd>{caseAnswerLabels[detail.answer_type]}</dd><dt>{detail.answer_type === "not_person" ? "排除人物" : "正确身份"}</dt><dd>{caseAnswerSummary(detail)}{detail.answer_type === "known_person" && detail.correct_person_id === null && "（人物已删除）"}{detail.answer_type === "not_person" && detail.excluded_person_id === null && "（排除人物已删除，名称保留）"}</dd><dt>异常类型</dt><dd>{caseIssueLabels[detail.issue_type]}</dd><dt>记录人</dt><dd>{detail.actor_name}</dd><dt>记录时间</dt><dd>{formatDate(detail.created_at)}</dd><dt>原图</dt><dd>{snapshot.photo.filename}</dd><dt>原人脸编号</dt><dd>#{detail.source_face_id}</dd></dl>
          {detail.answer_type === "not_person" && <p className="tip">只确认不是被排除人物，尚未确定真实身份或是否属于库中其他人物。</p>}
          <h3>原识别信息</h3>
          <dl className="face-case-facts"><dt>识别记录时间</dt><dd>{formatDate(recognition.created_at)}</dd><dt>记录时绑定</dt><dd>{snapshot.binding_at_capture.person_name ?? "未绑定"}{snapshot.binding_at_capture.source === "face_manual" ? "（已人工绑定）" : ""}</dd><dt>第一候选</dt><dd>{recognition.predicted_person_name ?? "无"} / {score(recognition.match_score)}</dd><dt>第二候选</dt><dd>{recognition.second_person_name ?? "无"} / {score(recognition.second_match_score)}</dd><dt>候选分差</dt><dd>{score(recognition.match_margin)}</dd><dt>拒识原因</dt><dd>{recognition.rejection_reason ? rejectionLabels[recognition.rejection_reason] ?? recognition.rejection_reason : "未记录拒识原因"}</dd><dt>分数阈值</dt><dd>{score(recognition.decision_threshold)}</dd><dt>最小分差</dt><dd>{score(recognition.decision_min_margin)}</dd><dt>人脸大小</dt><dd>{score(recognition.face_size)} px</dd><dt>模糊度 / 偏航角</dt><dd>{score(recognition.blur_score)} / {score(recognition.pose_yaw)}</dd><dt>向量版本</dt><dd>{detail.embedding_version ?? "未记录"}</dd></dl>
          <details><summary>参考样本清单（记录时） · 就绪 {snapshot.reference_samples_at_capture.ready_count} 张</summary><p className="tip">采集于 {formatDate(snapshot.reference_samples_at_capture.captured_at)}。不包含样本图片，也不代表原识别发生时的样本库。</p>
            <p className="tip">参考人物：{snapshot.reference_samples_at_capture.person_name ?? (snapshot.schema_version === 1 ? detail.correct_person_name : "未指定")}（{snapshot.reference_samples_at_capture.role === "excluded_person" ? "被排除人物" : snapshot.reference_samples_at_capture.role === "recognized_person" ? "记录时的绑定人物" : snapshot.reference_samples_at_capture.role === null ? "无参考人物" : "正确人物"}）</p>
            <div className="face-case-table-wrap"><table><thead><tr><th>编号 / 文件名</th><th>状态 / 质量</th><th>来源</th></tr></thead><tbody>{snapshot.reference_samples_at_capture.samples.map((sample) => <tr key={sample.id}><td>#{sample.id} {sample.filename}<small>{sample.sha256}</small></td><td>{sampleStatusLabels[sample.status] ?? sample.status} / {sample.quality_status ? qualityLabels[sample.quality_status] ?? sample.quality_status : "未评级"}</td><td>{sample.source_type === "gallery_face" ? "图库裁剪" : sample.source_type === "upload" ? "上传" : sample.source_type}{sample.source_gallery_photo_id != null && ` · 图片 #${sample.source_gallery_photo_id}`}</td></tr>)}</tbody></table></div>
          </details>
          {snapshot.same_photo_sample_ids_at_capture.length > 0 && <p className="face-case-warning">记录时此图已关联样本 #{snapshot.same_photo_sample_ids_at_capture.join("、#")}，后续测评需排除同源样本。</p>}
          <details><summary>识别配置（记录时）</summary><pre>{JSON.stringify(snapshot.configuration_at_capture, null, 2)}</pre></details>
          <label className="face-case-fields" htmlFor="edit-case-notes">备注<textarea id="edit-case-notes" rows={4} maxLength={4000} value={notes} disabled={!canEdit || busy || detail.status !== "active"} onChange={(event) => setNotes(event.target.value)} /></label>
          <div className="face-case-actions">{canEdit && <button disabled={busy || detail.status !== "active" || notes === detail.notes} onClick={() => void saveNotes()}>保存备注</button>}{detail.source_photo_id !== null ? <button className="ghost-button" disabled={busy} onClick={() => onOpenPhoto(detail.source_photo_id!)}>查看图库原图</button> : <span className="tip">图库原图已删除，案例独立保留</span>}
            <button className="ghost-button" disabled={busy || detail.status !== "active"} onClick={() => void download([detail.id])}>导出此案例</button>{canDelete && <button className="ghost-button" disabled={busy} onClick={() => void remove(detail)}><Trash2 size={15} />{detail.status === "deleting" ? "重试删除" : "删除案例"}</button>}</div>
        </>}
      </aside>}
    </div>
  </main>;
}
