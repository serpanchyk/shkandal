"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return <main className="statusPage"><p className="kicker">error / backend</p><h1>Не вдалося завантажити дані</h1><button onClick={reset}>спробувати ще раз</button></main>;
}
