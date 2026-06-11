import Link from "next/link";

export function Header() {
  return (
    <header className="siteHeader">
      <Link className="wordmark" href="/">
        shkandal<span>.ua</span>
      </Link>
      <p className="headerDescriptor">досьє суспільно важливих справ</p>
    </header>
  );
}
