import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, demoLogin, isDemoMode } from "../api/client";
import { DEMO_ACCOUNTS } from "../api/mocks";
import { setCurrentUserId } from "../session";
import { Button } from "../signal/components/ui";
import { AuthInput, AuthShell } from "../auth/AuthShell";

export default function LoginPage({ onComplete }: { onComplete: (userId: number) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const form = useRef<HTMLFormElement>(null);
  const passwordInput = useRef<HTMLInputElement>(null);
  const login = useMutation({ mutationFn: () => isDemoMode ? demoLogin(email, password) : api.login({ email: email.trim(), password }), onSuccess: (user) => { setPassword(""); setVisible(false); if (isDemoMode) setCurrentUserId(user.id); onComplete(user.id); } });
  const validate = () => ({ email: /^\S+@\S+\.\S+$/.test(email.trim()) ? undefined : "Укажите корректную электронную почту.", password: password ? undefined : "Введите пароль тестового аккаунта." });
  return <AuthShell mode="login"><h1>Войти в аккаунт</h1>
      <form className="w-form" ref={form} noValidate onSubmit={(event) => {
        event.preventDefault(); const next = validate(); setErrors(next);
        const first = next.email ? "email" : next.password ? "password" : null;
        if (first) { (form.current?.elements.namedItem(first) as HTMLElement | null)?.focus(); return; } login.mutate();
      }}>
        <AuthInput id="auth-email" name="email" label="Электронная почта" type="email" inputMode="email" autoComplete="email" autoCapitalize="none" spellCheck={false} value={email} onChange={(event) => { setEmail(event.target.value); setErrors((current) => ({ ...current, email: undefined })); login.reset(); }} onBlur={() => setErrors((current) => ({ ...current, email: validate().email }))} required error={errors.email} disabled={login.isPending} />
        <AuthInput id="auth-password" name="password" ref={passwordInput} label="Пароль" type={visible ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => { setPassword(event.target.value); setErrors((current) => ({ ...current, password: undefined })); login.reset(); }} onBlur={() => setErrors((current) => ({ ...current, password: validate().password }))} required error={errors.password} disabled={login.isPending} accessory={<button className="auth-password-toggle" type="button" aria-label={visible ? "Скрыть пароль" : "Показать пароль"} aria-controls="auth-password" aria-pressed={visible} onPointerDown={(event) => { if (event.pointerType === "mouse") event.preventDefault(); }} onClick={() => {
          const input = passwordInput.current; const hadFocus = input === document.activeElement; const position = input?.selectionStart ?? password.length;
          setVisible((current) => !current); if (hadFocus) requestAnimationFrame(() => { input?.focus({ preventScroll: true }); input?.setSelectionRange(position, position); });
        }}><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />{!visible && <path d="m3 3 18 18" />}</svg></button>} />
        {login.error && <div className="auth-problem" role="alert">{login.error.message}</div>}
        <Button type="submit" disabled={login.isPending}>{login.isPending ? "Проверяем…" : "Войти"}</Button>
      </form>
      {isDemoMode && <details className="auth-demo-accounts"><summary>Тестовые аккаунты</summary>{DEMO_ACCOUNTS.map((account) => <article key={account.userId}><strong>{account.label}</strong><p>{account.description}</p><code>{account.email}</code><code>{account.password}</code><button type="button" onClick={() => { setEmail(account.email); setPassword(account.password); setErrors({}); login.reset(); }}>Подставить реквизиты</button></article>)}</details>}
  </AuthShell>;
}
