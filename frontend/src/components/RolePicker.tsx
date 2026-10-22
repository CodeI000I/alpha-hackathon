import type { Role } from "../api/types";

interface Props {
  roles: Role[];
  selected: string[];
  onChange: (codes: string[]) => void;
  legend?: string;
  disabled?: boolean;
}

// Пользователь может совмещать несколько ролей, поэтому выбор множественный.
export default function RolePicker({ roles, selected, onChange, legend = "Выберите одну или несколько ролей", disabled = false }: Props) {
  const toggle = (code: string) =>
    onChange(selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code]);
  return (
    <fieldset className="role-picker" disabled={disabled}>
      <legend className="sr-only">{legend}</legend>
      <div className="role-picker__grid">
        {roles.map((role) => {
          const checked = selected.includes(role.code);
          return (
            <label key={role.code} className={`role-option${checked ? " role-option--selected" : ""}`}>
              <input type="checkbox" checked={checked} onChange={() => toggle(role.code)} />
              <span className="role-option__check" aria-hidden="true">
                <span />
              </span>
              <span className="role-option__copy">
                <strong>{role.name}</strong>
                {(role.focus || role.question) && <small>{role.focus || role.question}</small>}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
