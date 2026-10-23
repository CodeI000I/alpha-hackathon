// До появления авторизации текущий пользователь хранится в localStorage.
const KEY = "alpha.userId";

export function currentUserId(): number | null {
  try {
    const raw = localStorage.getItem(KEY);
    const value = raw === null ? null : Number(raw);
    if (value !== null && Number.isSafeInteger(value) && value > 0) return value;
    if (raw !== null) localStorage.removeItem(KEY);
    return null;
  } catch {
    return null;
  }
}

export function setCurrentUserId(id: number | null) {
  try {
    if (id !== null && Number.isSafeInteger(id) && id > 0) localStorage.setItem(KEY, String(id));
    else localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
