import { AlertTriangle, CircleHelp } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ConfirmDialogTone = "danger" | "primary";

export type ConfirmDialogOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  tone?: ConfirmDialogTone;
};

type PendingConfirmation = {
  options: Required<Pick<ConfirmDialogOptions, "confirmLabel" | "tone">> & ConfirmDialogOptions;
  resolve: (confirmed: boolean) => void;
};

type ConfirmContextValue = {
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>;
};

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const pendingRef = useRef<PendingConfirmation | null>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  const settle = useCallback((confirmed: boolean) => {
    const current = pendingRef.current;
    if (!current) return;
    pendingRef.current = null;
    setPending(null);
    current.resolve(confirmed);
  }, []);

  const confirm = useCallback((options: ConfirmDialogOptions) => {
    if (pendingRef.current) return Promise.resolve(false);
    return new Promise<boolean>((resolve) => {
      const next: PendingConfirmation = {
        options: {
          ...options,
          confirmLabel: options.confirmLabel ?? "确认",
          tone: options.tone ?? "primary"
        },
        resolve
      };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  useEffect(() => {
    if (!pending) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        settle(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    window.setTimeout(() => cancelButtonRef.current?.focus(), 0);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [pending, settle]);

  useEffect(() => () => settle(false), [settle]);

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      {pending && (
        <div
          className="confirm-dialog-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) settle(false);
          }}
        >
          <section
            className={`confirm-dialog confirm-dialog--${pending.options.tone}`}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-dialog-title"
            aria-describedby="confirm-dialog-message"
          >
            <div className="confirm-dialog-icon" aria-hidden="true">
              {pending.options.tone === "danger" ? <AlertTriangle size={24} /> : <CircleHelp size={24} />}
            </div>
            <div className="confirm-dialog-copy">
              <p className="eyebrow">操作确认</p>
              <h2 id="confirm-dialog-title">{pending.options.title}</h2>
              <p id="confirm-dialog-message">{pending.options.message}</p>
            </div>
            <div className="confirm-dialog-actions">
              <button ref={cancelButtonRef} type="button" className="ghost-button" onClick={() => settle(false)}>
                取消
              </button>
              <button
                type="button"
                className={pending.options.tone === "danger" ? "danger-button" : "primary"}
                onClick={() => settle(true)}
              >
                {pending.options.confirmLabel}
              </button>
            </div>
          </section>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error("useConfirm 必须在 ConfirmDialogProvider 内使用。");
  return context.confirm;
}
