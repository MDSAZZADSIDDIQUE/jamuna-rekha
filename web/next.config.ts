import type { NextConfig } from "next";

// Only set NEXT_PUBLIC_BASE_PATH when the site is hosted under a sub-path, such
// as a GitHub Pages project site at /jamuna-rekha. Leave it unset for a domain
// root (Vercel, Cloudflare Pages, a custom domain).
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || undefined;

const nextConfig: NextConfig = {
  // Plain HTML, CSS and JS in out/. There is no server to run, patch or pay
  // for, and nothing on the host that can be attacked.
  output: "export",
  // /en/ is written as out/en/index.html, which every static host serves
  // without rewrite rules.
  trailingSlash: true,
  basePath,
  images: { unoptimized: true },
  experimental: {
    // Bengali (/) and English (/en/) each have their own root layout so that
    // <html lang> is correct on both. That leaves no single layout to build a
    // 404 from; app/global-not-found.tsx is this version's documented answer.
    globalNotFound: true,
  },
};

export default nextConfig;
