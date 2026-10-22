import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes, ReactNode } from 'react';

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'outline' };
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', className = '', type = 'button', ...props },
  ref,
) {
  return <button ref={ref} type={type} className={`button button--${variant} ${className}`} {...props} />;
});
export function Tag({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'red' | 'green' }) {
  return <span className={`tag tag--${tone}`}>{children}</span>;
}
type FieldMeta = { id: string; label: string; hint?: string; error?: string };
function FieldShell({ id, label, hint, error, children }: FieldMeta & { children: ReactNode }) {
  return <div className="field"><label htmlFor={id}>{label}</label>{children}
    {hint && <span className="field-hint" id={`${id}-hint`}>{hint}</span>}
    {error && <span className="field-error" id={`${id}-error`}>{error}</span>}
  </div>;
}
function accessibility({ id, hint, error }: FieldMeta) {
  return { 'aria-invalid': !!error, 'aria-describedby': [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined };
}
export type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & FieldMeta;
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, ...props },
  ref,
) {
  return <FieldShell {...{ id: props.id, label, hint, error }}><input ref={ref} className="control" {...props} {...accessibility({ id: props.id, label, hint, error })} /></FieldShell>;
});

export type SelectFieldProps = SelectHTMLAttributes<HTMLSelectElement> & FieldMeta;
export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, hint, error, children, ...props },
  ref,
) {
  return <FieldShell {...{ id: props.id, label, hint, error }}><div className="select-wrap"><select ref={ref} className="control" {...props} {...accessibility({ id: props.id, label, hint, error })}>{children}</select><img src={`${import.meta.env.BASE_URL}assets/chevron.svg`} width="20" height="20" alt="" /></div></FieldShell>;
});

export type TextAreaFieldProps = TextareaHTMLAttributes<HTMLTextAreaElement> & FieldMeta;
export const TextAreaField = forwardRef<HTMLTextAreaElement, TextAreaFieldProps>(function TextAreaField(
  { label, hint, error, ...props },
  ref,
) {
  return <FieldShell {...{ id: props.id, label, hint, error }}><textarea ref={ref} className="control" {...props} {...accessibility({ id: props.id, label, hint, error })} /></FieldShell>;
});
