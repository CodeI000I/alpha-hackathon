import { dataMode } from "./api/client";
import type { DataMode } from "./api/types";

// До появления серверной авторизации идентификаторы хранятся только в браузере.
// v2 намеренно не читает старые alpha.userId/alpha.pendingCompanyId: API и демо
// используют разные пространства и не могут случайно восстановить чужую сессию.
const SESSION_NAMESPACE = "signal.session.v2";

function sessionKey(mode: DataMode, name: "userId" | "pendingCompanyId"): string {
  return `${SESSION_NAMESPACE}.${mode}.${name}`;
}

function readPositiveId(key: string): number | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function writePositiveId(key: string, id: number | null): void {
  try {
    if (id !== null && Number.isSafeInteger(id) && id > 0) {
      localStorage.setItem(key, String(id));
    } else {
      localStorage.removeItem(key);
    }
  } catch {
    // Приложение продолжает работать без восстановления сессии.
  }
}

export function currentUserId(mode: DataMode = dataMode): number | null {
  return readPositiveId(sessionKey(mode, "userId"));
}

export function setCurrentUserId(id: number | null, mode: DataMode = dataMode): void {
  writePositiveId(sessionKey(mode, "userId"), id);
}

export function clearCurrentUserId(mode: DataMode = dataMode): void {
  writePositiveId(sessionKey(mode, "userId"), null);
}

export function pendingCompanyId(mode: DataMode = dataMode): number | null {
  return readPositiveId(sessionKey(mode, "pendingCompanyId"));
}

export function setPendingCompanyId(id: number | null, mode: DataMode = dataMode): void {
  writePositiveId(sessionKey(mode, "pendingCompanyId"), id);
}

export function clearPendingCompanyId(mode: DataMode = dataMode): void {
  writePositiveId(sessionKey(mode, "pendingCompanyId"), null);
}
