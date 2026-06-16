import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Про Шкандаль",
  description:
    "Як Шкандаль збирає українські матеріали у досьє суспільно важливих справ.",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <main className="pageShell aboutPage">
      <Link className="backLink" href="/">
        ← усі справи
      </Link>
      <header className="aboutHero panel">
        <p className="kicker">про проєкт / transparency</p>
        <h1>Про Шкандаль</h1>
        <p>
          Шкандаль допомагає побачити цілісну історію за розрізненими новинами
          про суспільно важливі справи в Україні.
        </p>
      </header>

      <div className="aboutSections">
        <section>
          <p className="sectionCode">01 / purpose</p>
          <h2>Навіщо існує Шкандаль</h2>
          <p>
            Одна справа може розвиватися місяцями, а матеріали про неї виходять
            у різні дні та в різних джерелах. Шкандаль поєднує ці матеріали у
            читацькі досьє з коротким поясненням, хронологією, згаданими особами
            й організаціями та посиланнями на пов’язані справи.
          </p>
        </section>

        <section>
          <p className="sectionCode">02 / process</p>
          <h2>Як матеріали стають досьє</h2>
          <p>
            Система знаходить матеріали українських медіа й установ, визначає
            їхню суспільну важливість, пов’язує їх зі справами та виділяє
            підтверджені матеріалами події й згадки. Кожна картка матеріалу веде
            на оригінальну сторінку видавця.
          </p>
        </section>

        <section>
          <p className="sectionCode">03 / limits</p>
          <h2>Як читати досьє</h2>
          <p>
            Досьє формуються автоматично з відкритих матеріалів і можуть містити
            неточності. Згадка особи чи організації не означає вини,
            відповідальності або формальної участі. Перевіряйте важливі
            твердження за оригінальними матеріалами джерел.
          </p>
        </section>

        <section>
          <p className="sectionCode">04 / support</p>
          <h2>Підтримка розробки</h2>
          <p>
            Шкандаль розроблено за підтримки{" "}
            <a href="https://aidept.com.ua/" rel="noopener noreferrer" target="_blank">
              Катедри систем штучного інтелекту НУ «Львівська політехніка»
            </a>{" "}
            та{" "}
            <a href="https://lapathoniia.top/" rel="noopener noreferrer" target="_blank">
              Lapatonia
            </a>
            .
          </p>
        </section>
      </div>
    </main>
  );
}
