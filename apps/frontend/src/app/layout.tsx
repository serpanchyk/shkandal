import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Shkandal",
  description: "Structured public case tracking for Ukrainian media stories.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
