'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { api, CurrentUser } from '@/lib/api';

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const router = useRouter();

  useEffect(() => {
    api<CurrentUser>('/auth/me').then(() => router.replace('/chat')).catch(() => undefined);
    api<{ registration_enabled: boolean }>('/auth/config')
      .then(config => setRegistrationEnabled(config.registration_enabled))
      .catch(() => setRegistrationEnabled(false));
  }, [router]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    if (mode === 'register' && password !== confirmPassword) {
      setError('Passwords do not match.');
      setLoading(false);
      return;
    }
    try {
      await api(`/auth/${mode === 'register' ? 'register' : 'login'}`, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      const next = new URLSearchParams(window.location.search).get('next');
      router.replace(next?.startsWith('/') ? next : '/chat');
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Authentication failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <Card className="w-full max-w-md shadow-xl border-none">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold tracking-tight text-center">{mode === 'login' ? 'Welcome back' : 'Create your Knowra account'}</CardTitle>
          <CardDescription className="text-center text-gray-500">
            {mode === 'login' ? 'Sign in to access your workspace' : 'Set up an account to protect your workspace'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70" htmlFor="email">Email</label>
              <Input id="email" type="email" placeholder="you@example.com" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} required />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70" htmlFor="password">Password</label>
              <Input id="password" type="password" minLength={8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} required />
            </div>
            {mode === 'register' && (
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="confirm-password">Confirm password</label>
                <Input id="confirm-password" type="password" minLength={8} autoComplete="new-password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} required />
                <p className="text-xs text-gray-500">Use at least 8 characters with a letter and a number.</p>
              </div>
            )}
            {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
            </Button>
          </form>
          {(registrationEnabled || mode === 'register') && (
            <button
              type="button"
              className="mt-5 w-full text-center text-sm text-gray-600 underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900"
              onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}
            >
              {mode === 'login' ? 'Need an account? Sign up' : 'Already have an account? Sign in'}
            </button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
