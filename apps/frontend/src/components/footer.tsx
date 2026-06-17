import Link from "next/link";

const externalLinkProps = {
  rel: "noopener noreferrer",
  target: "_blank",
} as const;

export function Footer() {
  return (
    <footer className="siteFooter">
      <p className="sectionCode">про проєкт / transparency</p>
      <p className="footerStatement">
        Шкандаль зводить розрізнені публікації в цілісні справи.
        Сторінки складаються машинно, тому важливі твердження звіряйте з першоджерелами.
      </p>
      <div className="footerPills">
        <nav aria-label="Про проєкт" className="footerLinks footerLinks--primary">
          <Link href="/about">Про Шкандаль</Link>
          <a href="https://github.com/serpanchyk/shkandal" {...externalLinkProps}>
            GitHub ↗
          </a>
        </nav>
        <div className="footerLinks footerLinks--secondary">
          <a href="https://chat.whatsapp.com/GKLJlgZ5Fh8Fp4WGc6ThB6" {...externalLinkProps}>
            <span>Маєте ідеї або знайшли ваду?</span>{" "}
            <span>Доєднуйтесь до спільноти у WhatsApp ↗</span>
          </a>
          <a href="https://www.linkedin.com/in/anton-mykhalchuk/" {...externalLinkProps}>
            Розробник: Антон Михальчук ↗
          </a>
        </div>
      </div>
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
