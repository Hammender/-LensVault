import { useEffect, useMemo, useState } from "react";

import {
  addPhotoTag,
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
    return "无 EXIF 时间";
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
  const [clusterName, setClusterName] = useState("");
  const [activeClusterKey, setActiveClusterKey] = useState<string | null>(null);
  const [manualPersonId, setManualPersonId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedNames = useMemo(
    () => persons.filter((person) => selectedIds.includes(person.id)).map((person) => person.name),
    [persons, selectedIds]
  );

  const activeCluster = useMemo(
    () => clusters.find((cluster) => cluster.cluster_key === activeClusterKey) ?? null,
    [activeClusterKey, clusters]
  );

  async function refreshPersons() {
    setPersons(await listPersons());
  }

  async function refreshPhotos(nextOffset = offset, ids = selectedIds) {
    const response = await listPhotos(ids, nextOffset, galleryPageSize);
    setPhotos(response.items);
    setTotal(response.total);
    setOffset(response.offset);
  }

  async function refreshClusters() {
    const nextClusters = await listClusters();
    setClusters(nextClusters);
    if (nextClusters.length === 0) {
      setActiveClusterKey(null);
      setClusterName("");
      return;
    }
    if (!nextClusters.some((cluster) => cluster.cluster_key === activeClusterKey)) {
      setActiveClusterKey(nextClusters[0].cluster_key);
      setClusterName("");
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        await refreshPersons();
        await refreshPhotos(0, []);
        await refreshClusters();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "加载应用数据失败。");
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
        setError(cause instanceof Error ? cause.message : "任务轮询失败。");
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
      await createPerson(personName.trim());
      setPersonName("");
      await refreshPersons();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建人物失败。");
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
      setError(cause instanceof Error ? cause.message : "导入文件失败。");
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
      setError(cause instanceof Error ? cause.message : "加载图库失败。");
    }
  }

  async function openPhoto(photoId: number) {
    setError(null);
    try {
      setSelectedPhoto(await getPhoto(photoId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载图片详情失败。");
    }
  }

  async function handleAssignCluster(personLabel?: string) {
    const targetName = (personLabel ?? clusterName).trim();
    if (!activeCluster || !targetName) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await assignCluster(activeCluster.cluster_key, targetName);
      setClusterName("");
      await refreshClusters();
      await refreshPersons();
      await refreshPhotos(0, selectedIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "归并簇失败。");
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
      setError(cause instanceof Error ? cause.message : "移除标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddTag(photoId: number) {
    if (!manualPersonId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await addPhotoTag(photoId, Number(manualPersonId));
      setSelectedPhoto(detail);
      setManualPersonId("");
      await refreshPhotos(offset, selectedIds);
      await refreshPersons();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加人物标签失败。");
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
      setError(cause instanceof Error ? cause.message : "重新识别失败。");
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
            先建人物库，再批量入库照片。系统会自动匹配已知人物，未识别的人脸单独进入待确认区，不再把建库和入库混在一起。
          </p>
        </div>
        <div className="hero-meta">
          <span>{persons.length} 人物</span>
          <span>{total} 检索结果</span>
          <span>{clusters.length} 待确认簇</span>
        </div>
      </header>

      <section className="workflow-band reveal-one">
        <article className="workflow-card panel">
          <div className="workflow-head">
            <div>
              <p className="eyebrow">Step 1</p>
              <h2>建库</h2>
            </div>
            <span>这里只管理人物名称</span>
          </div>
          <p className="workflow-copy">
            手动创建人物条目，先把你的常用人物名单建立起来。这里不上传照片，不做识别，只负责维护库里的“人”。
          </p>
          <div className="create-row">
            <input
              value={personName}
              onChange={(event) => setPersonName(event.target.value)}
              placeholder="输入人物名字，例如：李雷"
            />
            <button onClick={() => void handleCreatePerson()} disabled={busy || !personName.trim()}>
              创建人物
            </button>
          </div>
          <div className="person-list">
            {persons.map((person) => (
              <button
                key={person.id}
                className={selectedIds.includes(person.id) ? "person-pill active" : "person-pill"}
                onClick={() => {
                  const nextIds = selectedIds.includes(person.id)
                    ? selectedIds.filter((id) => id !== person.id)
                    : [...selectedIds, person.id];
                  void handleSelectTags(nextIds);
                }}
              >
                <span>{person.name}</span>
                <small>{person.photo_count} 张</small>
              </button>
            ))}
            {persons.length === 0 && <p className="muted">人物库还是空的，先创建几个名字。</p>}
          </div>
        </article>

        <article className="workflow-card panel import-card">
          <div className="workflow-head">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2>入库</h2>
            </div>
            <span>上传照片，系统自动识别</span>
          </div>
          <p className="workflow-copy">
            这里专门做照片入库。上传后原图写入 MinIO，后端自动识别已知人物；无法确认的脸会进入右侧待确认工作台。
          </p>
          <label className="file-drop import-drop">
            <input type="file" multiple accept="image/*" onChange={(event) => void handleImport(event.target.files)} />
            <strong>拖入照片或点击选择</strong>
            <span>支持批量导入，识别任务会在后台异步运行。</span>
          </label>
          <div className="task-strip">
            <div>
              <strong>任务状态</strong>
              <p>{task ? task.message ?? task.status : "还没有进行中的导入任务。"}</p>
            </div>
            <div className="task-meter">
              <span style={{ width: `${Math.round((task?.progress ?? 0) * 100)}%` }} />
            </div>
          </div>
        </article>
      </section>

      <main className="layout-grid">
        <section className="gallery-stage reveal-two">
          <div className="stage-topbar panel">
            <div>
              <p className="eyebrow">Gallery</p>
              <h2>按人物浏览</h2>
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
            {persons.length === 0 && <p className="muted">建库后，这里会显示可筛选的人物标签。</p>}
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

        <aside className="right-rail reveal-three">
          <section className="panel cluster-workbench">
            <div className="section-head">
              <p>待确认工作台</p>
              <span>只处理未识别的人脸</span>
            </div>
            <div className="cluster-list cluster-list-inline">
              {clusters.map((cluster) => (
                <button
                  key={cluster.cluster_key}
                  className={cluster.cluster_key === activeClusterKey ? "cluster-card active" : "cluster-card"}
                  onClick={() => {
                    setActiveClusterKey(cluster.cluster_key);
                    setClusterName("");
                  }}
                >
                  <img src={`${cluster.sample.thumbnail_url}?width=240`} alt={cluster.cluster_key} />
                  <div>
                    <strong>{cluster.cluster_key}</strong>
                    <span>{cluster.count} 张待确认人脸</span>
                  </div>
                </button>
              ))}
              {clusters.length === 0 && <p className="muted">当前没有待确认簇，自动识别结果已经比较干净。</p>}
            </div>
            {activeCluster && (
              <div className="cluster-editor">
                <p className="cluster-editor-title">将 {activeCluster.cluster_key} 归并到人物</p>
                <div className="create-row cluster-editor-row">
                  <input
                    value={clusterName}
                    onChange={(event) => setClusterName(event.target.value)}
                    placeholder="输入人物名后归并"
                  />
                  <button onClick={() => void handleAssignCluster()} disabled={busy || !clusterName.trim()}>
                    归并并入库
                  </button>
                </div>
                <div className="quick-assign-row">
                  {persons.slice(0, 8).map((person) => (
                    <button key={person.id} className="quick-assign-chip" onClick={() => void handleAssignCluster(person.name)}>
                      归到 {person.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="panel viewer-panel">
            <div className="section-head">
              <p>原图查看器</p>
              <span>点击图库图片查看</span>
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
                <div className="manual-tag-panel">
                  <p>手动修正人物</p>
                  <div className="manual-tag-row">
                    <select value={manualPersonId} onChange={(event) => setManualPersonId(event.target.value)}>
                      <option value="">选择人物后添加到当前照片</option>
                      {persons
                        .filter((person) => !selectedPhoto.tags.some((tag) => tag.person_id === person.id))
                        .map((person) => (
                          <option key={person.id} value={person.id}>
                            {person.name}
                          </option>
                        ))}
                    </select>
                    <button onClick={() => void handleAddTag(selectedPhoto.id)} disabled={busy || !manualPersonId}>
                      添加人物
                    </button>
                  </div>
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
                <p>查看细节时，这里保持原图视角。</p>
                <span>左边筛选和入库，右边专注查看、修正和处理待确认簇。</span>
              </div>
            )}

            {error && <div className="error-box">{error}</div>}
          </section>
        </aside>
      </main>
    </div>
  );
}
