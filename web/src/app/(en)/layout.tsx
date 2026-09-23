import type { Metadata } from "next";

import "../globals.css";
import { fontVariables } from "@/lib/fonts";
import { dictionaries } from "@/lib/i18n";

// See (bn)/layout.tsx: a second root layout, for <html lang="en">.

export const metadata: Metadata = {
  title: dictionaries.en.htmlTitle,
  description: dictionaries.en.htmlDescription,
};

export default function EnglishLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={fontVariables}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
