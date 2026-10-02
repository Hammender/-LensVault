import { useEffect, useMemo, useState } from "react";
import { FileArchive, KeyRound, PlugZap, RotateCcw, ShieldCheck } from "lucide-react";
import {
  changePlugin, deletePluginCredential, getPluginGuide, listPluginCredentials, listPlugins,
  savePluginCredential, testPluginCredential, uploadPlugin,
  uninstallPlugin,
  type AcquisitionPluginCredential, type AcquisitionPluginVersion
} from "../api/acquisitionPlugins";
import { useConfirm } from "./ConfirmDialog";

type Props = {
  canAdmin: boolean;
  canManageAccounts: boolean;
  onChanged: () => void;
  refreshRef?: { current: (() => Promise<void>) | null };
};

const stateLabel: Record<string, string> = {
  uploaded: "待准备", preparing: "准备中", ready: "可启用", active: "已启用", failed: "准备失败"
};

export default function AcquisitionPluginsPanel({ canAdmin, canManageAccounts, onChanged, refreshRef }: Props) {
  const confirm = useConfirm();
  const [versions, setVersions] = useState<AcquisitionPluginVersion[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [guide, setGuide] = useState("");
  const [accounts, setAccounts] = useState<AcquisitionPluginCredential[]>([]);
  const [accountName, setAccountName] = useState("默认账号");
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const active = useMemo(() => versions.find((item) => item.key === selectedKey && item.status === "active"), [versions, selectedKey]);

  async function refresh() {
    const result = await listPlugins();
    setVersions(result);
    setSelectedKey((current) => current || result.find((item) => item.status === "active")?.key || result[0]?.key || "");
  }
  if (refreshRef) refreshRef.current = refresh;

  useEffect(() => { void refresh().catch((error) => setNotice(String(error))); }, []);
  useEffect(() => {
    setValues({});
    setAccountName("默认账号");
    if (!active) { setGuide(""); setAccounts([]); return; }
    void Promise.all([getPluginGuide(active.key), listPluginCredentials(active.key)])
      .then(([text, saved]) => { setGuide(text); setAccounts(saved); })
      .catch((error) => setNotice(String(error)));
  }, [active?.key, active?.version]);

  async function perform(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setNotice("");
    try {
      await action();
      await refresh();
      onChanged();
      setNotice(success);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return <section className="plugin-workbench">
    <div className="acquisition-section plugin-package-panel">
      <div className="acquisition-section-title"><span>插件包</span><PlugZap size={18} /></div>
      <p className="source-notes">采集插件用于不用登录、按页直接下载图片或视频的网站。管理员上传并启用后，再绑定到站点。Telegram 频道使用采集中心原有的账号登录流程。</p>
      {canAdmin && <div className="plugin-upload-row">
        <label className="plugin-file-label"><FileArchive size={17} /> 选择 ZIP 插件包<input type="file" accept=".zip,application/zip" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        <button type="button" disabled={!file || busy} onClick={() => void perform(async () => { if (file) await uploadPlugin(file); setFile(null); }, "插件已上传，请准备环境")}>上传插件</button>
        {file && <small>{file.name}</small>}
      </div>}
      {notice && <p className="acquisition-notice" role="status">{notice}</p>}
      <div className="plugin-version-list">
        {versions.map((item) => <article className={`plugin-version ${selectedKey === item.key ? "selected" : ""}`} key={`${item.key}@${item.version}`}>
          <button type="button" className="plugin-select" onClick={() => setSelectedKey(item.key)}>
            <strong>{item.name}</strong><small>{item.key} · v{item.version}</small>
          </button>
          <span className={`plugin-state ${item.status}`}>{stateLabel[item.status]}</span>
          <p>{item.description}</p>
          {item.last_error && item.status === "failed" && <small className="telegram-topic-error">{item.last_error}</small>}
          {item.requirements.length > 0 && <small>依赖：{item.requirements.join("、")}</small>}
          {canAdmin && <div className="plugin-actions">
            {(item.status === "uploaded" || item.status === "failed" || item.status === "preparing") && <button type="button" disabled={busy} onClick={() => void perform(() => changePlugin(item.key, item.version, "prepare"), "环境准备已排队，请稍后刷新状态")}>{item.status === "preparing" ? "重新准备" : "准备环境"}</button>}
            {item.status === "ready" && <button type="button" disabled={busy} onClick={() => void perform(() => changePlugin(item.key, item.version, "activate"), "插件已启用")}>启用版本</button>}
            {item.status === "active" && <button type="button" className="secondary-command" disabled={busy} onClick={() => void perform(() => changePlugin(item.key, item.version, "disable"), "插件已停用")}>停用</button>}
            {item.status !== "active" && <button type="button" className="secondary-command" disabled={busy} onClick={() => void (async () => {
              if (!await confirm({ title: `卸载 ${item.name} v${item.version}？`, message: "移除该版本的代码和独立环境；采集历史与审核结果保留。", confirmLabel: "确认卸载", tone: "danger" })) return;
              await perform(() => uninstallPlugin(item.key, item.version), "插件版本已卸载");
            })()}>卸载版本</button>}
          </div>}
        </article>)}
        {!versions.length && <p className="acquisition-empty">尚未安装采集插件。</p>}
      </div>
      <button type="button" className="secondary-command" disabled={busy} onClick={() => void refresh()}><RotateCcw size={15} /> 刷新插件状态</button>
    </div>

    <div className="acquisition-section plugin-account-panel">
      <div className="acquisition-section-title"><span>连接账号</span><KeyRound size={18} /></div>
      {!active && <p className="acquisition-empty">选择一个已启用的插件后配置账号。</p>}
      {active && <>
        <h2>{active.name}</h2>
        {active.credentials.length > 0 && <p className="source-notes">先按插件说明填写配置，再保存并测试连接。系统不会显示已保存内容的原文。</p>}
        <pre className="plugin-guide">{guide}</pre>
        {active.credentials.length === 0 && <p className="plugin-no-auth"><ShieldCheck size={17} /> 此插件无需填写登录凭据。</p>}
        {canManageAccounts && active.credentials.length > 0 && <div className="plugin-account-form">
          <label>账号名称<input value={accountName} maxLength={128} onChange={(event) => setAccountName(event.target.value)} /></label>
          {active.credentials.map((field) => <label key={field.key}>{field.label}{field.required ? " *" : ""}
            <input type={field.secret === false ? "text" : "password"} value={values[field.key] ?? ""}
              placeholder={field.description || undefined}
              onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))} />
          </label>)}
          <button type="button" disabled={busy || !accountName.trim()} onClick={() => void perform(async () => {
            await savePluginCredential(active.key, accountName, values);
            setValues({});
            setAccounts(await listPluginCredentials(active.key));
          }, "账号配置已保存，请测试连接")}>保存账号配置</button>
        </div>}
        {accounts.length > 0 && <div className="plugin-account-list">
          <h3>已保存账号</h3>
          {accounts.map((account) => <div className="plugin-account-line" key={account.id}>
            <div><strong>{account.name}</strong><small>{account.status === "valid" ? "连接正常" : account.status === "invalid" ? "连接失败，请更新凭据" : "尚未测试"}</small></div>
            {canManageAccounts && <button type="button" className="secondary-command" disabled={busy} onClick={() => { setAccountName(account.name); setValues({}); }}>更新</button>}
            {canManageAccounts && <button type="button" className="secondary-command" disabled={busy} onClick={() => void perform(async () => {
              const result = await testPluginCredential(account.id);
              setAccounts(await listPluginCredentials(active.key));
              if (result.status !== "valid") throw new Error(result.reason || "连接失败，请检查插件说明并更新凭据");
            }, "连接测试完成")}>测试连接</button>}
            {canManageAccounts && <button type="button" className="secondary-command" disabled={busy} onClick={() => void (async () => {
              if (!await confirm({ title: `删除账号配置“${account.name}”？`, message: "将删除保存的登录凭据；已完成的采集记录保留。", confirmLabel: "确认删除", tone: "danger" })) return;
              await perform(async () => { await deletePluginCredential(account.id); setAccounts(await listPluginCredentials(active.key)); }, "账号配置已删除");
            })()}>删除</button>}
          </div>)}
        </div>}
      </>}
    </div>
  </section>;
}
