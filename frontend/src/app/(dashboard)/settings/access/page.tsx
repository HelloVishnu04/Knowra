'use client';

import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  api,
  AuditEvent,
  CurrentUser,
  WorkspaceMember,
  WorkspaceRole,
} from '@/lib/api';

const roleLabel: Record<WorkspaceRole, string> = {
  owner: 'Owner',
  administrator: 'Administrator',
  member: 'Member',
  viewer: 'Viewer',
};

const roleTone: Record<WorkspaceRole, string> = {
  owner: 'bg-violet-100 text-violet-700',
  administrator: 'bg-blue-100 text-blue-700',
  member: 'bg-emerald-100 text-emerald-700',
  viewer: 'bg-slate-100 text-slate-600',
};

function readableAction(action: string) {
  return action
    .replace('workspace.', '')
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export default function WorkspaceAccessPage() {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WorkspaceRole>('member');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const canAdminister = currentUser?.role === 'owner' || currentUser?.role === 'administrator';
  const isOwner = currentUser?.role === 'owner';
  const availableRoles = useMemo<WorkspaceRole[]>(
    () => isOwner ? ['owner', 'administrator', 'member', 'viewer'] : ['member', 'viewer'],
    [isOwner],
  );

  async function load() {
    const user = await api<CurrentUser>('/auth/me');
    const memberList = await api<WorkspaceMember[]>('/workspaces/current/members');
    setCurrentUser(user);
    setMembers(memberList);
    if (user.role === 'owner' || user.role === 'administrator') {
      setEvents(await api<AuditEvent[]>('/workspaces/current/audit-events?limit=50'));
    } else {
      setEvents([]);
    }
  }

  useEffect(() => {
    let active = true;
    Promise.all([
      api<CurrentUser>('/auth/me'),
      api<WorkspaceMember[]>('/workspaces/current/members'),
    ])
      .then(async ([user, memberList]) => {
        if (!active) return;
        setCurrentUser(user);
        setMembers(memberList);
        if (user.role === 'owner' || user.role === 'administrator') {
          const audit = await api<AuditEvent[]>('/workspaces/current/audit-events?limit=50');
          if (active) setEvents(audit);
        }
      })
      .catch(caught => {
        if (active) setError(caught instanceof Error ? caught.message : 'Could not load workspace access.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  async function addMember(event: React.FormEvent) {
    event.preventDefault();
    setBusyId('add');
    setError('');
    setMessage('');
    try {
      await api('/workspaces/current/members', {
        method: 'POST',
        body: JSON.stringify({ email, role }),
      });
      await load();
      setEmail('');
      setRole('member');
      setMessage('Workspace member added.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add the workspace member.');
    } finally {
      setBusyId(null);
    }
  }

  async function changeRole(member: WorkspaceMember, nextRole: WorkspaceRole) {
    setBusyId(member.id);
    setError('');
    setMessage('');
    try {
      await api(`/workspaces/current/members/${member.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ role: nextRole }),
      });
      await load();
      setMessage(`${member.email} is now ${roleLabel[nextRole].toLowerCase()}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not change the workspace role.');
    } finally {
      setBusyId(null);
    }
  }

  async function removeMember(member: WorkspaceMember) {
    if (!window.confirm(`Remove ${member.email} from this workspace?`)) return;
    setBusyId(member.id);
    setError('');
    setMessage('');
    try {
      await api<void>(`/workspaces/current/members/${member.id}`, { method: 'DELETE' });
      await load();
      setMessage(`${member.email} no longer has access to this workspace.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not remove the workspace member.');
    } finally {
      setBusyId(null);
    }
  }

  function canManage(member: WorkspaceMember) {
    if (!canAdminister) return false;
    if (isOwner) return true;
    return member.role === 'member' || member.role === 'viewer';
  }

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-5 sm:p-7 lg:p-10">
      <div className="mx-auto max-w-6xl space-y-7">
        <header>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Workspace security</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Access & audit</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            Control who can use this workspace and review its recent access changes. New members need an existing Knowra account.
          </p>
        </header>

        <div aria-live="polite" aria-atomic="true">
          {(message || error) && (
            <div role={error ? 'alert' : 'status'} className={`rounded-xl border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
              {error || message}
            </div>
          )}
        </div>

        {loading ? (
          <div className="rounded-2xl border bg-white p-8 text-sm text-slate-500 shadow-sm">Loading workspace access…</div>
        ) : (
          <>
            <section className="grid gap-4 sm:grid-cols-3" aria-label="Workspace access summary">
              <div className="rounded-2xl border bg-white p-5 shadow-sm">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Members</p>
                <p className="mt-2 text-3xl font-semibold text-slate-950">{members.length}</p>
              </div>
              <div className="rounded-2xl border bg-white p-5 shadow-sm">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Your role</p>
                <p className="mt-3"><span className={`rounded-full px-2.5 py-1 text-sm font-medium ${roleTone[currentUser?.role ?? 'viewer']}`}>{roleLabel[currentUser?.role ?? 'viewer']}</span></p>
              </div>
              <div className="rounded-2xl border bg-white p-5 shadow-sm">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Recorded changes</p>
                <p className="mt-2 text-3xl font-semibold text-slate-950">{events.length}</p>
              </div>
            </section>

            {canAdminister && (
              <section className="rounded-2xl border bg-white p-5 shadow-sm sm:p-6" aria-labelledby="add-member-title">
                <div className="flex flex-col gap-1">
                  <h2 id="add-member-title" className="text-lg font-semibold text-slate-950">Add a member</h2>
                  <p className="text-sm text-slate-500">Enter the email address associated with an existing Knowra account.</p>
                </div>
                <form onSubmit={addMember} className="mt-5 grid gap-4 md:grid-cols-[1fr_220px_auto] md:items-end">
                  <div className="space-y-2">
                    <label htmlFor="member-email" className="text-sm font-medium text-slate-800">Email address</label>
                    <Input id="member-email" type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="teammate@example.com" required />
                  </div>
                  <div className="space-y-2">
                    <label htmlFor="member-role" className="text-sm font-medium text-slate-800">Initial role</label>
                    <select id="member-role" value={role} onChange={event => setRole(event.target.value as WorkspaceRole)} className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900">
                      {availableRoles.map(item => <option key={item} value={item}>{roleLabel[item]}</option>)}
                    </select>
                  </div>
                  <Button type="submit" disabled={busyId === 'add'}>{busyId === 'add' ? 'Adding…' : 'Add member'}</Button>
                </form>
              </section>
            )}

            <section className="overflow-hidden rounded-2xl border bg-white shadow-sm" aria-labelledby="members-title">
              <div className="border-b px-5 py-4 sm:px-6">
                <h2 id="members-title" className="text-lg font-semibold text-slate-950">Workspace members</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr><th scope="col" className="px-6 py-3 font-medium">Account</th><th scope="col" className="px-4 py-3 font-medium">Role</th><th scope="col" className="px-4 py-3 font-medium">Added</th><th scope="col" className="px-6 py-3 text-right font-medium">Actions</th></tr>
                  </thead>
                  <tbody className="divide-y">
                    {members.map(member => (
                      <tr key={member.id} className="text-slate-700">
                        <td className="px-6 py-4"><p className="font-medium text-slate-950">{member.email}</p>{member.user_id === currentUser?.id && <p className="mt-0.5 text-xs text-slate-500">You</p>}</td>
                        <td className="px-4 py-4">
                          {canManage(member) ? (
                            <select aria-label={`Role for ${member.email}`} value={member.role} disabled={busyId === member.id} onChange={event => changeRole(member, event.target.value as WorkspaceRole)} className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900">
                              {(isOwner ? ['owner', 'administrator', 'member', 'viewer'] : ['member', 'viewer']).map(item => <option key={item} value={item}>{roleLabel[item as WorkspaceRole]}</option>)}
                            </select>
                          ) : <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${roleTone[member.role]}`}>{roleLabel[member.role]}</span>}
                        </td>
                        <td className="px-4 py-4 text-slate-500">{new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(member.created_at))}</td>
                        <td className="px-6 py-4 text-right">{canManage(member) && <Button variant="outline" size="sm" className="text-red-600" disabled={busyId === member.id} onClick={() => removeMember(member)}>Remove</Button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {canAdminister && (
              <section className="rounded-2xl border bg-white shadow-sm" aria-labelledby="audit-title">
                <div className="border-b px-5 py-4 sm:px-6"><h2 id="audit-title" className="text-lg font-semibold text-slate-950">Recent access changes</h2><p className="mt-1 text-sm text-slate-500">The 50 most recent membership actions in this workspace.</p></div>
                <ol className="divide-y">
                  {events.length === 0 && <li className="px-6 py-8 text-center text-sm text-slate-500">No access changes have been recorded yet.</li>}
                  {events.map(event => (
                    <li key={event.id} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                      <div><p className="font-medium text-slate-900">{readableAction(event.action)}</p><p className="mt-0.5 text-xs text-slate-500">Actor {event.actor_user_id ?? 'system'} · {event.outcome}</p></div>
                      <time className="text-xs text-slate-500" dateTime={event.created_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(event.created_at))}</time>
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
