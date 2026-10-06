import type { Metadata } from 'next';
import './globals.css';
import { LayoutTabs } from '@/components/LayoutTabs';
import { Header } from '@/components/Header';
import { AuthProvider } from '@/components/AuthContext';

export const metadata: Metadata = {
  title: 'RolloForge Dashboard',
  description: 'Bookmark intelligence for AI agents',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <div className="container">
            <Header />
            <LayoutTabs />
            <main>{children}</main>
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}// CSS cache bust 1774461278
