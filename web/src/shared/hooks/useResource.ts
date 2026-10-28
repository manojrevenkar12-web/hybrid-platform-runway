import { useCallback, useEffect, useRef, useState } from "react";
import { timing } from "../../theme/tokens";

export type Resource<T> =
  | { state: "loading" }
  | { state: "error"; error: Error; retry: () => void }
  | { state: "ready"; data: T; refresh: () => void };

/**
 * Load something from the core and keep it fresh. A failed refresh keeps the last good data on
 * screen; only a failed first load shows the error state.
 */
export function useResource<T>(load: () => Promise<T>, deps: unknown[], pollMs: number | null = timing.pollMs): Resource<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setData(undefined);
    setError(null);
  }, deps);

  useEffect(() => {
    let live = true;
    loadRef
      .current()
      .then((d) => {
        if (!live) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e : new Error(String(e)));
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (pollMs === null) return;
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [pollMs, refresh]);

  if (data !== undefined) return { state: "ready", data, refresh };
  if (error) return { state: "error", error, retry: refresh };
  return { state: "loading" };
}
