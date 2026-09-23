import type { Metadata } from "next";

import "../globals.css";
import { fontVariables } from "@/lib/fonts";
import { dictionaries } from "@/lib/i18n";

// One root layout per language, so each page's <html lang> is right in the
// static HTML itself. Screen readers pick their voice from it, and browsers
// their hyphenation and line-breaking rules.

export const metadata: Metadata = {
  title: dictionaries.bn.htmlTitle,
  description: dictionaries.bn.htmlDescription,
};

export default function BengaliLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="bn" className={fontVariables}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
