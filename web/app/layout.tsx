import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { siteMeta } from "@/lib/copy";
import { LanguageProvider } from "@/lib/i18n";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://moundmodel.com"),
  title: {
    default: `${siteMeta.title} — nightly MLB predictions, scored in public`,
    template: `%s — ${siteMeta.title}`,
  },
  description: siteMeta.subtitle,
  openGraph: {
    siteName: siteMeta.title,
    type: "website",
    url: "/",
    title: `${siteMeta.title} — nightly MLB predictions, scored in public`,
    description: siteMeta.subtitle,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <LanguageProvider>
          <SiteHeader />
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
            {children}
          </main>
        </LanguageProvider>
      </body>
    </html>
  );
}
