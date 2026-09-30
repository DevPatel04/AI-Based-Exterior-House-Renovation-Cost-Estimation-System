import type { Metadata, Viewport } from "next";
import { ReactNode } from "react";
import AppShell from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "FacadePlan — Exterior renovation planning & cost estimates",
  description:
    "Upload an exterior photo, apply materials, generate a redesign, and get transparent quantity and cost estimates.",
};

export const viewport: Viewport = {
  themeColor: "#276a59",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
