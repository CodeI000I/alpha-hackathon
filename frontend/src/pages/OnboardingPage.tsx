import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, isDemoMode } from "../api/client";
import RolePicker from "../components/RolePicker";
import { Button, DemoBadge, StatePanel, TextField } from "../components/ui";
import {
  clearPendingCompanyId,
  pendingCompanyId,
  setCurrentUserId,
  setPendingCompanyId,
} from "../session";
import type { Company, CreateCompanyInput, CreateUserInput, User } from "../api/types";

interface FormState {
  fullName: string;
  email: string;
  companyName: string;
  inn: string;
}

type FormErrors = Partial<Record<keyof FormState | "roles", string>>;

const initialForm: FormState = { fullName: "", email: "", companyName: "", inn: "" };

interface OnboardingService {
  createCompany(input: CreateCompanyInput): Promise<Company>;
  createUser(input: CreateUserInput): Promise<User>;
}

function validate(form: FormState, selected: string[]): FormErrors {
  const errors: FormErrors = {};
  if (!form.fullName.trim()) errors.fullName = "Укажите имя.";
  else if (form.fullName.trim().length > 120) errors.fullName = "Не больше 120 символов.";
  if (!/^\S+@\S+\.\S+$/.test(form.email.trim())) errors.email = "Укажите корректную электронную почту.";
  if (!form.companyName.trim()) errors.companyName = "Укажите название компании.";
  else if (form.companyName.trim().length > 160) errors.companyName = "Не больше 160 символов.";
  if (!/^\d{10}(\d{2})?$/.test(form.inn.trim())) errors.inn = "ИНН должен содержать 10 или 12 цифр.";
  if (selected.length === 0) errors.roles = "Выберите хотя бы одну роль.";
  return errors;
}

export async function createOnboardingProfile(
  form: FormState,
  selectedRoles: string[],
  service: OnboardingService = api,
): Promise<User> {
  const normalized = {
    fullName: form.fullName.trim(),
    email: form.email.trim(),
    companyName: form.companyName.trim(),
    inn: form.inn.trim(),
  };
  let companyId = pendingCompanyId();
  if (!companyId) {
    const company = await service.createCompany({ name: normalized.companyName, inn: normalized.inn });
    companyId = company.id;
    setPendingCompanyId(companyId);
  }
  const user = await service.createUser({
    fullName: normalized.fullName,
    email: normalized.email,
    companyId,
    roles: selectedRoles,
  });
  clearPendingCompanyId();
  return user;
}

export default function OnboardingPage({ onComplete }: { onComplete: (userId: number) => void }) {
  const roles = useQuery({ queryKey: ["roles"], queryFn: api.roles });
  const [form, setForm] = useState<FormState>(initialForm);
  const [selected, setSelected] = useState<string[]>([]);
  const [errors, setErrors] = useState<FormErrors>({});
  const resumedCompanyId = useMemo(() => pendingCompanyId(), []);

  const submit = useMutation({
    mutationFn: () => createOnboardingProfile(form, selected),
    onSuccess: (user) => {
      setCurrentUserId(user.id);
      onComplete(user.id);
    },
  });

  const update = (key: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (errors[key]) setErrors((current) => ({ ...current, [key]: undefined }));
  };

  return (
    <div className="auth-page">
      <header className="auth-header page-width">
        <Link className="brand" to="/">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>Альфа Инсайты</span>
        </Link>
        {isDemoMode && <DemoBadge>Деморежим</DemoBadge>}
      </header>

      <main className="auth-main">
        <section className="auth-card" aria-labelledby="onboarding-title">
          <div className="auth-card__intro">
            <span className="eyebrow">Новый профиль</span>
            <h1 id="onboarding-title">Настройте персональную ленту</h1>
            <p>
              Расскажите, для какой компании и управленческих ролей подбирать события. Пароль не нужен:
              авторизация появится после подключения backend.
            </p>
          </div>

          {resumedCompanyId && (
            <div className="notice" role="status">
              Компания уже создана. Повторная отправка завершит создание пользователя без дубликата.
            </div>
          )}

          {roles.isError && (
            <StatePanel
              tone="error"
              title="Не удалось загрузить роли"
              text="Проверьте соединение с API и попробуйте ещё раз."
              action={<Button onClick={() => roles.refetch()}>Повторить</Button>}
            />
          )}

          <form
            className="form-stack"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              const nextErrors = validate(form, selected);
              setErrors(nextErrors);
              if (Object.keys(nextErrors).length === 0) submit.mutate();
            }}
          >
            <div className="form-grid">
              <TextField id="full-name" label="Как вас зовут" value={form.fullName} onChange={(event) => update("fullName", event.target.value)} autoComplete="name" maxLength={120} error={errors.fullName} required />
              <TextField id="email" label="Электронная почта" value={form.email} onChange={(event) => update("email", event.target.value)} type="email" autoComplete="email" placeholder="name@company.ru" error={errors.email} required />
              <TextField id="company-name" label="Название компании" value={form.companyName} onChange={(event) => update("companyName", event.target.value)} maxLength={160} error={errors.companyName} required />
              <TextField id="inn" label="ИНН компании" value={form.inn} onChange={(event) => update("inn", event.target.value.replace(/\D/g, "").slice(0, 12))} inputMode="numeric" autoComplete="off" error={errors.inn} required />
            </div>

            <fieldset className="role-fieldset" disabled={roles.isLoading || submit.isPending}>
              <legend>Ваши роли в компании</legend>
              <p>Можно выбрать несколько — у каждой будет свой ракурс ленты.</p>
              {roles.isLoading ? <div className="skeleton skeleton--roles" aria-label="Загрузка ролей" /> : <RolePicker roles={roles.data ?? []} selected={selected} onChange={setSelected} />}
              {errors.roles && <span className="field-error">{errors.roles}</span>}
            </fieldset>

            {submit.error && (
              <div className="inline-error" role="alert"><strong>Не удалось создать профиль</strong><span>{submit.error.message}</span></div>
            )}

            <Button type="submit" size="large" disabled={submit.isPending || roles.isError}>
              {submit.isPending ? "Создаём профиль…" : "Перейти к событиям"}
            </Button>
            <p className="form-footnote">
              Продолжая, вы создаёте профиль без пароля. ID пользователя хранится только в этом браузере.
            </p>
          </form>
        </section>
      </main>
    </div>
  );
}

export { validate as validateOnboarding };
