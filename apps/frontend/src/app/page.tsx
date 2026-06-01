const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Public cases, not a disposable feed</p>
        <h1>Shkandal</h1>
        <p className="lede">
          A structured dossier system for Ukrainian public scandals, investigations, key
          actors, and timelines.
        </p>
        <a className="healthLink" href={`${backendUrl}/healthz`}>
          API health
        </a>
      </section>
      <section className="pipeline" aria-label="Pipeline">
        {["Discover", "Extract", "Filter", "Resolve", "Review", "Publish"].map((step) => (
          <div className="step" key={step}>
            {step}
          </div>
        ))}
      </section>
    </main>
  );
}
