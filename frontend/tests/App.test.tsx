import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { App } from "../src/App";

test("App renders the My App heading", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "My App" })).toBeInTheDocument();
});
