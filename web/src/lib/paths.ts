/**
 * The site may be served from a sub-path (GitHub Pages serves a project at
 * /<repo>/). next/link adds that prefix itself; plain <a href> links to files
 * in public/ do not, so they go through here. Set at build time from the same
 * variable next.config.ts reads.
 */
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export function withBase(path: string): string {
  return `${BASE_PATH}${path}`;
}
