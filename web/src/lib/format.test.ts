import { describe, expect, it } from "vitest";

import { makeFormatter, roughly } from "./format";

const bn = makeFormatter("bn");
const en = makeFormatter("en");

describe("makeFormatter", () => {
  it("uses Bengali digits and lakh grouping for Bengali", () => {
    expect(bn.int(123456)).toBe("১,২৩,৪৫৬");
    expect(en.int(123456)).toBe("123,456");
  });

  it("prints a real but sub-hectare area as <1, never as 0", () => {
    expect(en.hectares(0)).toBe("0");
    expect(en.hectares(0.3)).toBe("<1");
    expect(bn.hectares(0.3)).toBe("<১");
    expect(en.hectares(0.6)).toBe("1");
    expect(en.hectares(741.997)).toBe("742");
  });

  it("signs net change, and prints a net that rounds away as plain 0", () => {
    expect(en.signed(-740.56)).toBe("-741");
    expect(en.signed(1.44)).toBe("+1");
    expect(en.signed(-0.2)).toBe("0");
    expect(en.int(-0.2)).toBe("0");
  });

  it("formats mapping density, keeping a real but tiny density distinct from none", () => {
    expect(en.density(0)).toBe("0");
    expect(en.density(0.016)).toBe("<0.1");
    expect(bn.density(0.016)).toBe("<০.১");
    expect(en.density(2.47)).toBe("2.5");
    expect(en.density(171.56)).toBe("172");
  });

  it("formats years without grouping", () => {
    expect(en.year(2024)).toBe("2024");
    expect(bn.year(2024)).toBe("২০২৪");
  });

  it("names the month in UTC, so it cannot slip into the previous one", () => {
    expect(en.month("2025-03")).toBe("March 2025");
    expect(bn.month("2025-03")).toBe("মার্চ ২০২৫");
  });

  it("formats the threshold, the household size and shares", () => {
    expect(en.fixed2(0.55)).toBe("0.55");
    expect(bn.decimal(4.5)).toBe("৪.৫");
    expect(en.percent(0.6397)).toBe("64%");
  });
});

describe("roughly", () => {
  it("rounds to the nearest step", () => {
    expect(roughly(759.6, 10)).toBe(760);
    expect(roughly(695.97, 10)).toBe(700);
  });
});
