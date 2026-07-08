import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Legal AI Agent",
  description: "法律智能体应用前端",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
