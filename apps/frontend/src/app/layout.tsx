import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Unbounded } from "next/font/google";

import { Header } from "@/components/header";
import "./styles.css";

const sans = IBM_Plex_Sans({
  display: "swap",
  subsets: ["cyrillic", "latin"],
  variable: "--font-ibm-plex-sans",
  weight: "variable",
});

const mono = IBM_Plex_Mono({
  display: "swap",
  subsets: ["cyrillic", "latin"],
  variable: "--font-ibm-plex-mono",
  weight: ["400", "700"],
});

const display = Unbounded({
  display: "swap",
  subsets: ["cyrillic", "latin"],
  variable: "--font-unbounded",
  weight: "variable",
});

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
    <html className={`${sans.variable} ${mono.variable} ${display.variable}`} lang="uk">
      <body><div className="ambient" /><Header />{children}</body>
    </html>
  );
}
