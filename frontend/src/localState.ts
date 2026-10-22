import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";
import { dataMode } from "./api/client";

const LOCAL_STATE_EVENT = "alpha-insights:local-state";
const memoryState = new Map<string, unknown>();

interface LocalStateDetail<T> {
  key: string;
  value: T;
  source: object;
}

function readStored<T>(key: string, fallback: T): T {
  let saved: string | null;
  try {
    saved = localStorage.getItem(key);
  } catch {
    return memoryState.has(key) ? (memoryState.get(key) as T) : fallback;
  }
  if (saved === null) {
    memoryState.delete(key);
    return fallback;
  }
  try {
    const parsed = JSON.parse(saved) as T;
    memoryState.set(key, parsed);
    return parsed;
  } catch {
    memoryState.delete(key);
    return fallback;
  }
}

function writeStored<T>(key: string, value: T): void {
  memoryState.set(key, value);
  try {
    const serialized = JSON.stringify(value);
    if (serialized === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, serialized);
  } catch {
    // In-memory копия и локальное событие сохраняют синхронизацию в текущей вкладке.
  }
}

export function localKey(userId: number, name: string, companyId?: number | null): string {
  return `alpha.insights.v2.${dataMode}.company.${companyId ?? "none"}.user.${userId}.${name}`;
}

export function useStoredState<T>(key: string, initial: T): readonly [T, (action: SetStateAction<T>) => void] {
  const source = useRef({});
  const initialRef = useRef(initial);
  initialRef.current = initial;
  const [value, setValue] = useState<T>(() => readStored(key, initial));
  const valueRef = useRef(value);

  useEffect(() => {
    const next = readStored(key, initialRef.current);
    valueRef.current = next;
    setValue(next);

    const sync = (event: Event) => {
      const detail = (event as CustomEvent<LocalStateDetail<T>>).detail;
      if (detail?.key === key && detail.source !== source.current) {
        memoryState.set(key, detail.value);
        valueRef.current = detail.value;
        setValue(detail.value);
      }
    };

    const syncStorage = (event: StorageEvent) => {
      if (event.key !== key) return;
      let nextValue = initialRef.current;
      if (event.newValue !== null) {
        try {
          nextValue = JSON.parse(event.newValue) as T;
        } catch {
          return;
        }
      }
      memoryState.set(key, nextValue);
      valueRef.current = nextValue;
      setValue(nextValue);
    };

    window.addEventListener(LOCAL_STATE_EVENT, sync);
    window.addEventListener("storage", syncStorage);
    return () => {
      window.removeEventListener(LOCAL_STATE_EVENT, sync);
      window.removeEventListener("storage", syncStorage);
    };
  }, [key]);

  const update = useCallback(
    (action: SetStateAction<T>) => {
      const next = typeof action === "function" ? (action as (value: T) => T)(valueRef.current) : action;
      valueRef.current = next;
      setValue(next);
      writeStored(key, next);
      const detail: LocalStateDetail<T> = { key, value: next, source: source.current };
      window.dispatchEvent(new CustomEvent(LOCAL_STATE_EVENT, { detail }));
    },
    [key],
  );

  return [value, update] as const;
}
