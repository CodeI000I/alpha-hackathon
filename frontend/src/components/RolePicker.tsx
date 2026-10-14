import type { Role } from "../api/types";

interface Props {
  roles: Role[];
  selected: string[];
  onChange: (codes: string[]) => void;
}

// Пользователь может совмещать несколько ролей, поэтому выбор множественный.
export default function RolePicker({ roles, selected, onChange }: Props) {
  const toggle = (code: string) =>
    onChange(selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code]);
  return (
    <div className="roles">
      {roles.map((r) => (
        <label key={r.code} className={selected.includes(r.code) ? "role role--on" : "role"} title={r.question}>
          <input type="checkbox" checked={selected.includes(r.code)} onChange={() => toggle(r.code)} />
          {r.name}
        </label>
      ))}
    </div>
  );
}
