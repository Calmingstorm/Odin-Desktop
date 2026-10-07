import { EventEmitter } from 'node:events'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { anonymousReleaseTransport, RELEASES_API, ReleaseNoticeService } from '../src/main/release-notice'
import { installKdeLogoutHook, startSessionMonitor } from '../src/main/session-logout'

const boundary = vi.hoisted(() => ({ request: vi.fn(), spawn: vi.fn() }))
vi.mock('node:https', () => ({ request: boundary.request }))
vi.mock('node:child_process', () => ({ spawn: boundary.spawn }))
let response: any, request: any
beforeEach(() => {
  vi.clearAllMocks(); vi.useFakeTimers();
  response = Object.assign(new EventEmitter(), { statusCode: 200, headers: { 'x-ratelimit-remaining': '50', link: '<next>; rel="next"' } });
  request = Object.assign(new EventEmitter(), { end: vi.fn(), destroy: vi.fn((error: Error) => { request.emit('error', error); request.emit('close') }) });
  boundary.request.mockImplementation((_url: string, _opts: any, callback: any) => { callback(response); return request });
})
afterEach(() => { vi.useRealTimers() })
describe('anonymous HTTPS transport with no socket or credential access', () => {
  it('requests fixed metadata anonymously, assembles exact chunks and clears its deadline on close', async () => {
    const pending = anonymousReleaseTransport();
    expect(boundary.request).toHaveBeenCalledWith(RELEASES_API, {
      method: 'GET', agent: false, headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Odin-Desktop-release-notice', 'X-GitHub-Api-Version': '2022-11-28' }
    }, expect.any(Function));
    expect(request.end).toHaveBeenCalledOnce();
    response.emit('data', Buffer.from('[{"tag":')); response.emit('data', Buffer.from('"v1.0.0"}]')); response.emit('end'); request.emit('close');
    expect(await pending).toEqual({ status: 200, body: '[{"tag":"v1.0.0"}]', remaining: '50', link: '<next>; rel="next"' });
    await vi.advanceTimersByTimeAsync(10000); expect(request.destroy).not.toHaveBeenCalled();
  })
  it('handles missing status and non-string pagination without inventing metadata', async () => {
    response.statusCode = undefined; response.headers = { link: ['bad'] };
    const pending = anonymousReleaseTransport(); response.emit('end'); request.emit('close');
    expect(await pending).toEqual({ status: 0, body: '', remaining: undefined, link: undefined });
  })
  it.each(['error', 'aborted'])('preserves ordinary response %s failures as offline', async kind => {
    const pending = new ReleaseNoticeService('1.0.0', vi.fn()).check();
    response.emit(kind, new Error('response failed')); request.emit('close');
    expect(await pending).toEqual({ state: 'offline', currentVersion: '1.0.0' });
  })
  it.each(['request', 'error', 'aborted'])('classifies oversized metadata via %s as malformed, never no-release', async kind => {
    // Some runtimes report an aborted/error response after destroy rather than
    // a request error. Exercise all three documented terminal signals.
    request.destroy.mockImplementation((error: Error) => {
      if (kind === 'request') request.emit('error', error);
      else response.emit(kind, new Error('socket closed'));
      request.emit('close');
    });
    const pending = new ReleaseNoticeService('1.0.0', vi.fn()).check();
    response.emit('data', Buffer.alloc(1024 * 1024 + 1));
    expect(await pending).toEqual({ state: 'malformed', currentVersion: '1.0.0' });
    expect(request.destroy).toHaveBeenCalledWith(expect.objectContaining({ message: 'metadata too large' }));
  })
  it('terminates a stalled metadata request at its bounded deadline', async () => {
    const pending = new ReleaseNoticeService('1.0.0', vi.fn()).check();
    await vi.advanceTimersByTimeAsync(10000);
    expect(await pending).toEqual({ state: 'offline', currentVersion: '1.0.0' });
    expect(request.destroy).toHaveBeenCalledWith(expect.objectContaining({ message: 'metadata deadline' }));
  })
})
describe('session monitor on inert pipes, never the active session', () => {
  const launch = { command: '/mock/python', args: ['-I', '-m', 'src'], env: { DBUS_SESSION_BUS_ADDRESS: 'mock-bus' } };
  it('preserves runtime/env, detects fragmented session end once and closes only its owned stdin', () => {
    const child = Object.assign(new EventEmitter(), { stdin: Object.assign(new EventEmitter(), { end: vi.fn() }), stdout: new EventEmitter() });
    boundary.spawn.mockReturnValue(child); const end = vi.fn();
    const monitor = startSessionMonitor(launch, end)!;
    expect(boundary.spawn).toHaveBeenCalledWith('/mock/python', ['-I', '-m', 'src.desktop.session_end'], { env: launch.env, stdio: ['pipe', 'pipe', 'ignore'] });
    child.emit('error', new Error('optional monitor')); child.stdin.emit('error', new Error('optional pipe'));
    child.stdout.emit('data', Buffer.from('noise\nsession-')); expect(end).not.toHaveBeenCalled();
    child.stdout.emit('data', Buffer.from('ending\n')); child.stdout.emit('data', Buffer.from('session-ending\n'));
    expect(end).toHaveBeenCalledOnce(); monitor.close(); expect(child.stdin.end).toHaveBeenCalledOnce();
  })
  it('requires the selected core module and bus, and fails open if spawn throws', () => {
    expect(startSessionMonitor({ ...launch, args: ['fixture.py'] }, vi.fn())).toBeNull();
    expect(startSessionMonitor({ ...launch, env: {} }, vi.fn())).toBeNull(); expect(boundary.spawn).not.toHaveBeenCalled();
    boundary.spawn.mockImplementation(() => { throw new Error('spawn unavailable') });
    expect(startSessionMonitor(launch, vi.fn())).toBeNull();
  })
  it('refuses invalid logout ownership without creating a hook in a disposable directory', () => {
    const root = mkdtempSync(join(tmpdir(), 'odin-b3-logout-'));
    try {
      expect(installKdeLogoutHook([], { XDG_CONFIG_HOME: root, XDG_CURRENT_DESKTOP: 'KDE' }, 123)).toBeNull();
    } finally { rmSync(root, { recursive: true, force: true }) }
  })
})
