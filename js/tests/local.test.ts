import { describe, it, expect, vi, beforeEach } from 'vitest';
import { LocalAgent, LocalHTTPBackend, parseCommand } from '../src/integrations/local.js';
import { createRegistry } from '../src/registry.js';
import { runTool } from '../src/safety/guard.js';
vi.mock('../src/safety/guard.js', () => ({ runTool: vi.fn() }));
const ok = { title: 'fixture', output: 'success', error: false, attachments: [], metadata: {} };
const backend = (...responses: string[]) => ({ generate: vi.fn(async () => responses.shift()!) });
beforeEach(() => { vi.mocked(runTool).mockReset(); vi.mocked(runTool).mockResolvedValue(ok); });

describe('local agent', () => {
  it('exposes every registered tool with actions enabled', () => {
    const registry = createRegistry();
    const agent = new LocalAgent(backend(), { allowActions: true, registry });
    expect([...agent.allowed.keys()].sort()).toEqual(registry.all().map(t => t.name).sort());
  });
  it('executes every registered tool through the guard', async () => {
    const cases: Record<string, Record<string, unknown>> = {
      screenshot: {}, mouse: { action: 'move', x: 120, y: 80 }, keyboard: { action: 'type', text: 'hello' },
      app: { action: 'list' }, ui: { action: 'get_tree', app: 'Calculator' }, clipboard: { action: 'read' },
      ocr: {}, audit: { action: 'show' }, memory: { action: 'status' }, script: { action: 'shell', code: 'pwd' },
      browser: { action: 'tabs' }, memory_manage: { action: 'pause' },
    };
    expect(Object.keys(cases).sort()).toEqual(createRegistry().all().map(t => t.name).sort());
    for (const [tool, args] of Object.entries(cases)) {
      const agent = new LocalAgent(backend(JSON.stringify({ tool, arguments: args }), '{"answer":"done"}'), { allowActions: true, tools: [tool] });
      const r = await agent.run('fixture');
      expect(r.error, tool + ': ' + r.output).toBe(false);
      expect(vi.mocked(runTool).mock.lastCall?.[0].name).toBe(tool);
    }
  });
  it('blocks write actions by default', async () => {
    const r = await new LocalAgent(backend('{"tool":"app","arguments":{"action":"open","name":"Calculator"}}'), { maxSteps: 1 }).run('open');
    expect(r.error).toBe(true); expect(runTool).not.toHaveBeenCalled();
  });
  it('rejects unknown parameters and malformed JSON', async () => {
    for (const raw of ['[]', 'bad', '{"tool":"app","arguments":{"action":"list","peer":"x"}}']) {
      const r = await new LocalAgent(backend(raw), { maxSteps: 1 }).run('test');
      expect(r.error).toBe(true);
    }
    expect(runTool).not.toHaveBeenCalled();
  });
  it('requires an observation and returns tool failures', async () => {
    expect((await new LocalAgent(backend('{"answer":"done"}'), { maxSteps: 1 }).run('test')).error).toBe(true);
    vi.mocked(runTool).mockResolvedValue({ ...ok, error: true, output: 'denied' });
    const r = await new LocalAgent(backend('{"tool":"app","arguments":{"action":"list"}}', '{"answer":"denied"}')).run('test');
    expect(r.error).toBe(true);
  });
  it('forwards inline images only to vision backends', async () => {
    for (const vision of [false, true]) {
      vi.mocked(runTool).mockResolvedValue({ ...ok, attachments: [{ filename: 'x.png', mediaType: 'image/png', content: Buffer.from('png') }] });
      const b = { ...backend('{"tool":"screenshot","arguments":{}}', '{"answer":"seen"}'), vision };
      expect((await new LocalAgent(b, { tools: ['screenshot'] }).run('look')).error).toBe(false);
      const content = b.generate.mock.calls[1]?.[0]?.at(-1)?.content;
      expect(Array.isArray(content)).toBe(vision);
    }
  });
  it('supports schema discovery and tool subsets', async () => {
    const b = backend('{"describe":"app"}', '{"tool":"app","arguments":{"action":"list"}}', '{"answer":"seen"}');
    const a = new LocalAgent(b, { tools: ['app'] });
    expect((await a.run('list')).error).toBe(false);
    expect([...a.allowed.keys()]).toEqual(['app']);
    expect(runTool).toHaveBeenCalledTimes(1);
  });
  it('accepts JSON tool-call envelopes, never code', () => {
    expect(parseCommand('<tool_call>{"name":"app","arguments":{"action":"list"}}</tool_call>').tool).toBe('app');
    expect(() => parseCommand('app(action="list")')).toThrow();
  });
});

describe('local endpoint boundary', () => {
  it('rejects remote URLs and credentials', () => {
    for (const url of ['https://example.com/v1', 'http://127.0.0.1@evil.example/v1', 'file:///tmp/a', 'http://localhost/v1?x=1']) {
      expect(() => new LocalHTTPBackend('test', url)).toThrow();
    }
  });
  it('uses loopback, no redirects, and native structured calls', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ choices: [{ message: { tool_calls: [{ function: { name: 'app', arguments: '{"action":"list"}' } }] } }] })));
    try {
      const response = await new LocalHTTPBackend('test').generate([{ role: 'user', content: 'test' }]);
      expect(JSON.parse(response)).toEqual({ tool: 'app', arguments: { action: 'list' } });
      expect(fetchMock.mock.calls[0][1]?.redirect).toBe('error');
    } finally { fetchMock.mockRestore(); }
  });
});
