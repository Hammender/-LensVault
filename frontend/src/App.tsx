import { useEffect, useMemo, useState } from "react";

import {
  addSamples,
  assignCluster,
  createPerson,
  getPhoto,
  getTask,
  importPhotos,
  listClusters,
  listPersons,
  listPhotos,
  removePhotoTag,
  reprocessPhoto
} from "./api";
import type { Cluster, Person, PhotoDetail, PhotoListItem, Task } from "./types";

const galleryPageSize = 24;

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "No EXIF time";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export default function App() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [photos, setPhotos] = useState<PhotoListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selectedPhoto, setSelectedPhoto] = useState<PhotoDetail | null>(null);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [task, setTask] = useState<Task | null>(null);
  const [personName, setPersonName] = useState("");
  const [samplePersonId, setSamplePersonId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedNames = useMemo(
    () => persons.filter((person) => selectedIds.includes(person.id)).map((person) => person.name),
    [persons, selectedIds]
  );

  async function refreshPersons() {
    const next = await listPersons();
    setPersons(next);
    if (samplePersonId === null && next.length > 0) {
      setSamplePersonId(next[0].id);
    }
  }

  async function refreshPhotos(nextOffset = offset, ids = selectedIds) {
    const response = await listPhotos(ids, nextOffset, galleryPageSize);
    setPhotos(response.items);
    setTotal(response.total);
    setOffset(response.offset);
  }

  async function refreshClusters() {
    setClusters(await listClusters());
  }

  useEffect(() => {
    void (async () => {
      try {
        await refreshPersons();
        await refreshPhotos(0, []);
        await refreshClusters();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Failed to load app data.");
      }
    })();
  }, []);

  useEffect(() => {
    if (!task || task.status === "completed" || task.status === "failed") {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(task.id);
        setTask(nextTask);
        if (nextTask.status === "completed") {
          await refreshPhotos(0, selectedIds);
          await refreshClusters();
          await refreshPersons();
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Task polling failed.");
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedIds, task]);

  async function handleCreatePerson() {
    if (!personName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const person = await createPerson(personName.trim());
      setPersonName("");
      await refreshPersons();
      setSamplePersonId(person.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to create person.");
    } finally {
      setBusy(false);
    }
  }

  async function handleImport(files: FileList | null) {
    if (!files || files.length === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const nextTask = await importPhotos(Array.from(files));
      setTask(nextTask);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to import files.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSampleUpload(files: FileList | null) {
    if (!files || files.length === 0 || samplePersonId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addSamples(samplePersonId, Array.from(files));
      await refreshPersons();
      await refreshPhotos(0, selectedIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to upload samples.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSelectTags(nextIds: number[]) {
    setSelectedIds(nextIds);
    setSelectedPhoto(null);
    setError(null);
    try {
      await refreshPhotos(0, nextIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to load gallery.");
    }
  }

  async function openPhoto(photoId: number) {
    setError(null);
    try {
      setSelectedPhoto(await getPhoto(photoId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to load photo.");
    }
  }

  async function handleAssignCluster(clusterKey: string) {
    const proposed = window.prompt("输入人物名称，将这一组人脸归并到该人物：");
    if (!proposed?.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await assignCluster(clusterKey, proposed.trim());
      await refreshClusters();
      await refreshPersons();
      await refreshPhotos(0, selectedIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to assign cluster.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemoveTag(photoId: number, personId: number) {
    setBusy(true);
    setError(null);
    try {
      await removePhotoTag(photoId, personId);
      const detail = await getPhoto(photoId);
      setSelectedPhoto(detail);
      await refreshPhotos(offset, selectedIds);
      await refreshPersons();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to remove tag.");
    } finally {
      setBusy(false);
    }
  }

  async function handleReprocess(photoId: number) {
    setBusy(true);
    setError(null);
    try {
      const detail = await reprocessPhoto(photoId);
      setSelectedPhoto(detail);
      await refreshClusters();
      await refreshPhotos(offset, selectedIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to reprocess photo.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <header className="hero">
        <div>
          <p className="eyebrow">Local Face Archive</p>
          <h1>PictureShow</h1>
          <p className="hero-copy">
            用 MinIO 封装原图，用本地模型做识别，把你的私人照片库整理成一面可筛选、可校正、可追溯的编辑墙。
          </p>
        </div>
        <div className="hero-meta">
          <span>{persons.length} 人物标签</span>
          <span>{total} 当前检索结果</span>
          <span>{clusters.length} 待确认簇</span>
        </div>
      </header>

      <main className="layout-grid">
        <aside className="left-rail panel reveal-one">
          <section>
            <div className="section-head">
              <p>导入照片</p>
              <span>原图写入 MinIO</span>
            </div>
            <label className="file-drop">
              <input type="file" multiple accept="image/*" onChange={(event) => void handleImport(event.target.files)} />
              <strong>拖入或选择照片</strong>
              <span>支持批量上传，后台异步识别与聚类。</span>
            </label>
          </section>

          <section>
            <div className="section-head">
              <p>新建人物</p>
              <span>先建库，再喂样本照</span>
            </div>
            <div className="stacked-inputs">
              <input value={personName} onChange={(event) => setPersonName(event.target.value)} placeholder="例如：李雷" />
              <button onClick={() => void handleCreatePerson()} disabled={busy}>创建人物</button>
            </div>
          </section>

          <section>
            <div className="section-head">
              <p>人物样本</p>
              <span>上传后会写入人物特征库</span>
            </div>
            <select value={samplePersonId ?? ""} onChange={(event) => setSamplePersonId(Number(event.target.value))}>
              {persons.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name}
                </option>
              ))}
            </select>
            <label className="subtle-upload">
              <input type="file" multiple accept="image/*" onChange={(event) => void handleSampleUpload(event.target.files)} />
              选择样本照
            </label>
          </section>

          <section>
            <div className="section-head">
              <p>识别任务</p>
              <span>后台运行状态</span>
            </div>
            {task ? (
              <div className="task-card">
                <strong>{task.status}</strong>
                <div className="progress-bar">
                  <span style={{ width: `${Math.round(task.progress * 100)}%` }} />
                </div>
                <p>{task.message}</p>
              </div>
            ) : (
              <p className="muted">还没有进行中的导入任务。</p>
            )}
          </section>

          <section>
            <div className="section-head">
              <p>待确认簇</p>
              <span>将未知人脸归并命名</span>
            </div>
            <div className="cluster-list">
              {clusters.map((cluster) => (
                <button key={cluster.cluster_key} className="cluster-card" onClick={() => void handleAssignCluster(cluster.cluster_key)}>
                  <img src={`${cluster.sample.thumbnail_url}?width=240`} alt={cluster.cluster_key} />
                  <div>
                    <strong>{cluster.cluster_key}</strong>
                    <span>{cluster.count} 张待确认人脸</span>
                  </div>
                </button>
              ))}
              {clusters.length === 0 && <p className="muted">当前没有待确认簇。</p>}
            </div>
          </section>
        </aside>

        <section className="gallery-stage reveal-two">
          <div className="stage-topbar panel">
            <div>
              <p className="eyebrow">Tag Query</p>
              <h2>人物筛选</h2>
            </div>
            <div className="selected-copy">{selectedNames.length ? selectedNames.join(" / ") : "当前显示全部照片"}</div>
          </div>

          <div className="tag-cloud panel">
            {persons.map((person) => {
              const active = selectedIds.includes(person.id);
              return (
                <button
                  key={person.id}
                  className={active ? "tag-chip active" : "tag-chip"}
                  onClick={() => {
                    const nextIds = active ? selectedIds.filter((id) => id !== person.id) : [...selectedIds, person.id];
                    void handleSelectTags(nextIds);
                  }}
                >
                  <span>{person.name}</span>
                  <small>{person.photo_count}</small>
                </button>
              );
            })}
          </div>

          <div className="gallery-grid">
            {photos.map((photo, index) => (
              <button
                key={photo.id}
                className="photo-card"
                style={{ animationDelay: `${index * 45}ms` }}
                onClick={() => void openPhoto(photo.id)}
              >
                <img src={`${photo.thumbnail_url}?width=720`} alt={photo.filename} loading="lazy" />
                <div className="photo-overlay">
                  <p>{photo.filename}</p>
                  <span>{formatDate(photo.taken_at)}</span>
                  <div className="mini-tags">
                    {photo.tags.map((tag) => (
                      <small key={`${photo.id}-${tag.person_id}`}>{tag.person_name}</small>
                    ))}
                  </div>
                </div>
              </button>
            ))}
          </div>

          <div className="pagination-row panel">
            <button disabled={offset === 0} onClick={() => void refreshPhotos(Math.max(0, offset - galleryPageSize), selectedIds)}>
              上一页
            </button>
            <span>
              {offset + 1} - {Math.min(offset + galleryPageSize, total)} / {total}
            </span>
            <button
              disabled={offset + galleryPageSize >= total}
              onClick={() => void refreshPhotos(offset + galleryPageSize, selectedIds)}
            >
              下一页
            </button>
          </div>
        </section>

        <aside className="right-rail panel reveal-three">
          <div className="section-head">
            <p>原图查看器</p>
            <span>点击中间图片卡片打开</span>
          </div>
          {selectedPhoto ? (
            <>
              <a className="viewer-image-wrap" href={selectedPhoto.original_url} target="_blank" rel="noreferrer">
                <img className="viewer-image" src={selectedPhoto.original_url} alt={selectedPhoto.filename} />
                <span className="viewer-badge">打开原图</span>
              </a>
              <div className="viewer-meta">
                <h3>{selectedPhoto.filename}</h3>
                <p>{selectedPhoto.width} × {selectedPhoto.height}</p>
                <p>{formatDate(selectedPhoto.taken_at || selectedPhoto.created_at)}</p>
              </div>
              <div className="viewer-tags">
                {selectedPhoto.tags.map((tag) => (
                  <button key={tag.person_id} className="viewer-tag" onClick={() => void handleRemoveTag(selectedPhoto.id, tag.person_id)}>
                    {tag.person_name}
                  </button>
                ))}
              </div>
              <div className="viewer-actions">
                <button onClick={() => void handleReprocess(selectedPhoto.id)}>重新识别</button>
                <a href={selectedPhoto.original_url} target="_blank" rel="noreferrer">
                  新窗口原图
                </a>
              </div>
              <div className="face-boxes">
                {selectedPhoto.faces.map((face) => (
                  <article key={face.id}>
                    <strong>{face.cluster_key || "matched"}</strong>
                    <span>{face.match_score ? `score ${face.match_score.toFixed(3)}` : "待确认"}</span>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className="viewer-empty">
              <p>右侧保持原图视角。</p>
              <span>中间区域做筛选和浏览，右侧用于无压缩查看与修正标签。</span>
            </div>
          )}

          {error && <div className="error-box">{error}</div>}
        </aside>
      </main>
    </div>
  );
}
