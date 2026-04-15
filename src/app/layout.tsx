import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Barry CO Workbench",
  description: "Local-first discovery workspace for certificate of origin case files.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="app-body">{children}</body>
    </html>
  );
}
