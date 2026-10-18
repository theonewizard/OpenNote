import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { Layout } from "@/app/Layout";

it("renders the three panes and status bar", () => {
  render(<Layout />);
  expect(screen.getByRole("navigation")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Note list" })).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(screen.getByRole("contentinfo")).toHaveTextContent("Not connected");
});
