import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fyolo — Live fish tracking",
  description: "Local fish detection, persistent tracks, trajectories, crossings, and behavior overlays on live or uploaded video.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
