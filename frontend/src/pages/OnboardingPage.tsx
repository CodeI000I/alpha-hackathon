import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import RolePicker from "../components/RolePicker";
import { setCurrentUserId } from "../session";

export default function OnboardingPage() {
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const [form, setForm] = useState({ fullName: "", email: "", companyName: "", inn: "" });
  const [selected, setSelected] = useState<string[]>([]);

  const submit = useMutation({
    mutationFn: async () => {
      const company = await api.createCompany({ name: form.companyName, inn: form.inn });
      return api.createUser({ fullName: form.fullName, email: form.email, companyId: company.id, roles: selected });
    },
    onSuccess: (user) => {
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
        submit.mutate();
      }}
    >
      <h1>Знакомство</h1>
      {field("fullName", "ФИО")}
      {field("email", "Email")}
      {field("companyName", "Компания")}
      {field("inn", "ИНН компании")}
      <h2>Ваши роли</h2>
      {roles.data && <RolePicker roles={roles.data} selected={selected} onChange={setSelected} />}
      {submit.error && <p className="error">{submit.error.message}</p>}
      <button type="submit" disabled={submit.isPending || selected.length === 0}>
        Продолжить
      </button>
    </form>
  );
}
