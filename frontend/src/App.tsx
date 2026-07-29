import { useEffect, useState } from "react";

import { ApplicationContent } from "./ApplicationContent";
import AuthScreen from "./components/AuthScreen";
import {
  bootstrapAdmin,
  clearAuthToken,
  clearSelectedWorkspaceId,
  getBootstrapStatus,
  getCurrentSession,
  login,
  logout,
  registerAccount,
  setAuthToken,
  setSelectedWorkspaceId
} from "./api";
import type { AuthSession } from "./types";

export default function App() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const [bootstrapRequired, setBootstrapRequired] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadAuth() {
      try {
        const session = await getCurrentSession();
        if (!cancelled) {
          setAuthToken(session.access_token);
          setSelectedWorkspaceId(session.workspace.id);
          setAuthSession(session);
          setBootstrapRequired(false);
        }
      } catch {
        clearAuthToken();
        try {
          const status = await getBootstrapStatus();
          if (!cancelled) {
            setBootstrapRequired(status.required);
          }
        } catch (error) {
          if (!cancelled) {
            setAuthError(error instanceof Error ? error.message : "无法连接服务");
          }
        }
      } finally {
        if (!cancelled) {
          setAuthReady(true);
        }
      }
    }
    void loadAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSession = (session: AuthSession) => {
    setAuthToken(session.access_token);
    setSelectedWorkspaceId(session.workspace.id);
    setAuthSession(session);
    setBootstrapRequired(false);
    setAuthError(null);
  };

  const handleBootstrap = async (payload: { username: string; password: string; display_name?: string | null; workspace_name?: string | null }) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      handleSession(await bootstrapAdmin(payload));
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "初始化失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogin = async (username: string, password: string) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      handleSession(await login(username, password));
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "登录失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleRegister = async (payload: { username: string; password: string; display_name?: string | null }) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      handleSession(await registerAccount(payload));
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "注册失败");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = () => {
    void logout().finally(() => {
      clearAuthToken();
      clearSelectedWorkspaceId();
      setAuthSession(null);
      setAuthError(null);
    });
  };

  const handleSessionChange = (session: AuthSession) => {
    setAuthToken(session.access_token);
    setSelectedWorkspaceId(session.workspace.id);
    setAuthSession(session);
  };

  if (!authReady) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <p className="eyebrow">PictureShow</p>
          <h1>加载中</h1>
        </section>
      </main>
    );
  }

  if (!authSession) {
    return (
      <AuthScreen
        bootstrapRequired={bootstrapRequired}
        busy={authBusy}
        error={authError}
        onBootstrap={handleBootstrap}
        onLogin={handleLogin}
        onRegister={handleRegister}
      />
    );
  }

  return (
    <ApplicationContent
      authSession={authSession}
      onLogout={handleLogout}
      onSessionChange={handleSessionChange}
    />
  );
}
