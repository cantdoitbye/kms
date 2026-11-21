import type { Metadata } from "next";
import { Instrument_Sans, Newsreader } from "next/font/google";
import "./globals.css";

const instrument = Instrument_Sans({
  variable: "--font-instrument",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "Margin: ask your documents",
  description:
    "AI knowledge base: upload PDF, DOCX or text files and get answers with page-level citations. Hybrid search, reranking, pgvector.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${instrument.variable} ${newsreader.variable} h-full antialiased`}>
      <body className="h-full">{children}</body>
    </html>
  );
}
