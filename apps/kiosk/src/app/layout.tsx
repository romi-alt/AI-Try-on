import type { Metadata, Viewport } from "next";
import { Providers } from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Try-On Mirror",
  description: "AI virtual try-on mirror kiosk",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-ink text-mist font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
