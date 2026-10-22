export function AnalysisHeading({ title, category, level = 2 }: {
  title: string;
  category?: string;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? 'h2' : 'h3';
  return <header className="w-analysis-heading">
    <Heading>{title}</Heading>
    {category && <span className="w-provenance">{category}</span>}
  </header>;
}
