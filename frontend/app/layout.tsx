import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SalmonSight — Every journey, in sight.",
  description: "Computer vision for understanding salmon passage behavior. Follow individual journeys, reveal movement patterns, and observe what happens beneath the surface.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
