import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { applyAccent, applyTheme, loadAccent, loadTheme } from "./lib/prefs";
import "./styles.css";

// Apply the saved theme and accent before the first paint (no flash).
applyTheme(loadTheme(), false);
applyAccent(loadAccent(), false);

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
