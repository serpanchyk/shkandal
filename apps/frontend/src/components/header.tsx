import Image from "next/image";
import Link from "next/link";

export function Header() {
  return (
    <header className="siteHeader">
      <Link className="wordmark" href="/">
        <Image alt="Shkandal" height={36} priority src="/logo.svg" width={255} />
      </Link>
      <form action="/" className="headerSearch">
        <label className="srOnly" htmlFor="header-query">Пошук справ</label>
        <input id="header-query" minLength={2} name="query" placeholder="Пошук справи" />
        <button type="submit">знайти</button>
      </form>
    </header>
  );
}
