import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { createFaceCase } from "../api/faceCases";
import { listPersonSamples } from "../api/people";
import { caseAnswerLabels, caseCreatePayload, caseIssueLabels } from "../lib/faceCases";
import { filterPersonMatches } from "../lib/personPicker";
import type { Face, GalleryPhotoDetail } from "../types/gallery";
import type { Person } from "../types/people";
import type { CaseAnswerType, CaseIssueType, FaceCaseDetail } from "../types/faceCases";
import FaceCaseImage from "./FaceCaseImage";
import SearchableSelect from "./SearchableSelect";
import "./FaceCases.css";

type Props = { photo: GalleryPhotoDetail; face: Face; persons: Person[]; onClose: () => void; onSaved: (item: FaceCaseDetail) => void };
export default function FaceCaseDialog({ photo, face, persons, onClose, onSaved }: Props) {
  const initial = face.binding_source === "manual" ? persons.find((p) => p.id === face.matched_person_id && !p.is_unknown) : undefined;
  const [personId, setPersonId] = useState(initial ? String(initial.id) : "");
  const [query, setQuery] = useState(initial?.display_name ?? "");
  const initialExcluded = persons.find((p) => !p.is_unknown && p.id === face.matched_person_id)
    ?? persons.find((p) => !p.is_unknown && p.id === face.predicted_person_id);
  const [answerType, setAnswerType] = useState<CaseAnswerType>("known_person");
  const [excludedPersonId, setExcludedPersonId] = useState(initialExcluded ? String(initialExcluded.id) : "");
  const [excludedQuery, setExcludedQuery] = useState(initialExcluded?.display_name ?? "");
  const [issue, setIssue] = useState<CaseIssueType>(face.binding_source === "manual" ? "other" : face.needs_review || face.matched_person_is_unknown ? "unknown" : "wrong_person");
  const [notes, setNotes] = useState("");
  const [bind, setBind] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readySamples, setReadySamples] = useState<number | null>(null);
  const [sampleNotice, setSampleNotice] = useState("");
  const dialog = useRef<HTMLElement>(null);
  const activePersonId = answerType === "known_person" ? personId : answerType === "not_person" ? excludedPersonId : "";
  const activeQuery = answerType === "not_person" ? excludedQuery : query;
  const canSave = answerType === "out_of_library" || Boolean(activePersonId);
  useEffect(() => {
    let active = true;
    setReadySamples(null); setSampleNotice("");
    if (activePersonId) void listPersonSamples(Number(activePersonId)).then((samples) => {
      if (active) setReadySamples(samples.filter((sample) => sample.status === "ready").length);
    }).catch(() => { if (active) setSampleNotice("暂时无法核对参考样本，仍可保存案例。"); });
    return () => { active = false; };
  }, [activePersonId]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    return () => { document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, []);
  async function save() {
    if (!canSave || busy) return;
    setBusy(true); setError("");
    try {
      onSaved(await createFaceCase(caseCreatePayload(photo.id, face, { answerType, personId, excludedPersonId, issue, notes, bind })));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "记录失败，请重试"); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onClick={() => { if (!busy) onClose(); }}>
    <section ref={dialog} tabIndex={-1} className="export-modal face-case-dialog" role="dialog" aria-modal="true" aria-labelledby="face-case-title"
      onClick={(event) => event.stopPropagation()} onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape" && !event.defaultPrevented && !busy) onClose();
        if (event.key === "Tab") {
          const controls = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]');
          if (!controls?.length) return;
          const first = controls[0], last = controls[controls.length - 1];
          if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      }}>
      <header className="face-case-heading"><div><h2 id="face-case-title">记录识别异常</h2><p>这张脸的识别结果不合理，标注你能确定的结论。</p></div>
        <button type="button" className="ghost-button" disabled={busy} aria-label="关闭" onClick={onClose}><X size={18} /></button></header>
      <div className="face-case-form-layout">
        <div><FaceCaseImage url={photo.original_url} width={photo.display_width ?? 0} height={photo.display_height ?? 0} face={face} />
          <p className="tip">人脸 {face.face_index} · 当前绑定：{face.matched_person_name ?? "未绑定"}</p>
          <p className="tip">第一候选：{face.predicted_person_name ?? "无"} · 第二候选：{face.second_person_name ?? "无"}</p>
        </div>
        <div className="face-case-fields">
          <label htmlFor="case-answer">人工结论</label>
          <select id="case-answer" value={answerType} disabled={busy} onChange={(event) => {
            const next = event.target.value as CaseAnswerType;
            setAnswerType(next); setBind(false);
            if (next !== "known_person") setIssue("wrong_person");
          }}>{Object.entries(caseAnswerLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
          {answerType !== "out_of_library" && <>
          <label htmlFor="case-person">{answerType === "not_person" ? "明确不是哪个人物（必填）" : "正确人物（必填）"}</label>
          <SearchableSelect id="case-person" value={activePersonId} query={activeQuery} options={filterPersonMatches(persons.filter((p) => !p.is_unknown), activeQuery).map((p) => ({ value: String(p.id), label: p.display_name }))}
            placeholder="搜索全部正式人物" emptyText="没有匹配的人物" disabled={busy}
            onQueryChange={(value) => { if (answerType === "not_person") { setExcludedQuery(value); setExcludedPersonId(""); } else { setQuery(value); setPersonId(""); } }}
            onSelect={(option) => { if (answerType === "not_person") { setExcludedPersonId(option.value); setExcludedQuery(option.label); } else { setPersonId(option.value); setQuery(option.label); } }} />
          </>}
          {answerType === "out_of_library" && <p className="tip">确认这张脸不属于样本库中的任何人物，无需为路人创建人物。</p>}
          {answerType === "not_person" && <p className="tip">仅记录不是所选人物，不推断是否属于库中其他人物。</p>}
          {answerType !== "out_of_library" && readySamples === 0 && <p className="face-case-warning">所选人物当前没有就绪样本，仍可记录此案例。</p>}
          {sampleNotice && <p className="tip">{sampleNotice}</p>}
          <label htmlFor="case-issue">异常类型</label>
          <select id="case-issue" value={issue} disabled={busy} onChange={(event) => setIssue(event.target.value as CaseIssueType)}>{Object.entries(caseIssueLabels).filter(([key]) => answerType === "known_person" || key !== "unknown").map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
          <label htmlFor="case-notes">备注（可选）</label>
          <textarea id="case-notes" value={notes} maxLength={4000} rows={4} disabled={busy} placeholder="例如：正脸清晰，但两个候选都不是她" onChange={(event) => setNotes(event.target.value)} />
          {answerType === "known_person" ? <>
            <label className="face-case-check"><input type="checkbox" checked={bind} disabled={busy || face.promoted_sample_id !== null} onChange={(event) => setBind(event.target.checked)} />同时改绑为正确人物</label>
            {face.promoted_sample_id !== null && <p className="tip">该人脸已加入样本库，可仅记录；改绑需先撤销样本。</p>}
          </> : <p className="tip">仅保存异常案例，不改变人脸绑定，不创建人物或样本。</p>}
          {face.binding_source === "manual" && <p className="tip">这张脸已经人工绑定，案例会注明当前状态，并保留现有算法候选。</p>}
          <p className="tip">独立保留原图和识别信息；参考样本保存清单。记录不会自动加入样本库。</p>
        </div>
      </div>
      {error && <p role="alert" className="inline-error">{error}</p>}
      <footer className="face-case-actions"><button type="button" className="ghost-button" disabled={busy} onClick={onClose}>取消</button><button type="button" disabled={busy || !canSave || !face.face_revision} onClick={() => void save()}>{busy ? "正在保存…" : answerType === "known_person" && bind ? "保存并改绑" : "保存案例"}</button></footer>
    </section>
  </div>;
}
