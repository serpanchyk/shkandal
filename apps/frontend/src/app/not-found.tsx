import Link from "next/link";

export default function NotFound() {
  return <main className="statusPage"><p className="kicker">404 / не знайдено</p><h1>Такої сторінки немає</h1><Link href="/">Повернутися до справ</Link></main>;
}
