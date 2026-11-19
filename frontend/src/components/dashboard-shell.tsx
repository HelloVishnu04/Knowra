'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { api, CurrentUser } from '@/lib/api';

const links = [
  ['/code', 'Code Workspace'],
  ['/chat', 'Chat'],
  ['/knowledge', 'Knowledge Bases'],
  ['/runs', 'Runs & Traces'],
  ['/settings/models', 'Models & Providers'],
  ['/settings/access', 'Workspace Access'],
] as const;

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checked, setChecked] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    api<CurrentUser>('/auth/me')
      .then(setUser)
      .catch(() => router.replace(`/login?next=${encodeURIComponent(pathname)}`))
      .finally(() => setChecked(true));
  }, [pathname, router]);

  async function logout() {
    await api<void>('/auth/logout', { method: 'POST' }).catch(() => undefined);
    router.replace('/login');
    router.refresh();
  }

  if (!checked || !user) {
    return <div className="grid min-h-screen place-items-center bg-slate-50 text-sm text-slate-500">Checking your session…</div>;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-900">
      <aside className="w-64 border-r bg-white dark:bg-gray-800 flex-shrink-0">
        <div className="h-full flex flex-col">
          <div className="h-16 flex items-center px-6 border-b font-bold text-lg tracking-tight">Knowra</div>
          <nav className="flex-1 overflow-y-auto py-4">
            <ul className="space-y-1 px-3">
              {links.map(([href, label]) => (
                <li key={href}>
                  <Link
                    href={href}
                    className={`flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors ${pathname.startsWith(href) ? 'bg-slate-900 text-white' : 'hover:bg-gray-100 dark:hover:bg-gray-700'}`}
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="border-t p-4">
            <p className="truncate text-xs text-slate-500" title={user.email}>{user.email}</p>
            <Button variant="outline" size="sm" className="mt-3 w-full" onClick={logout}>Sign out</Button>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-hidden flex flex-col">{children}</main>
    </div>
  );
}
