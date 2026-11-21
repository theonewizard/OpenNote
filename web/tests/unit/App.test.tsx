import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, expect, it } from "vitest";

import { App } from "@/app/App";
import { createHandlers, createRest, initialNotes } from "@/mocks/handlers";
import { FakeSyncServer } from "@/mocks/sync-server";
import { server } from "./setup";

afterEach(() => {
  localStorage.clear();
  history.replaceState(null, "", "/");
});

function signedOut(options: Parameters<typeof createRest>[2] = {}) {
  const notes = initialNotes();
  const sync = new FakeSyncServer();
  const rest = createRest(notes, sync, { signedIn: false, ...options });
  server.use(...createHandlers(notes, sync, rest));
  return rest;
}

async function signIn(password = "correct horse battery") {
  fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "dana" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("shows the login screen when nobody is signed in, and the notes after signing in", async () => {
  signedOut();
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Sign in to OpenNote" })).toBeInTheDocument();
  await signIn();
  expect(await screen.findByRole("button", { name: /^Welcome/ })).toBeInTheDocument();
});

it("says when the password is wrong", async () => {
  signedOut();
  render(<App />);
  await signIn("wrong password!");
  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});

it("says how long to wait when login is rate limited", async () => {
  signedOut();
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json({ title: "Too many requests", status: 429 }, { status: 429, headers: { "Retry-After": "42", "Content-Type": "application/problem+json" } }),
    ),
  );
  render(<App />);
  await signIn();
  expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 42 seconds.");
});

it("offers one button per OIDC provider", async () => {
  signedOut({ loginMethods: ["password", "keycloak"] });
  render(<App />);
  expect(await screen.findByRole("button", { name: "Sign in with keycloak" })).toBeInTheDocument();
});

it("follows redirect_to when a native app sent the browser to log in", async () => {
  signedOut();
  history.replaceState(null, "", "/login?auth_request=0192a0c4-aaaa-7000-8000-000000000001");
  const assigned: string[] = [];
  const original = window.location;
  Object.defineProperty(window, "location", { configurable: true, value: { ...original, search: original.search, pathname: original.pathname, origin: original.origin, assign: (url: string) => assigned.push(url) } });
  try {
    render(<App />);
    await signIn();
    await waitFor(() => expect(assigned).toEqual(["/native-callback?code=mock&state=0192a0c4-aaaa-7000-8000-000000000001"]));
  } finally {
    Object.defineProperty(window, "location", { configurable: true, value: original });
  }
});

it("signs out, forgets the user and shows the login screen", async () => {
  const rest = signedOut();
  rest.signedIn = true;
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: /^Welcome/ }));
  await waitFor(() => expect(localStorage.getItem("opennote:user")).toBe(rest.user.id));
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("heading", { name: "Sign in to OpenNote" })).toBeInTheDocument();
  expect(rest.signedIn).toBe(false);
  expect(localStorage.getItem("opennote:user")).toBeNull();
});

it("returns to the login screen when the session expires", async () => {
  const rest = signedOut();
  rest.signedIn = true;
  render(<App />);
  expect(await screen.findByRole("button", { name: /^Welcome/ })).toBeInTheDocument();
  rest.signedIn = false;
  fireEvent.click(screen.getByRole("button", { name: "Favorites" }));
  expect(await screen.findByRole("heading", { name: "Sign in to OpenNote" })).toBeInTheDocument();
});
