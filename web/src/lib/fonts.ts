import { Noto_Sans, Noto_Sans_Bengali } from "next/font/google";

/**
 * Both families are loaded once here and shared by every root layout (see
 * next/font: each call is a separate hosted instance). Both pages need both:
 * the English page carries Bengali text too, if only the language switch.
 *
 * The CSS variables feed --font-sans in globals.css, where Noto Sans comes
 * first and Bengali glyphs fall through to Noto Sans Bengali.
 */
export const notoSans = Noto_Sans({
  subsets: ["latin"],
  variable: "--font-noto-sans",
  display: "swap",
});

export const notoSansBengali = Noto_Sans_Bengali({
  subsets: ["bengali"],
  variable: "--font-noto-bengali",
  display: "swap",
});

export const fontVariables = `${notoSans.variable} ${notoSansBengali.variable}`;
