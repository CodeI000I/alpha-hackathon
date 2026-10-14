import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

export default function CompanyPage({ userId }: { userId: number }) {
  const qc = useQueryClient();
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => api.user(userId) });
  const companyId = user.data?.companyId ?? null;
  const company = useQuery({
    queryKey: ["company", companyId],
    queryFn: () => api.company(companyId!),
    enabled: companyId !== null,
  });
  const elements = useQuery({ queryKey: ["profile-elements"], queryFn: api.profileElements });
  const files = useQuery({
    queryKey: ["files", companyId],
    queryFn: () => api.files(companyId!),
    enabled: companyId !== null,
  });
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadFile(companyId!, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["files", companyId] }),
  });

  if (!company.data) return <p>Загрузка…</p>;

  return (
    <section className="card">
      <h1>{company.data.name}</h1>
      <p className="muted">ИНН {company.data.inn}</p>

      <h2>Профиль</h2>
      <table className="profile">
        <tbody>
          {elements.data?.map((el) => (
            <tr key={el.code}>
              <td>{el.code}</td>
              <td title={el.description}>{el.name}</td>
              <td>{company.data.profile[el.code] ? "заполнено" : <span className="muted">нет данных</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Документы</h2>
      <input type="file" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
      {upload.error && <p className="error">{upload.error.message}</p>}
      <ul>
        {files.data?.map((f) => (
          <li key={f.id}>
            {f.filename} ({Math.round(f.sizeBytes / 1024)} КБ)
          </li>
        ))}
      </ul>
    </section>
  );
}
