import { createContext, useContext } from "react";

// ProgressiveContext: a flexible context for passing all App state
// Page components destructure what they need from useAppContext()
export const AppContext = createContext<Record<string, any> | null>(null);

export function useAppContext() {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useAppContext must be used inside <AppContext.Provider>");
  }
  return ctx;
}
