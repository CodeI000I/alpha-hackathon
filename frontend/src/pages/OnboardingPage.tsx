import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError, isDemoMode } from "../api/client";
import RolePicker from "../components/RolePicker";
import { Button } from "../signal/components/ui";
import { AuthInput, AuthShell } from "../auth/AuthShell";
import { clearOnboardingDraft, emptyOnboardingForm, readOnboardingDraft, saveOnboardingDraft, validateRegistrationIdentity, type OnboardingForm } from "../auth/onboardingDraft";
import { clearPendingCompanyId, pendingCompanyId, setCurrentUserId, setPendingCompanyId } from "../session";
import type { Company, CreateCompanyInput, CreateUserInput, User } from "../api/types";

type FormState = OnboardingForm;
type FormErrors = Partial<Record<keyof FormState | "roles", string>>;
interface OnboardingService { createCompany(input: CreateCompanyInput): Promise<Company>; createUser(input: CreateUserInput): Promise<User> }
export function validateOnboarding(form: FormState, selected: string[]): FormErrors {
  const errors: FormErrors = validateRegistrationIdentity(form);
  if (!form.companyName.trim()) errors.companyName = "Укажите название компании.";
  else if (form.companyName.trim().length > 160) errors.companyName = "Не больше 160 символов.";
  if (!/^\d{10}(\d{2})?$/.test(form.inn.trim())) errors.inn = "ИНН должен содержать 10 или 12 цифр.";
  if (selected.length === 0) errors.roles = "Выберите хотя бы одну роль.";
  return errors;
}
export async function createOnboardingProfile(form: FormState, selectedRoles: string[], service: OnboardingService = api): Promise<User> {
  let companyId = pendingCompanyId();
  if (!companyId) { const company = await service.createCompany({ name: form.companyName.trim(), inn: form.inn.trim() }); companyId = company.id; setPendingCompanyId(companyId); }
  const user = await service.createUser({ fullName: form.fullName.trim(), email: form.email.trim(), companyId, roles: selectedRoles });
  clearPendingCompanyId(); return user;
}
export default function OnboardingPage({ onComplete }: { onComplete: (userId: number) => void }) {
  const [draft] = useState(readOnboardingDraft);
  const [step, setStep] = useState<1 | 2>(draft?.step ?? 1);
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles, enabled: step === 2 });
  const [form, setForm] = useState<FormState>(draft?.form ?? emptyOnboardingForm);
  const [selected, setSelected] = useState<string[]>(draft?.selectedRoles ?? []);
  const [errors, setErrors] = useState<FormErrors>({});
  const [resumedCompanyId, setResumedCompanyId] = useState(pendingCompanyId);
  const [announcement, setAnnouncement] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const company = useQuery({ queryKey: ["company", resumedCompanyId], queryFn: () => api.company(resumedCompanyId!), enabled: resumedCompanyId !== null && step === 2 });
  const pendingCompanyUnconfirmed = resumedCompanyId !== null && (!company.data || company.isError);
  useEffect(() => { saveOnboardingDraft({ form, selectedRoles: selected, step }); }, [form, selected, step]);
  useEffect(() => {
    if (!roles.data) return;
    const validRoles = new Set(roles.data.map((role) => role.code));
    setSelected((current) => current.every((code) => validRoles.has(code)) ? current : current.filter((code) => validRoles.has(code)));
  }, [roles.data]);
  const submit = useMutation({ mutationFn: () => createOnboardingProfile(form, selected), onSuccess: (user) => { clearOnboardingDraft(); setCurrentUserId(user.id); onComplete(user.id); }, onSettled: () => setResumedCompanyId(pendingCompanyId()) });
  const validate = (): FormErrors => { const next: FormErrors = step === 1 ? validateRegistrationIdentity(form) : validateOnboarding(form, selected); if (resumedCompanyId) { delete next.companyName; delete next.inn; } return next; };
  const update = (key: keyof FormState, value: string) => { setForm((current) => ({ ...current, [key]: value })); setErrors((current) => ({ ...current, [key]: undefined })); setAnnouncement(""); };
  const blur = (key: keyof FormState) => setErrors((current) => ({ ...current, [key]: validate()[key] }));
  const changeStep = (next: 1 | 2) => { setErrors({}); setAnnouncement(""); setStep(next); requestAnimationFrame(() => { document.getElementById("registration-heading")?.focus(); }); };
  return <AuthShell mode="register">
    <p className="auth-progress">Шаг {step} из 2 · {step === 1 ? "Данные пользователя" : "Компания и роли"}</p>
    <h1 id="registration-heading" tabIndex={-1}>{step === 1 ? "Создать аккаунт" : "Настройте профиль"}</h1>
    <p className="auth-intro">{step === 1 ? "Сначала укажите имя и почту. На следующем шаге нужно добавить компанию и выбрать роли." : "Добавьте компанию и выберите хотя бы одну роль. Аккаунт будет создан только после завершения этого шага."} {isDemoMode ? "Будет создан локальный демопрофиль без пароля." : "Пароль не нужен: серверный вход пока не подключён."}</p>
    {resumedCompanyId && step === 2 && (company.error instanceof ApiError && company.error.status === 404 ? <div className="auth-problem" role="alert">Сохранённая компания больше не найдена. Можно начать настройку компании заново.<Button type="button" variant="secondary" onClick={() => { clearPendingCompanyId(); setResumedCompanyId(null); submit.reset(); }}>Начать настройку компании заново</Button></div> : <div className="auth-notice" role="status">Компания уже создана: {company.data?.name || `ID ${resumedCompanyId}`}. Завершите создание пользователя. Повторная отправка не создаст компанию заново.</div>)}
    {resumedCompanyId && step === 2 && company.isPending && <p role="status">Проверяем сохранённую компанию…</p>}
    {resumedCompanyId && step === 2 && company.isError && !(company.error instanceof ApiError && company.error.status === 404) && <div className="auth-problem" role="alert"><strong>Не удалось проверить сохранённую компанию</strong>{company.error.message}<Button type="button" variant="secondary" onClick={() => company.refetch()}>Повторить проверку компании</Button></div>}
    <form className="w-form" noValidate ref={formRef} onSubmit={(event) => {
      event.preventDefault(); const next = validate(); setErrors(next);
      const first = (["fullName", "email", "companyName", "inn", "roles"] as const).find((key) => next[key]);
      if (first) { setAnnouncement(next[first] || "Проверьте поля формы."); if (step === 2 && (first === "fullName" || first === "email")) { changeStep(1); setErrors(next); } if (first === "roles") formRef.current?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.focus(); else requestAnimationFrame(() => (formRef.current?.elements.namedItem(first) as HTMLElement | null)?.focus()); return; }
      if (step === 1) { changeStep(2); return; }
      if (!roles.data?.length || roles.isError || roles.isLoading || pendingCompanyUnconfirmed) return;
      submit.mutate();
    }}>
      {step === 1 ? <>
        <AuthInput id="full-name" name="fullName" label="Как вас зовут" value={form.fullName} onChange={(event) => update("fullName", event.target.value)} onBlur={() => blur("fullName")} autoComplete="name" maxLength={120} error={errors.fullName} required />
        <AuthInput id="email" name="email" label="Электронная почта" value={form.email} onChange={(event) => update("email", event.target.value)} onBlur={() => blur("email")} type="email" autoComplete="email" autoCapitalize="none" spellCheck={false} error={errors.email} required maxLength={320} />
        <Button type="submit">Продолжить</Button>
      </> : <>
      <p className="auth-identity">{form.fullName} <span>{form.email}</span></p>
      {!resumedCompanyId && <><AuthInput id="company-name" name="companyName" label="Название компании" value={form.companyName} onChange={(event) => update("companyName", event.target.value)} onBlur={() => blur("companyName")} maxLength={160} error={errors.companyName} required disabled={submit.isPending} /><AuthInput id="inn" name="inn" label="ИНН компании" value={form.inn} onChange={(event) => update("inn", event.target.value.replace(/\D/g, "").slice(0, 12))} onBlur={() => blur("inn")} inputMode="numeric" autoComplete="off" error={errors.inn} required disabled={submit.isPending} /></>}
      <fieldset className="auth-roles" disabled={roles.isLoading || submit.isPending} aria-describedby={errors.roles ? "auth-roles-error" : undefined}><legend>Ваши роли в компании</legend><p>Можно выбрать несколько. Названия и описание ролей загружаются из каталога.</p>{roles.isLoading && <p role="status">Загружаем роли…</p>}{roles.data && <RolePicker roles={roles.data} selected={selected} onChange={(value) => { setSelected(value); setErrors((current) => ({ ...current, roles: undefined })); }} />}{errors.roles && <span className="auth-field-message is-error" id="auth-roles-error" role="alert">{errors.roles}</span>}</fieldset>
      {roles.isError && <div className="auth-problem" role="alert"><strong>Не удалось загрузить роли</strong>{roles.error.message}<Button type="button" variant="secondary" onClick={() => roles.refetch()}>Повторить</Button></div>}
      {!roles.isLoading && !roles.isError && !roles.data?.length && <p className="auth-problem" role="status">В каталоге пока нет ролей. Регистрация станет доступна после заполнения каталога.</p>}
      {submit.error && <div className="auth-problem" role="alert"><strong>Не удалось создать профиль</strong>{submit.error.message}</div>}
      <Button type="submit" disabled={submit.isPending || roles.isLoading || roles.isError || !roles.data?.length || pendingCompanyUnconfirmed}>{submit.isPending ? "Создаём профиль…" : "Завершить настройку"}</Button>
      <Button type="button" variant="secondary" disabled={submit.isPending} onClick={() => changeStep(1)}>Назад к данным пользователя</Button>
      </>}
    </form><p className="auth-draft-note">Черновик хранится в сессии этой вкладки и очищается после успешной регистрации. Закрытие вкладки может удалить его. {isDemoMode ? "Созданная демокомпания сохраняется локально." : "Ранее созданная компания остаётся на сервере."}</p><div className="auth-announcement" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
  </AuthShell>;
}
