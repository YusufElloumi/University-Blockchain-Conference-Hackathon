// Entry point for the /privacy and /terms pages. Loads no sign-in or blockchain code.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Legal, { type LegalDoc } from "./Legal";
import "./styles.css";

const root = document.getElementById("root")!;
const doc: LegalDoc = root.dataset.doc === "terms" ? "terms" : "privacy";

createRoot(root).render(
  <StrictMode>
    <Legal doc={doc} />
  </StrictMode>,
);
