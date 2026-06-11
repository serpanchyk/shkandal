import type { Metadata } from "next";
import { Header } from "@/components/header";
import "./styles.css";

export const metadata: Metadata = {
  title: { default: "Shkandal — досьє суспільно важливих справ", template: "%s | Shkandal" },
  description: "Українські суспільно важливі справи з хронологією та відкритими джерелами.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="uk">
      <body><div className="ambient" /><Header />{children}</body>
    </html>
  );
}
