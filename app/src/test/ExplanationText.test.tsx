import { render, screen } from "@testing-library/react";
import { ExplanationText } from "../components/ExplanationText";

describe("ExplanationText", () => {
  it("renders bold and list items as elements, never as HTML", () => {
    const { container } = render(
      <ExplanationText text={"**Çeviri:** veri\n\n**Kelimeler:**\n- data: veri\n- <img src=x onerror=alert(1)>"} />,
    );
    expect(screen.getByText("Çeviri:").tagName).toBe("STRONG");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});
