import type { Metadata } from "next";

import "./globals.css";
import { fontVariables } from "@/lib/fonts";
import { withBase } from "@/lib/paths";

// With one root layout per language there is no single layout to build a 404
// page from, so this one stands alone (experimental.globalNotFound in
// next.config.ts). It cannot know which language the reader wanted, so it
// speaks both.

export const metadata: Metadata = {
  title: "পাতাটি পাওয়া যায়নি · Page not found",
};

export default function GlobalNotFound() {
  return (
    <html lang="bn" className={fontVariables}>
      <body className="font-sans antialiased">
        <main className="mx-auto max-w-xl px-4 py-16 sm:px-6">
          <h1 className="text-2xl font-semibold">পাতাটি পাওয়া যায়নি</h1>
          <p className="mt-2 text-ink-2">
            <a href={withBase("/")} className="text-accent-ink underline underline-offset-4">
              ইউনিয়নভিত্তিক ভাঙন-পূর্বাভাসে ফিরে যান
            </a>
          </p>
          <div lang="en" className="mt-10 border-t border-rule pt-6">
            <h2 className="text-xl font-semibold">Page not found</h2>
            <p className="mt-2 text-ink-2">
              <a href={withBase("/en/")} className="text-accent-ink underline underline-offset-4">
                Back to the union-level erosion forecast
              </a>
            </p>
          </div>
        </main>
      </body>
    </html>
  );
}
