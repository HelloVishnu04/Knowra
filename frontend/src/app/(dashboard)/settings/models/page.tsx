'use client';

import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api, ModelProvider } from '@/lib/api';

type ProviderType = ModelProvider['provider_type'];

const defaults: Record<ProviderType, string> = {
  ollama: 'http://host.docker.internal:11434',
  lm_studio: 'http://host.docker.internal:1234/v1',
  google_gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  openai_compatible: 'https://api.openai.com/v1',
};

const emptyForm = {
  name: 'Local Ollama',
  provider_type: 'ollama' as ProviderType,
  base_url: defaults.ollama,
  api_key: '',
  models: '',
  is_enabled: true,
};

export default function ModelsPage() {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const selected = useMemo(() => providers.find(item => item.id === editingId), [editingId, providers]);

  async function load() {
    setProviders(await api<ModelProvider[]>('/providers'));
  }

  useEffect(() => {
    let active = true;
    api<ModelProvider[]>('/providers')
      .then(value => { if (active) setProviders(value); })
      .catch(caught => { if (active) setError(caught.message); });
    return () => { active = false; };
  }, []);

  function changeType(provider_type: ProviderType) {
    setForm(current => ({
      ...current,
      provider_type,
      base_url: defaults[provider_type],
      name: provider_type === 'ollama' ? 'Local Ollama' : provider_type === 'lm_studio' ? 'LM Studio' : provider_type === 'google_gemini' ? 'Google Gemini' : 'OpenAI compatible',
    }));
  }

  function edit(provider: ModelProvider) {
    setEditingId(provider.id);
    setForm({
      name: provider.name,
      provider_type: provider.provider_type,
      base_url: provider.base_url,
      api_key: '',
      models: provider.models.join(', '),
      is_enabled: provider.is_enabled,
    });
    setMessage('');
    setError('');
  }

  function reset() {
    setEditingId(null);
    setForm(emptyForm);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    const payload = {
      ...form,
      models: form.models.split(',').map(item => item.trim()).filter(Boolean),
      api_key: form.api_key || null,
    };
    try {
      await api(editingId ? `/providers/${editingId}` : '/providers', {
        method: editingId ? 'PUT' : 'POST',
        body: JSON.stringify(payload),
      });
      await load();
      setMessage(editingId ? 'Provider updated.' : 'Provider added. You can now discover or manually add models.');
      reset();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save provider.');
    } finally {
      setBusy(false);
    }
  }

  async function action(provider: ModelProvider, kind: 'test' | 'discover') {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await api<{ models?: string[]; models_found?: number }>(`/providers/${provider.id}/${kind}`, { method: 'POST' });
      await load();
      setMessage(kind === 'test' ? `Connection successful. Found ${result.models_found ?? 0} model(s).` : `Model list updated. Found ${result.models?.length ?? 0} model(s).`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `Could not ${kind} provider.`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(provider: ModelProvider) {
    if (!window.confirm(`Delete ${provider.name}?`)) return;
    setBusy(true);
    try {
      await api<void>(`/providers/${provider.id}`, { method: 'DELETE' });
      if (editingId === provider.id) reset();
      await load();
      setMessage('Provider deleted.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete provider.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-6 lg:p-10">
      <div className="mx-auto max-w-6xl">
        <div className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">AI configuration</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Models & Providers</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">Connect Ollama, LM Studio, Google Gemini, OpenAI, Groq, OpenRouter, or another OpenAI-compatible endpoint. Knowra never downloads a model from this page.</p>
        </div>

        {(message || error) && <div className={`mb-6 rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}

        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <section className="space-y-4">
            {providers.length === 0 && <div className="rounded-xl border border-dashed bg-white p-8 text-center text-sm text-slate-500">No model provider is configured yet. Add one using the form.</div>}
            {providers.map(provider => (
              <article key={provider.id} className="rounded-xl border bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2"><h2 className="font-semibold">{provider.name}</h2><span className={`rounded-full px-2 py-0.5 text-xs ${provider.is_enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{provider.is_enabled ? 'Enabled' : 'Disabled'}</span></div>
                    <p className="mt-1 text-xs uppercase tracking-wide text-slate-500">{provider.provider_type.replace('_', ' ')}</p>
                    <p className="mt-2 break-all text-sm text-slate-600">{provider.base_url}</p>
                    <p className="mt-1 text-xs text-slate-500">API key: {provider.has_api_key ? `saved securely${provider.api_key_version ? ` · ${provider.api_key_version}` : ''}` : 'not set'}</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => edit(provider)}>Edit</Button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {provider.models.length ? provider.models.map(model => <span key={model} className="rounded-md bg-slate-100 px-2 py-1 text-xs">{model}</span>) : <span className="text-xs text-amber-700">No models added yet</span>}
                </div>
                <div className="mt-5 flex flex-wrap gap-2 border-t pt-4">
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => action(provider, 'test')}>Test connection</Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => action(provider, 'discover')}>Discover models</Button>
                  <Button size="sm" variant="outline" disabled={busy} className="text-red-600" onClick={() => remove(provider)}>Delete</Button>
                </div>
              </article>
            ))}
          </section>

          <section className="rounded-xl border bg-white p-6 shadow-sm lg:sticky lg:top-6 lg:self-start">
            <h2 className="text-lg font-semibold">{selected ? `Edit ${selected.name}` : 'Add a provider'}</h2>
            <form className="mt-5 space-y-4" onSubmit={save}>
              <div className="space-y-2"><label className="text-sm font-medium" htmlFor="provider-type">Provider type</label><select id="provider-type" className="h-10 w-full rounded-md border bg-white px-3 text-sm" value={form.provider_type} onChange={event => changeType(event.target.value as ProviderType)}><option value="ollama">Ollama</option><option value="lm_studio">LM Studio</option><option value="google_gemini">Google Gemini</option><option value="openai_compatible">OpenAI compatible</option></select></div>
              <div className="space-y-2"><label className="text-sm font-medium" htmlFor="provider-name">Display name</label><Input id="provider-name" value={form.name} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} required /></div>
              <div className="space-y-2"><label className="text-sm font-medium" htmlFor="base-url">Base URL</label><Input id="base-url" type="url" value={form.base_url} readOnly={form.provider_type === 'google_gemini'} onChange={event => setForm(current => ({ ...current, base_url: event.target.value }))} required /><p className="text-xs text-slate-500">LM Studio localhost URLs are automatically converted to <code>host.docker.internal:1234/v1</code> for Docker. Hosted deployments block private network destinations unless an administrator explicitly allows the hostname.</p></div>
              {form.provider_type !== 'ollama' && <div className="space-y-2"><label className="text-sm font-medium" htmlFor="api-key">API key {form.provider_type === 'lm_studio' && '(optional)'}</label><Input id="api-key" type="password" autoComplete="off" required={form.provider_type === 'google_gemini' && !selected?.has_api_key} value={form.api_key} placeholder={selected?.has_api_key ? 'Leave blank to keep saved key' : form.provider_type === 'google_gemini' ? 'Google AI Studio API key' : 'Enter API key'} onChange={event => setForm(current => ({ ...current, api_key: event.target.value }))} /><p className="text-xs text-slate-500">The key is encrypted before it is saved and is never returned by the API.</p></div>}
              <div className="space-y-2"><label className="text-sm font-medium" htmlFor="models">Model IDs</label><Input id="models" value={form.models} placeholder="llama3.2, qwen2.5-coder:7b" onChange={event => setForm(current => ({ ...current, models: event.target.value }))} /><p className="text-xs text-slate-500">Comma-separated. You can also save first, then use Discover models.</p></div>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_enabled} onChange={event => setForm(current => ({ ...current, is_enabled: event.target.checked }))} />Available in chat</label>
              <div className="flex gap-2 pt-2"><Button type="submit" disabled={busy}>{busy ? 'Saving…' : selected ? 'Update provider' : 'Add provider'}</Button>{selected && <Button type="button" variant="outline" onClick={reset}>Cancel</Button>}</div>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}
