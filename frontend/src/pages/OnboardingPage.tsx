import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, isDemoMode } from "../api/client";
import RolePicker from "../components/RolePicker";
import { Button } from "../signal/components/ui";
import { AuthInput, AuthShell } from "../auth/AuthShell";
import { clearOnboardingDraft, clearOnboardingRequestKey, emptyOnboardingForm, getOnboardingRequestKey, readOnboardingDraft, saveOnboardingDraft, validateRegistrationIdentity, type OnboardingForm } from "../auth/onboardingDraft";
import { setCurrentUserId } from "../session";
import type { OnboardingRequest, User } from "../api/types";

type FormState = OnboardingForm;
type FormErrors = Partial<Record<keyof FormState | "roles" | "password", string>>;
interface OnboardingService { onboard(body: OnboardingRequest, idempotencyKey: string): Promise<{ user: User }> }
export function validateOnboarding(form: FormState, selected: string[], password: string): FormErrors {
  const errors: FormErrors = validateRegistrationIdentity(form);
  if (!form.companyName.trim()) errors.companyName = "Укажите название компании.";
  else if (form.companyName.trim().length > 160) errors.companyName = "Не больше 160 символов.";
  if (!/^\d{10}(\d{2})?$/.test(form.inn.trim())) errors.inn = "ИНН должен содержать 10 или 12 цифр.";
  if (password.length < 10) errors.password = "Пароль должен содержать не менее 10 символов.";
  if (selected.length === 0) errors.roles = "Выберите хотя бы одну роль.";
  return errors;
}
export async function createOnboardingProfile(form: FormState, selectedRoles: string[], password: string, idempotencyKey: string, service: OnboardingService = api): Promise<User> {
  const body: OnboardingRequest = {
    company: { name: form.companyName.trim(), inn: form.inn.trim() },
    user: { fullName: form.fullName.trim(), email: form.email.trim(), roles: [...new Set(selectedRoles)].sort(), password },
  };
  return (await service.onboard(body, idempotencyKey)).user;
}
export default function OnboardingPage({ onComplete }: { onComplete: (userId: number) => void }) {
  const [draft] = useState(readOnboardingDraft);
  const [step, setStep] = useState<1 | 2>(draft?.step ?? 1);
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles, enabled: step === 2 });
  const [form, setForm] = useState<FormState>(draft?.form ?? emptyOnboardingForm);
  const [selected, setSelected] = useState<string[]>(draft?.selectedRoles ?? []);
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [announcement, setAnnouncement] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => { saveOnboardingDraft({ form, selectedRoles: selected, step }); }, [form, selected, step]);
  useEffect(() => {
    if (!roles.data) return;
    const validRoles = new Set(roles.data.map((role) => role.code));
    setSelected((current) => current.every((code) => validRoles.has(code)) ? current : current.filter((code) => validRoles.has(code)));
  }, [roles.data]);
  const submit = useMutation({ mutationFn: (idempotencyKey: string) => createOnboardingProfile(form, selected, password, idempotencyKey), onSuccess: (user) => { clearOnboardingDraft(); clearOnboardingRequestKey(); setPassword(""); if (isDemoMode) setCurrentUserId(user.id); onComplete(user.id); } });
  const validate = (): FormErrors => step === 1 ? validateRegistrationIdentity(form) : validateOnboarding(form, selected, password);
  const update = (key: keyof FormState, value: string) => { clearOnboardingRequestKey(); setForm((current) => ({ ...current, [key]: value })); setErrors((current) => ({ ...current, [key]: undefined })); setAnnouncement(""); };
  const blur = (key: keyof FormState) => setErrors((current) => ({ ...current, [key]: validate()[key] }));
  const changeStep = (next: 1 | 2) => { setErrors({}); setAnnouncement(""); setStep(next); requestAnimationFrame(() => { document.getElementById("registration-heading")?.focus(); }); };
  return <AuthShell mode="register">
    <p className="auth-progress">Шаг {step} из 2 · {step === 1 ? "Данные пользователя" : "Компания и роли"}</p>
    <h1 id="registration-heading" tabIndex={-1}>{step === 1 ? "Создать аккаунт" : "Настройте профиль"}</h1>
    <form className="w-form" noValidate ref={formRef} onSubmit={(event) => {
      event.preventDefault(); const next = validate(); setErrors(next);
      const first = (["fullName", "email", "companyName", "inn", "password", "roles"] as const).find((key) => next[key]);
      if (first) { setAnnouncement(next[first] || "Проверьте поля формы."); if (step === 2 && (first === "fullName" || first === "email")) { changeStep(1); setErrors(next); } if (first === "roles") formRef.current?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.focus(); else requestAnimationFrame(() => (formRef.current?.elements.namedItem(first) as HTMLElement | null)?.focus()); return; }
      if (step === 1) { changeStep(2); return; }
      if (!roles.data?.length || roles.isError || roles.isLoading) return;
      submit.mutate(getOnboardingRequestKey());
    }}>
      {step === 1 ? <>
        <AuthInput id="full-name" name="fullName" label="Как вас зовут" value={form.fullName} onChange={(event) => update("fullName", event.target.value)} onBlur={() => blur("fullName")} autoComplete="name" maxLength={120} error={errors.fullName} required />
        <AuthInput id="email" name="email" label="Электронная почта" value={form.email} onChange={(event) => update("email", event.target.value)} onBlur={() => blur("email")} type="email" autoComplete="email" autoCapitalize="none" spellCheck={false} error={errors.email} required maxLength={320} />
        <Button type="submit">Продолжить</Button>
      </> : <>
      <p className="auth-identity">{form.fullName} <span>{form.email}</span></p>
      <AuthInput id="company-name" name="companyName" label="Название компании" value={form.companyName} onChange={(event) => update("companyName", event.target.value)} onBlur={() => blur("companyName")} maxLength={160} error={errors.companyName} required disabled={submit.isPending} /><AuthInput id="inn" name="inn" label="ИНН компании" value={form.inn} onChange={(event) => update("inn", event.target.value.replace(/\D/g, "").slice(0, 12))} onBlur={() => blur("inn")} inputMode="numeric" autoComplete="off" error={errors.inn} required disabled={submit.isPending} />
      <AuthInput id="registration-password" name="password" label="Пароль · не менее 10 символов" type="password" autoComplete="new-password" value={password} onChange={(event) => { if (submit.isError) clearOnboardingRequestKey(); setPassword(event.target.value); setErrors((current) => ({ ...current, password: undefined })); }} onBlur={() => setErrors((current) => ({ ...current, password: validateOnboarding(form, selected, password).password }))} maxLength={128} error={errors.password} required disabled={submit.isPending} />
      <fieldset className="auth-roles" disabled={roles.isLoading || submit.isPending} aria-describedby={errors.roles ? "auth-roles-error" : undefined}><legend>Ваши роли в компании</legend><p>Можно выбрать несколько.</p>{roles.isLoading && <p role="status">Загружаем роли…</p>}{roles.data && <RolePicker roles={roles.data} selected={selected} onChange={(value) => { clearOnboardingRequestKey(); setSelected(value); setErrors((current) => ({ ...current, roles: undefined })); }} />}{errors.roles && <span className="auth-field-message is-error" id="auth-roles-error" role="alert">{errors.roles}</span>}</fieldset>
      {roles.isError && <div className="auth-problem" role="alert"><strong>Не удалось загрузить роли</strong>{roles.error.message}<Button type="button" variant="secondary" onClick={() => roles.refetch()}>Повторить</Button></div>}
      {!roles.isLoading && !roles.isError && !roles.data?.length && <p className="auth-problem" role="status">В каталоге пока нет ролей. Регистрация станет доступна после заполнения каталога.</p>}
      {submit.error && <div className="auth-problem" role="alert"><strong>Не удалось создать профиль</strong>{submit.error.message}</div>}
      <Button type="submit" disabled={submit.isPending || roles.isLoading || roles.isError || !roles.data?.length}>{submit.isPending ? "Создаём профиль…" : "Завершить настройку"}</Button>
      <Button type="button" variant="secondary" disabled={submit.isPending} onClick={() => changeStep(1)}>Назад к данным пользователя</Button>
      </>}
    </form><div className="auth-announcement" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
  </AuthShell>;
}
