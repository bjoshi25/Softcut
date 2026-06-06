import "./globals.css";
import type { Metadata } from "next";
import { PropsWithChildren } from "react";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Softcut",
  description: "Video moderation pipeline UI"
};

export default function RootLayout({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
