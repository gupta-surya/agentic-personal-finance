import { categoryColor, categoryKey } from "./colors";

describe("categoryColor", () => {
  it("follows the category, whether named by series id or label", () => {
    expect(categoryColor("category:rent")).toBe(categoryColor("Rent"));
    expect(categoryColor("category:fees_interest")).toBe(categoryColor("Fees interest"));
    expect(categoryKey("Fees interest")).toBe("fees_interest");
  });

  it("keeps the common categories apart", () => {
    const common = ["rent", "travel", "groceries", "dining", "transport", "utilities", "shopping"];
    expect(new Set(common.map(categoryColor)).size).toBe(common.length);
  });

  it("greys the folded bucket and uncategorized spend", () => {
    expect(categoryColor("everything_else")).toBe("var(--series-neutral)");
    expect(categoryColor("Everything else")).toBe("var(--series-neutral)");
    expect(categoryColor("Uncategorized")).toBe("var(--series-neutral)");
  });

  it("gives an unknown category a stable validated slot, never red", () => {
    const color = categoryColor("category:pet_care");
    expect(color).toBe(categoryColor("Pet care"));
    expect(color).toMatch(/^var\(--series-[1-7]\)$/);
  });
});
