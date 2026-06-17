import Link from "next/link";

const externalLinkProps = {
  rel: "noopener noreferrer",
  target: "_blank",
} as const;

export function Footer() {
  return (
    <footer className="siteFooter">
      <div className="footerIntro">
        <p className="sectionCode">про проєкт / transparency</p>
        <p className="footerStatement">
          Шкандаль збирає розрізнені матеріали у досьє суспільно важливих справ.
          Сторінки формуються автоматично; перевіряйте твердження за оригінальними
          матеріалами джерел.
        </p>
      </div>
      <nav aria-label="Про проєкт" className="footerLinks">
        <Link href="/about">Про Шкандаль</Link>
        <a href="https://github.com/serpanchyk/shkandal" {...externalLinkProps}>
          GitHub ↗
        </a>
        <a href="https://chat.whatsapp.com/GKLJlgZ5Fh8Fp4WGc6ThB6" {...externalLinkProps}>
          Маєте ідеї або знайшли ваду? Доєднуйтесь до спільноти у WhatsApp.
        </a>
        <a href="https://www.linkedin.com/in/anton-mykhalchuk/" {...externalLinkProps}>
          Розробник: Антон Михальчук.
        </a>
      </nav>
      <p className="footerSupport">
        Шкандаль розроблено за підтримки{" "}
        <a href="https://aidept.com.ua/" {...externalLinkProps}>
          Катедри систем штучного інтелекту НУ «Львівська політехніка»
        </a>{" "}
        та{" "}
        <a href="https://lapathoniia.top/" {...externalLinkProps}>
          Lapathoniia
        </a>
        .
      </p>
    </footer>
  );
}
