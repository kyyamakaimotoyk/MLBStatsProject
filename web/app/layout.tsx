import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { siteMeta } from "@/lib/copy";
import { LanguageProvider } from "@/lib/i18n";
import { ADSENSE_CLIENT, googleBootstrapScript } from "@/lib/ads";
import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";
import ConsentBanner from "@/components/ConsentBanner";
import GoogleTags from "@/components/GoogleTags";
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
  // AdSense site verification: the loader script is injected post-hydration,
  // which Google's crawler can't see — this server-rendered meta tag is what
  // it verifies ownership against.
  ...(ADSENSE_CLIENT
    ? { other: { "google-adsense-account": ADSENSE_CLIENT } }
    : {}),
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
        {/* Consent Mode v2 defaults must run before any Google script loads. */}
        <script dangerouslySetInnerHTML={{ __html: googleBootstrapScript() }} />
        <LanguageProvider>
          <SiteHeader />
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
            {children}
          </main>
          <SiteFooter />
          <ConsentBanner />
        </LanguageProvider>
        <GoogleTags />
      </body>
    </html>
  );
}
