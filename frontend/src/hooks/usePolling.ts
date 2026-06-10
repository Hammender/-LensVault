import { useEffect, useRef } from "react";

export function usePolling(callback: () => void | Promise<void>, interval: number, enabled: boolean, immediate = false) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const tick = async () => {
      try {
        await savedCallback.current();
      } catch (err) {
        console.error("Polling error:", err);
      }
    };

    if (immediate) {
      tick();
    }

    const id = setInterval(tick, interval);
    return () => clearInterval(id);
  }, [interval, enabled, immediate]);
}
