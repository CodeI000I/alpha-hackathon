import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";

const LOCAL_STATE_EVENT = "alpha-insights:local-state";

export function localKey(userId: number, name: string) {
  return `alpha.insights.${userId}.${name}`;
}

export function useStoredState<T>(key: string, initial: T) {
  const source = useRef({});
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = localStorage.getItem(key);
      return saved === null ? initial : (JSON.parse(saved) as T);
    } catch {
      return initial;
    }
  });
  const valueRef = useRef(value);

  useEffect(() => {
    const sync = (event: Event) => {
      const detail = (event as CustomEvent<{ key: string; value: T; source: object }>).detail;
      if (detail?.key === key && detail.source !== source.current) {
        valueRef.current = detail.value;
        setValue(detail.value);
      }
    };
    window.addEventListener(LOCAL_STATE_EVENT, sync);
    return () => window.removeEventListener(LOCAL_STATE_EVENT, sync);
  }, [key]);

  const update = useCallback((action: SetStateAction<T>) => {
    const next = typeof action === "function" ? (action as (value: T) => T)(valueRef.current) : action;
    valueRef.current = next;
    setValue(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      // Private browsing or storage limits must not make the interface unusable.
    }
    window.dispatchEvent(new CustomEvent(LOCAL_STATE_EVENT, { detail: { key, value: next, source: source.current } }));
  }, [key]);

  return [value, update] as const;
}
