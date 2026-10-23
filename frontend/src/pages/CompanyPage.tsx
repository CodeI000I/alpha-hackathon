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

  const errorText = (error: unknown) => error instanceof Error ? error.message : "Не удалось загрузить данные.";
  if (user.isLoading) return <p role="status">Загрузка пользователя…</p>;
  if (user.isError) return <p className="error" role="alert">Не удалось загрузить пользователя: {errorText(user.error)} <button onClick={() => user.refetch()}>Повторить</button></p>;
  if (companyId === null) return <p>К пользователю не привязана компания.</p>;
  if (company.isLoading) return <p role="status">Загрузка компании…</p>;
  if (company.isError) return <p className="error" role="alert">Не удалось загрузить компанию: {errorText(company.error)} <button onClick={() => company.refetch()}>Повторить</button></p>;
  if (!company.data) return <p className="error" role="alert">Данные компании недоступны.</p>;

  return (
    <section className="card">
      <h1>{company.data.name}</h1>
      <p className="muted">ИНН {company.data.inn}</p>

      <h2>Профиль</h2>
      {elements.isLoading && <p role="status">Загрузка элементов профиля…</p>}
      {elements.isError && <p className="error" role="alert">Не удалось загрузить элементы профиля: {errorText(elements.error)} <button onClick={() => elements.refetch()}>Повторить</button></p>}
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
      {files.isLoading && <p role="status">Загрузка документов…</p>}
      {files.isError && <p className="error" role="alert">Не удалось загрузить документы: {errorText(files.error)} <button onClick={() => files.refetch()}>Повторить</button></p>}
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
