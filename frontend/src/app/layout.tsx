import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";

import "./globals.css";

// Fonts, colours and the real header/footer come in step 1 (the design system). This layout only
// guarantees the one thing every page must have from the start: the disclaimer (CLAUDE.md §6).
export const metadata: Metadata = {
  title: "DrugWatch India",
  description: "Check whether a medicine batch appears in CDSCO's Not of Standard Quality alerts.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        {children}
        <footer className="border-t border-zinc-200 px-4 py-6 dark:border-zinc-800">
          <div className="mx-auto max-w-3xl">
            <Disclaimer />
          </div>
        </footer>
      </body>
    </html>
  );
}
