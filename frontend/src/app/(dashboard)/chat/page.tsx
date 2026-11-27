'use client';

import Link from 'next/link';
import { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { API_URL, api, csrfToken, ModelProvider } from '@/lib/api';
import { Citation, Citations } from '@/components/citations';
import { ChatStreamDecoder } from '@/lib/sse';
import { ScrollArea } from '@/components/ui/scroll-area';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  runId?: string;
  route?: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [providerId, setProviderId] = useState('');
  const [model, setModel] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const [bases, setBases] = useState<{ id: string; name: string }[]>([]);
  const [kb, setKb] = useState('');
  const [repositories, setRepositories] = useState<{ id: string; name: string; status: string }[]>([]);
  const [repositoryId, setRepositoryId] = useState('');
  const [route, setRoute] = useState<'auto' | 'direct' | 'web' | 'document' | 'sql' | 'code' | 'multi'>('auto');
  useEffect(() => {
    const selected = new URLSearchParams(window.location.search).get('kb');
    const selectedRepository = new URLSearchParams(window.location.search).get('repository');
    api<{ id: string; name: string }[]>('/knowledge-bases').then(value => {
      setBases(value);
      if (selected && value.some(base => base.id === selected)) setKb(selected);
    }).catch(console.error);
    api<{ id: string; name: string; status: string }[]>('/repositories').then(value => {
      setRepositories(value.filter(repository => repository.status === 'ready'));
      if (selectedRepository && value.some(repository => repository.id === selectedRepository && repository.status === 'ready')) setRepositoryId(selectedRepository);
    }).catch(console.error);
    api<ModelProvider[]>('/providers').then(value => {
      const enabled = value.filter(provider => provider.is_enabled);
      setProviders(enabled);
      if (enabled.length) {
        setProviderId(enabled[0].id);
        setModel(enabled[0].models[0] || '');
      }
    }).catch(console.error);
  }, []);

  const activeProvider = providers.find(provider => provider.id === providerId);

  function selectProvider(id: string) {
    const provider = providers.find(item => item.id === id);
    setProviderId(id);
    setModel(provider?.models[0] || '');
    setMessages([]);
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading || !providerId || !model) return;

    const userMessage: Message = { id: Date.now().toString(), role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    const assistantId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: assistantId, role: 'assistant', content: '' }]);

    try {
      const payload = {
        messages: [...messages, userMessage].map(m => ({ role: m.role, content: m.content })),
        model: model,
        provider: providerId,
        stream: true
        , knowledge_base_id: kb || null
        , repository_id: repositoryId || null
        stream: true,
        route: route,
        knowledge_base_id: kb || null,
        repository_id: repositoryId || null,
      };

      const apiUrl = API_URL;
      const csrf = csrfToken();
      const res = await fetch(`${apiUrl}/api/v1/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        },
        credentials: 'include',
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        const message = error.detail || error.error?.message || 'Failed to fetch chat';
        throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
      }
      if (!res.body) throw new Error('No readable stream');

      const reader = res.body.getReader();
      const decoder = new ChatStreamDecoder();
      let done = false;
      let completed = false;

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          for (const dataStr of decoder.push(value)) {
            if (dataStr === '[DONE]') {
              done = true;
              completed = true;
              break;
            }
            if (!dataStr) continue;
            const data = JSON.parse(dataStr);
            if (data.error) throw new Error(data.error);
            setMessages(prev =>
              prev.map(m => m.id === assistantId ? {
                ...m,
                content: m.content + (data.content || ''),
                citations: data.citations ?? m.citations,
                runId: data.run_id ?? m.runId,
                route: data.route ?? m.route,
              } : m)
            );
          }
        }
      }
      await reader.cancel();
      if (!completed) throw new Error('The response was interrupted. Please retry.');
    } catch (error) {
      console.error(error);
      setMessages(prev =>
        prev.map(m => m.id === assistantId ? { ...m, content: `Error: ${error instanceof Error ? error.message : 'Could not reach the model.'}` } : m)
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-800">
      <header className="min-h-14 border-b flex flex-wrap items-center gap-3 px-4 py-2 justify-between flex-shrink-0">
        <h1 className="font-semibold">Knowra Chat</h1>
        <select aria-label="Knowledge base" disabled={loading} value={kb} className="border rounded p-1 max-w-60" onChange={e => { setKb(e.target.value); setMessages([]); }}>
          <option value="">General chat</option>
          {bases.map(base => <option key={base.id} value={base.id}>{base.name}</option>)}
        </select>
        <select aria-label="Code repository" disabled={loading} value={repositoryId} className="border rounded p-1 max-w-60" onChange={e => { setRepositoryId(e.target.value); setMessages([]); }}>
          <option value="">No code repository</option>
          {repositories.map(repository => <option key={repository.id} value={repository.id}>{repository.name}</option>)}
        </select>
        <select aria-label="Retrieval mode" disabled={loading} value={route} className="border rounded p-1 text-sm" onChange={e => setRoute(e.target.value as typeof route)}>
          <option value="auto">Auto route</option>
          <option value="web">Web search</option>
          <option value="direct">Direct (LLM only)</option>
          <option value="document">Documents</option>
          <option value="code">Code</option>
          <option value="sql">SQL</option>
          <option value="multi">Multi-source</option>
        </select>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500">Provider:</span>
          <select
            aria-label="Model provider"
            value={providerId}
            onChange={event => selectProvider(event.target.value)}
            className="border rounded px-2 py-1 bg-transparent"
          >
            {!providers.length && <option value="">Not configured</option>}
            {providers.map(provider => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
          </select>
          <span className="text-gray-500">Model:</span>
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            className="border rounded px-2 py-1 bg-transparent"
          >
            {!activeProvider?.models.length && <option value="">No models</option>}
            {activeProvider?.models.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
          <Link href="/settings/models" className="rounded border px-2 py-1 text-xs hover:bg-slate-50">Configure</Link>
        </div>
      </header>

      <ScrollArea className="flex-1 p-4">
        <div className="max-w-3xl mx-auto space-y-6 pb-20">
          {!providers.length && (
            <div className="mx-auto mt-16 max-w-xl rounded-xl border border-dashed bg-slate-50 p-8 text-center">
              <p className="text-lg font-medium text-slate-800">Connect a model provider to start chatting</p>
              <p className="mt-2 text-sm text-slate-500">Add Ollama, LM Studio, or an OpenAI-compatible API. No model is downloaded automatically.</p>
              <Link href="/settings/models" className="mt-5 inline-block rounded-md bg-slate-900 px-4 py-2 text-sm text-white">Add a provider</Link>
            </div>
          )}
          {!!providers.length && !activeProvider?.models.length && (
            <div className="mx-auto mt-16 max-w-xl rounded-xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800">This provider has no model IDs. Add one manually or use Discover models in <Link href="/settings/models" className="underline">Models & Providers</Link>.</div>
          )}
          {messages.length === 0 && !!providerId && !!model && (
            <div className="text-center text-gray-500 mt-20">
              <p className="text-lg">Start a conversation with Knowra</p>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`flex gap-4 ${m.role === 'user' ? 'justify-end' : ''}`}>
              {m.role === 'assistant' && (
                <Avatar className="w-8 h-8 flex-shrink-0">
                  <AvatarFallback className="bg-primary text-primary-foreground">AI</AvatarFallback>
                </Avatar>
              )}
              <div className={`rounded-xl px-4 py-3 max-w-[80%] ${m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-gray-100 dark:bg-gray-700'}`}>
                <div className="whitespace-pre-wrap">{m.content}</div>
                {!!m.citations?.length && <Citations citations={m.citations} />}
                {m.role === 'assistant' && m.runId && <Link href={`/runs/${m.runId}`} className="mt-3 block border-t pt-2 text-xs underline opacity-70">View {m.route ? `${m.route} ` : ''}run trace →</Link>}
              </div>
              {m.role === 'user' && (
                <Avatar className="w-8 h-8 flex-shrink-0">
                  <AvatarFallback>U</AvatarFallback>
                </Avatar>
              )}
            </div>
          ))}
          <div ref={scrollRef} />
        </div>
      </ScrollArea>

      <div className="p-4 bg-white dark:bg-gray-800 border-t flex-shrink-0">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto relative flex items-center">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything..."
            className="w-full pr-12 rounded-full shadow-sm border-gray-300 dark:border-gray-600 focus-visible:ring-primary"
            disabled={loading || !providerId || !model}
          />
          <Button
            type="submit"
            size="icon"
            className="absolute right-1 rounded-full h-8 w-8"
            disabled={loading || !input.trim() || !providerId || !model}
          >
            <span className="sr-only">Send</span>
            &rarr;
          </Button>
        </form>
      </div>
    </div>
  );
}
