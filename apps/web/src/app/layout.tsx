import type { Metadata } from "next";
import "./globals.css";
import "./design-system.css";
export const metadata: Metadata = {
  title: { default: "Mission Control · NEXUS", template: "%s · NEXUS" },
  description:
    "NEXUS — secure adversarial AI evaluation infrastructure. Light Forensic Intelligence.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
