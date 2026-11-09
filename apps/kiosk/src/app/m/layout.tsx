import type { Viewport } from "next";

// The kiosk locks zoom; this is a page on the shopper's own phone, where pinching must keep working.
export const viewport: Viewport = { width: "device-width", initialScale: 1, maximumScale: 5, userScalable: true };

export const metadata = { title: "Your look — Try-On Mirror" };

export default function MobileLayout({ children }: { children: React.ReactNode }) {
  return <div className="select-text">{children}</div>;
}
