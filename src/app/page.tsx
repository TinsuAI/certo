import { getDiscoverySnapshot } from "@/lib/discovery";

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatScanTime(value: string) {
  return new Intl.DateTimeFormat("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) {
    return `${Math.max(1, Math.round(value / 1024))} KB`;
  }

  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default async function Home() {
  const snapshot = await getDiscoverySnapshot();

  if (!snapshot.available) {
    return (
      <main className="shell">
        <section className="hero">
          <p className="eyebrow">Barry CO Workbench</p>
          <h1>Local discovery is not ready yet.</h1>
          <p className="lede">
            Extract the agency archives into <code>data/extracted/CO</code> to
            populate the intake dashboard.
          </p>
        </section>
      </main>
    );
  }

  const statusGroups = snapshot.groups.filter(
    (group) => group.name === "Chưa hoàn thiện" || group.name === "Đã hoàn thiện",
  );
  const workingGroups = snapshot.groups.filter(
    (group) => group.name !== "Chưa hoàn thiện" && group.name !== "Đã hoàn thiện",
  );
  const activeCases =
    statusGroups.find((group) => group.name === "Chưa hoàn thiện")?.caseCount ?? 0;
  const completedCases =
    statusGroups.find((group) => group.name === "Đã hoàn thiện")?.caseCount ?? 0;

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Barry CO Workbench</p>
          <h1>Certificate of origin files, mapped from the agency archive.</h1>
          <p className="lede">
            This bootstrap reads the local case folders directly so the first
            screen reflects the real operating model: active dossiers, completed
            submissions, customs declarations, and the legacy macro workbook.
          </p>
        </div>
        <div className="hero-meta">
          <div className="meta-block">
            <span className="meta-label">Scan root</span>
            <span className="meta-value">{snapshot.rootLabel}</span>
          </div>
          <div className="meta-block">
            <span className="meta-label">Last scanned</span>
            <span className="meta-value">{formatScanTime(snapshot.scannedAt)}</span>
          </div>
        </div>
      </section>

      <section className="metrics">
        <article className="metric-card">
          <span className="metric-label">Documents</span>
          <strong>{formatCount(snapshot.totalDocuments)}</strong>
          <p>Non-archive source files currently available for discovery.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Open Archives</span>
          <strong>{formatCount(snapshot.remainingArchives.length)}</strong>
          <p>Nested bundles still present after ZIP expansion.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Active Cases</span>
          <strong>{formatCount(activeCases)}</strong>
          <p>Folders under the in-progress status bucket.</p>
        </article>
        <article className="metric-card">
          <span className="metric-label">Completed Cases</span>
          <strong>{formatCount(completedCases)}</strong>
          <p>Folders already filed under the completed bucket.</p>
        </article>
      </section>

      <section className="panel-grid">
        <article className="panel">
          <div className="panel-heading">
            <p className="eyebrow">Workflow Artifacts</p>
            <h2>Legacy process sources</h2>
          </div>
          <ul className="file-list">
            {snapshot.workflowFiles.map((file) => (
              <li key={file.relativePath}>
                <span>{file.relativePath}</span>
                <span>{file.extension.toUpperCase()}</span>
              </li>
            ))}
          </ul>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <p className="eyebrow">Status Split</p>
            <h2>Case buckets</h2>
          </div>
          <div className="status-grid">
            {statusGroups.map((group) => (
              <div className="status-card" key={group.name}>
                <h3>{group.name}</h3>
                <p>{formatCount(group.caseCount)} case folders</p>
                <p>{formatCount(group.documentCount)} documents</p>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-grid">
        <article className="panel">
          <div className="panel-heading">
            <p className="eyebrow">Working Sets</p>
            <h2>Top-level discovery groups</h2>
          </div>
          <div className="group-list">
            {workingGroups.map((group) => (
              <section className="group-card" key={group.name}>
                <header>
                  <h3>{group.name}</h3>
                  <span>
                    {formatCount(group.documentCount)} docs / {formatCount(group.archiveCount)} archives
                  </span>
                </header>
                <p className="group-summary">
                  {group.caseCount > 0
                    ? `${formatCount(group.caseCount)} nested case folders discovered.`
                    : "Single dossier or working folder."}
                </p>
                <ul className="sample-list">
                  {group.samples.map((sample) => (
                    <li key={sample.relativePath}>
                      <span>{sample.relativePath}</span>
                      <span>{sample.extension.toUpperCase()}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <p className="eyebrow">Archive Backlog</p>
            <h2>Bundles still worth opening</h2>
          </div>
          <ul className="archive-list">
            {snapshot.remainingArchives.map((archive) => (
              <li key={archive.relativePath}>
                <div>
                  <strong>{archive.relativePath}</strong>
                  <p>{archive.extension.toUpperCase()} archive</p>
                </div>
                <span>{formatBytes(archive.sizeInBytes)}</span>
              </li>
            ))}
          </ul>
        </article>
      </section>

      <section className="panel panel-wide">
        <div className="panel-heading">
          <p className="eyebrow">Document Mix</p>
          <h2>File types driving the current workflow</h2>
        </div>
        <div className="chip-row">
          {snapshot.extensionCounts.map((entry) => (
            <span className="chip" key={entry.extension}>
              {entry.extension.toUpperCase()} {formatCount(entry.count)}
            </span>
          ))}
        </div>
      </section>
    </main>
  );
}
