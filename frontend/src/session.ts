// До появления авторизации текущий пользователь хранится в localStorage.
const KEY = "alpha.userId";

export function currentUserId(): number | null {
  try {
    const v = Number(localStorage.getItem(KEY));
    return v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function setCurrentUserId(id: number | null) {
  try {
    if (id) localStorage.setItem(KEY, String(id));
    else localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
