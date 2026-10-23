import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import RolePicker from "../components/RolePicker";
import { setCurrentUserId } from "../session";
import type { OnboardingRequest } from "../api/types";

const REQUEST_KEY = "alpha.onboardingRequest";

async function requestFingerprint(body: OnboardingRequest) {
  const bytes = new TextEncoder().encode(JSON.stringify(body));
  if (!crypto.subtle) return null;
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export default function OnboardingPage() {
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const [form, setForm] = useState({ fullName: "", email: "", companyName: "", inn: "" });
  const [selected, setSelected] = useState<string[]>([]);
  const requestKey = useRef<{ fingerprint: string; key: string } | null>(null);

  const idempotencyKey = async (body: OnboardingRequest) => {
    const fingerprint = await requestFingerprint(body);
    const cacheFingerprint = fingerprint ?? JSON.stringify(body);
    if (requestKey.current?.fingerprint === cacheFingerprint) return requestKey.current.key;
    let key = uuid();
    if (fingerprint) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(REQUEST_KEY) ?? "null");
        if (saved?.fingerprint === fingerprint && typeof saved.key === "string"
            && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(saved.key)) {
          key = saved.key;
        } else sessionStorage.setItem(REQUEST_KEY, JSON.stringify({ fingerprint, key }));
      } catch {
        // Keep retries in this page stable when browser storage is unavailable.
      }
    }
    requestKey.current = { fingerprint: cacheFingerprint, key };
    return key;
  };

  const submit = useMutation({
    mutationFn: async (body: OnboardingRequest) => api.onboard(body, await idempotencyKey(body)),
    onSuccess: ({ user }) => {
      requestKey.current = null;
      try { sessionStorage.removeItem(REQUEST_KEY); } catch { /* best effort */ }
      setCurrentUserId(user.id);
      window.location.assign("/feed");
    },
  });

  const field = (key: keyof typeof form, label: string) => (
    <label className="field">
      {label}
      <input value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} required />
    </label>
  );

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate({
          company: { name: form.companyName.trim(), inn: form.inn.trim() },
          user: {
            fullName: form.fullName.trim(), email: form.email.trim(), roles: [...new Set(selected)].sort(),
          },
        });
      }}
    >
      <h1>Знакомство</h1>
      {field("fullName", "ФИО")}
      {field("email", "Email")}
      {field("companyName", "Компания")}
      {field("inn", "ИНН компании")}
      <h2>Ваши роли</h2>
      {roles.isLoading && <p role="status">Загрузка ролей…</p>}
      {roles.isError && (
        <p className="error" role="alert">
          Не удалось загрузить роли: {roles.error instanceof Error ? roles.error.message : "Неизвестная ошибка."}{" "}
          <button type="button" onClick={() => roles.refetch()}>Повторить</button>
        </p>
      )}
      {roles.data && <RolePicker roles={roles.data} selected={selected} onChange={setSelected} />}
      {submit.error && <p className="error">{submit.error.message}</p>}
      <button type="submit" disabled={submit.isPending || selected.length === 0}>
        Продолжить
      </button>
    </form>
  );
}
