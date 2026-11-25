import { render, screen } from "@testing-library/react";
import { Chip, toneOf } from "./ui";
import { pct, pp, usd, usdK } from "../lib/format";

describe("Chip", () => {
  it("names its colour on hover so meaning never rests on colour alone", () => {
    render(<Chip tone="bad" meaning="credit stress">CR1</Chip>);
    expect(screen.getByText("CR1")).toHaveAttribute("title", "Red — credit stress");
  });
  it("maps signal statuses to tones", () => {
    expect(toneOf("green")).toBe("good");
    expect(toneOf("amber")).toBe("warn");
    expect(toneOf("red")).toBe("bad");
    expect(toneOf("na")).toBe("muted");
  });
});

describe("format", () => {
  it("formats numbers and handles missing values", () => {
    expect(pct(0.1234)).toBe("12.3%");
    expect(pp(-3.21)).toBe("-3.2%");
    expect(usd(1234.5)).toBe("$1,234.50");
    expect(usdK(2_500_000)).toBe("$2.50M");
    expect(pct(null)).toBe("—");
    expect(usd(Number.NaN)).toBe("—");
  });
});
