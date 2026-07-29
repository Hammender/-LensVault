import { useState } from "react";

type AuthScreenProps = {
  bootstrapRequired: boolean;
  busy: boolean;
  error: string | null;
  onBootstrap: (payload: { username: string; password: string; display_name?: string | null; workspace_name?: string | null }) => Promise<void>;
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (payload: { username: string; password: string; display_name?: string | null }) => Promise<void>;
};

export default function AuthScreen({ bootstrapRequired, busy, error, onBootstrap, onLogin, onRegister }: AuthScreenProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("我的内容空间");
  const [password, setPassword] = useState("");
  const isRegisterMode = !bootstrapRequired && mode === "register";
  const passwordMinLength = bootstrapRequired || isRegisterMode ? 8 : 1;

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <p className="eyebrow">PictureShow</p>
        <h1>{bootstrapRequired ? "初始化管理员" : isRegisterMode ? "注册账号" : "登录"}</h1>
        <p className="lead">
          {bootstrapRequired
            ? "首次使用需要创建管理员和默认内容空间。"
            : isRegisterMode
              ? "新账号会自动创建只能自己使用的私人内容空间。"
              : "登录后只会看到当前账号所属内容空间的数据。"}
        </p>
        {!bootstrapRequired && (
          <div className="auth-mode-tabs" role="tablist" aria-label="认证方式">
            <button className={mode === "login" ? "active" : ""} type="button" onClick={() => setMode("login")}>登录</button>
            <button className={mode === "register" ? "active" : ""} type="button" onClick={() => setMode("register")}>注册</button>
          </div>
        )}
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (bootstrapRequired) {
              void onBootstrap({ username, password, display_name: displayName || null, workspace_name: workspaceName || null });
              return;
            }
            if (isRegisterMode) {
              void onRegister({ username, password, display_name: displayName || null });
              return;
            }
            void onLogin(username, password);
          }}
        >
          <label>账号<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
          {(bootstrapRequired || isRegisterMode) && <label>显示名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" /></label>}
          {bootstrapRequired && <label>内容空间<input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} required /></label>}
          <label>
            密码
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={bootstrapRequired || isRegisterMode ? "new-password" : "current-password"} minLength={passwordMinLength} required />
          </label>
          <button className="primary" type="submit" disabled={busy || !username.trim() || password.length < passwordMinLength}>
            {busy ? "处理中..." : bootstrapRequired ? "创建并进入" : isRegisterMode ? "注册并进入" : "进入"}
          </button>
        </form>
        {error && <div className="error-banner">{error}</div>}
      </section>
    </main>
  );
}
