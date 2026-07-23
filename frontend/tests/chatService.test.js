/* global process */
process.env.NODE_ENV = 'test';
import { test, mock } from 'node:test';
import assert from 'node:assert';

// Mock axios before importing the module under test
const mockPost = mock.fn();
mock.method(await import('axios'), 'default', {
    create: () => ({
        post: mockPost,
        interceptors: {
            request: { handlers: [] },
        },
    }),
});

const { sendMessage, ChatError, classifyHttpError, createChatError } = await import('../src/features/chat/services/chatService.js');

// ─── classifyHttpError ───────────────────────────────────────────────────────

test('classifyHttpError: 504 is timeout', () => {
    assert.strictEqual(classifyHttpError(504), 'timeout');
});

test('classifyHttpError: 0 is timeout', () => {
    assert.strictEqual(classifyHttpError(0), 'timeout');
});

test('classifyHttpError: 429 is rate_limited', () => {
    assert.strictEqual(classifyHttpError(429), 'rate_limited');
});

test('classifyHttpError: 503 is service_unavailable', () => {
    assert.strictEqual(classifyHttpError(503), 'service_unavailable');
});

test('classifyHttpError: 422 is validation', () => {
    assert.strictEqual(classifyHttpError(422), 'validation');
});

test('classifyHttpError: 500 is unknown', () => {
    assert.strictEqual(classifyHttpError(500), 'unknown');
});

test('classifyHttpError: 418 is unknown', () => {
    assert.strictEqual(classifyHttpError(418), 'unknown');
});

// ─── createChatError ────────────────────────────────────────────────────────

function makeAxiosError(code, status, hasResponse = true) {
    const err = new Error('fake');
    err.code = code || '';
    err.response = hasResponse ? { status: status || 500 } : undefined;
    return err;
}

test('createChatError: ECONNABORTED is timeout', () => {
    const err = makeAxiosError('ECONNABORTED');
    const chatErr = createChatError(err);
    assert(chatErr instanceof ChatError);
    assert.strictEqual(chatErr.type, 'timeout');
});

test('createChatError: ERR_CANCELED is timeout', () => {
    const err = makeAxiosError('ERR_CANCELED');
    const chatErr = createChatError(err);
    assert.strictEqual(chatErr.type, 'timeout');
});

test('createChatError: no response is timeout', () => {
    const err = makeAxiosError('', 0, false);
    const chatErr = createChatError(err);
    assert.strictEqual(chatErr.type, 'timeout');
});

test('createChatError: HTTP 429 is rate_limited', () => {
    const err = makeAxiosError('', 429);
    const chatErr = createChatError(err);
    assert.strictEqual(chatErr.type, 'rate_limited');
});

test('createChatError: HTTP 503 is service_unavailable', () => {
    const err = makeAxiosError('', 503);
    const chatErr = createChatError(err);
    assert.strictEqual(chatErr.type, 'service_unavailable');
});

test('createChatError: HTTP 422 is validation', () => {
    const err = makeAxiosError('', 422);
    const chatErr = createChatError(err);
    assert.strictEqual(chatErr.type, 'validation');
});

test('createChatError: unknown error produces generic message', () => {
    const err = makeAxiosError('', 500);
    const chatErr = createChatError(err);
    assert.strictEqual(chatErr.type, 'unknown');
    assert.ok(chatErr.message.includes('Erro'));
});

test('createChatError: raw axios object not exposed in message', () => {
    const err = makeAxiosError('', 500);
    const chatErr = createChatError(err);
    // Ensure no config, headers, or token leaked into message
    assert.ok(!chatErr.message.includes('Bearer'));
    assert.ok(!chatErr.message.includes('Authorization'));
    assert.ok(!chatErr.message.includes('config'));
});

// ─── SendMessage with AbortSignal ───────────────────────────────────────────

test('sendMessage passes signal and timeout to axios', async () => {
    mockPost.mock.resetCalls();
    mockPost.mock.mockImplementation(() => Promise.resolve({
        data: { response: 'Hi', emotion_state: null },
    }));

    const controller = new AbortController();
    const result = await sendMessage('Hello', {
        signal: controller.signal,
        timeout: 50000,
    });

    assert.strictEqual(result.response, 'Hi');
    // Verify axios was called with signal
    const callArg = mockPost.mock.calls[0]?.arguments;
    assert.ok(callArg, 'axios.post was called');
    assert.strictEqual(callArg[0], '/chat');
    assert.deepStrictEqual(callArg[1], { message: 'Hello' });
    assert.strictEqual(callArg[2].signal, controller.signal);
    assert.strictEqual(callArg[2].timeout, 50000);
});

test('sendMessage abort rejects with ChatError', async () => {
    mockPost.mock.resetCalls();
    mockPost.mock.mockImplementation(() => new Promise(() => {})); // never resolves

    const controller = new AbortController();
    const promise = sendMessage('Hello', {
        signal: controller.signal,
        timeout: 50000,
    });

    // Abort immediately
    controller.abort();

    try {
        await promise;
        assert.fail('Should have thrown');
    } catch (err) {
        assert(err instanceof ChatError);
        // ERR_CANCELED or ECONNABORTED → timeout
        assert.ok(['timeout', 'unknown'].includes(err.type));
    }
});

test('timer expiration aborts request', async () => {
    mockPost.mock.resetCalls();
    mockPost.mock.mockImplementation(() => new Promise(() => {})); // never resolves

    const controller = new AbortController();
    const promise = sendMessage('Hello', {
        signal: controller.signal,
        timeout: 1, // 1ms → immediate timeout
    });

    try {
        await promise;
        assert.fail('Should have thrown');
    } catch (err) {
        assert(err instanceof ChatError);
    }
});
