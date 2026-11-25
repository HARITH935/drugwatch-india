import type { Metadata } from "next";

import { Disclaimer } from "@/components/Disclaimer";
import { SiteHeader } from "@/components/SiteHeader";

import "./globals.css";

export const metadata: Metadata = {
  title: "DrugWatch India",
  description: "Check whether a medicine batch appears in CDSCO's Not of Standard Quality alerts.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-background font-sans text-foreground">
        <SiteHeader />
        {children}
        <footer className="border-t border-border px-4 py-6">
          <div className="mx-auto max-w-3xl">
            <Disclaimer />
          </div>
        </footer>
      </body>
    </html>
  );
}
