import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./app/App.tsx";

async function start() {
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCKS === "1") {
    const { setupWorker } = await import("msw/browser");
    const { createHandlers } = await import("./mocks/handlers");
    await setupWorker(...createHandlers()).start({ onUnhandledFrame: "bypass" });
  } else if (import.meta.env.PROD && "serviceWorker" in navigator) {
    // App-shell cache for the PWA (public/sw.js); API calls always go to the network.
    void navigator.serviceWorker.register("/sw.js");
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
