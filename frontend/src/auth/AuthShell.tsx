import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import "./auth.css";
import "./integration.css";

interface InputProps extends ComponentPropsWithoutRef<"input"> { id: string; label: string; error?: string; hint?: string; accessory?: ReactNode }
export const AuthInput = forwardRef<HTMLInputElement, InputProps>(function AuthInput({ id, label, error, hint, accessory, ...props }, ref) {
  const descriptionId = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return <div className="auth-field"><div className={`auth-field-surface${error ? " has-error" : ""}${accessory ? " has-accessory" : ""}`}>
    <input {...props} ref={ref} id={id} className="auth-input" placeholder=" " aria-invalid={Boolean(error)} aria-describedby={descriptionId} /><label className="auth-floating-label" htmlFor={id}>{label}</label>{accessory}
  </div>{(error || hint) && <span className={error ? "auth-field-message is-error" : "auth-field-message"} id={descriptionId}>{error || hint}</span>}</div>;
});

export function AuthShell({ mode, children }: { mode: "register" | "login"; children: ReactNode }) {
  const navigate = useNavigate();
  return <div className="w-app auth-page">
    <Link className="auth-back action-back" to="/landing"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M19 12H5m6-6-6 6 6 6" /></svg>На главную</Link>
    <main className="auth-box"><Link to="/landing" className="w-brand"><span className="w-alfa" aria-hidden="true">A</span>Альфа-Бизнес <span className="w-muted">/ Сигнал</span></Link>
      <div className="auth-tabs" data-mode={mode} role="group" aria-label="Вход или регистрация"><span className="auth-tabs-indicator" aria-hidden="true" /><button type="button" className={mode === "login" ? "active" : ""} aria-pressed={mode === "login"} onClick={() => navigate("/login")}>Вход</button><button type="button" className={mode === "register" ? "active" : ""} aria-pressed={mode === "register"} onClick={() => navigate("/register")}>Регистрация</button></div>
      <div className="auth-form-content">{children}</div>
    </main>
  </div>;
}
