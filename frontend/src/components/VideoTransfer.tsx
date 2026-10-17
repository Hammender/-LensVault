import { useEffect, useRef, useState } from "react";
import { authFetch, jsonHeaders, parseResponse, withWorkspaceContext } from "../lib/apiClient";
import "./MediaSource.css";

type Issue = { id?: number; index?: number; message: string };
type Job = { id: string; status: string; message?: string; download_url?: string; result: {
  total?: number; processed?: number; exported?: number; imported?: number; duplicates?: number;
  errors?: Issue[]; warnings?: Issue[];
} };
type Props = {
  canImport: boolean; selectedIds: number[]; categoryIds: number[]; personIds: number[];
  query: string; videoType: string; onImported: () => void;
};
const states: Record<string, string> = { queued: "排队中", pending: "排队中", running: "处理中", ready: "可下载", completed: "已完成", failed: "失败", expired: "已过期" };

export default function VideoTransfer(props: Props) {
  const [exports, setExports] = useState<Job[]>([]);
  const [imports, setImports] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [showJobs, setShowJobs] = useState(false);
  const previousImports = useRef(new Map<string, string>());
  const refreshList = useRef(props.onImported);
  refreshList.current = props.onImported;
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [exportJobs, importJobs] = await Promise.all([
          authFetch("/api/videos/exports", { signal: controller.signal }).then(parseResponse<Job[]>),
          authFetch("/api/videos/imports", { signal: controller.signal }).then(parseResponse<Job[]>)
        ]);
        if (!active) return;
        setExports(exportJobs); setImports(importJobs);
        for (const job of importJobs) {
          const previous = previousImports.current.get(job.id);
          if (previous && previous !== "completed" && job.status === "completed") refreshList.current();
          previousImports.current.set(job.id, job.status);
        }
        if ([...exportJobs, ...importJobs].some((job) => ["queued", "pending", "running"].includes(job.status))) timer = setTimeout(() => void poll(), 3000);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "任务查询失败");
      }
    }
    void poll();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [refresh]);
  async function exportVideos(scope: "all" | "selected" | "filtered") {
    setBusy(true); setError("");
    try {
      await authFetch("/api/videos/exports", { method: "POST", headers: jsonHeaders, body: JSON.stringify({
        scope, video_ids: props.selectedIds, category_tag_ids: props.categoryIds, person_ids: props.personIds,
        query: props.query, video_type: props.videoType === "all" ? null : props.videoType
      }) }).then(parseResponse<Job>);
      setShowJobs(true); setRefresh((value) => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "导出失败"); }
    finally { setBusy(false); }
  }
  async function importZip(file: File) {
    setBusy(true); setError("");
    try {
      const form = new FormData(); form.append("file", file);
      const job = await authFetch("/api/videos/import-zip", { method: "POST", body: form }).then(parseResponse<Job>);
      previousImports.current.set(job.id, job.status);
      setShowJobs(true); setRefresh((value) => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "导入失败"); }
    finally { setBusy(false); }
  }
  function jobs(items: Job[], label: string) {
    return items.map((job) => <div key={job.id}>
      <strong>{label} · {states[job.status] || job.status}</strong>{" "}
      {job.message || (job.result.total !== undefined ? `${job.result.processed ?? 0}/${job.result.total}` : "")}
      {job.download_url && <> · <a href={withWorkspaceContext(job.download_url)}>下载 ZIP</a> <small>（保留24小时）</small></>}
      {((job.result.errors?.length ?? 0) + (job.result.warnings?.length ?? 0)) > 0 && <details><summary>查看报告</summary><ul>{[...(job.result.errors || []), ...(job.result.warnings || [])].map((issue, index) => <li key={index}>{issue.id !== undefined ? `视频 ${issue.id}：` : issue.index !== undefined ? `第 ${issue.index + 1} 项：` : ""}{issue.message}</li>)}</ul></details>}
    </div>);
  }
  return <section className="video-transfer" aria-label="视频素材包导入导出">
    <div className="video-transfer-actions">
      <strong>素材包</strong>
      <button disabled={busy || !props.selectedIds.length} onClick={() => void exportVideos("selected")}>导出选中（{props.selectedIds.length}）</button>
      <button disabled={busy} onClick={() => void exportVideos("filtered")}>导出当前筛选</button>
      <button disabled={busy} onClick={() => void exportVideos("all")}>导出全部</button>
      {props.canImport && <label>导入视频 ZIP <input aria-label="选择视频ZIP素材包" type="file" accept=".zip" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void importZip(file); event.target.value = ""; }} /></label>}
      <button onClick={() => { setShowJobs(!showJobs); setRefresh((value) => value + 1); }}>{showJobs ? "收起任务" : "查看任务"}</button>
    </div>
    {busy && <p role="status">正在提交，请稍候…</p>}
    {error && <p role="alert">{error} <button onClick={() => setRefresh((value) => value + 1)}>刷新任务</button></p>}
    {showJobs && <div className="video-transfer-jobs">{jobs(exports, "导出")}{jobs(imports, "导入")}{!exports.length && !imports.length && <p>暂无素材包任务。</p>}</div>}
  </section>;
}
