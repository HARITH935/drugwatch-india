import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Adds DOM matchers such as toBeInTheDocument() and toHaveTextContent() to expect().
import "@testing-library/jest-dom/vitest";

// Testing Library only unmounts automatically when Vitest's globals are switched on. Without
// this, each test's render piles up in the same document and a later getByText() finds
// several copies of the same text - which is how this file came to exist.
afterEach(() => {
  cleanup();
});
