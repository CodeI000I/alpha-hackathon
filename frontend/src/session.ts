// До появления серверной авторизации идентификаторы хранятся только в браузере.
const USER_KEY = "alpha.userId";
const PENDING_COMPANY_KEY = "alpha.pendingCompanyId";

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

export function currentUserId(): number | null {
  return readPositiveId(USER_KEY);
}

export function setCurrentUserId(id: number | null): void {
  writePositiveId(USER_KEY, id);
}

export function clearCurrentUserId(): void {
  writePositiveId(USER_KEY, null);
}

export function pendingCompanyId(): number | null {
  return readPositiveId(PENDING_COMPANY_KEY);
}

export function setPendingCompanyId(id: number | null): void {
  writePositiveId(PENDING_COMPANY_KEY, id);
}

export function clearPendingCompanyId(): void {
  writePositiveId(PENDING_COMPANY_KEY, null);
}
