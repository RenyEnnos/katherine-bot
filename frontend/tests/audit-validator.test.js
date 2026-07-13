import { test } from 'node:test';
import assert from 'node:assert';
import { spawnSync } from 'child_process';
import { validateAudit } from '../scripts/audit-validator.js';

const createReport = (vulns) => JSON.stringify({
  metadata: {
    vulnerabilities: {
      info: 0,
      low: 0,
      moderate: 0,
      high: 0,
      critical: 0,
      total: 0,
      ...vulns
    }
  }
});

test('relatório limpo com exit code 0', () => {
  const report = createReport({});
  const result = validateAudit(report, 0);
  assert.strictEqual(result.total, 0);
});

test('relatório apenas com baixa/moderada e exit code 1', () => {
  const report = createReport({ low: 2, moderate: 3, total: 5 });
  const result = validateAudit(report, 1);
  assert.strictEqual(result.total, 5);
});

test('vulnerabilidade alta', () => {
  const report = createReport({ high: 1, total: 1 });
  assert.throws(() => validateAudit(report, 1), (err) => {
    return err.code === 6 && err.message.includes('SECURITY_POLICY_VIOLATION');
  });
});

test('vulnerabilidade crítica', () => {
  const report = createReport({ critical: 1, total: 1 });
  assert.throws(() => validateAudit(report, 1), (err) => {
    return err.code === 6 && err.message.includes('SECURITY_POLICY_VIOLATION');
  });
});

test('exit code operacional inesperado', () => {
  const report = createReport({});
  assert.throws(() => validateAudit(report, 2), (err) => {
    return err.code === 4 && err.message.includes('OPERATIONAL_ERROR');
  });
});

test('arquivo ausente', () => {
  const result = spawnSync('node', ['scripts/audit-validator.js', 'non_existent_file.json', '0'], { encoding: 'utf8' });
  assert.strictEqual(result.status, 2);
  assert.match(result.stderr, /OPERATIONAL_ERROR: Audit report file is missing at:/);
});

test('JSON inválido', () => {
  assert.throws(() => validateAudit('invalid json text', 0), (err) => {
    return err.code === 3 && err.message.includes('INVALID_STRUCTURE');
  });
});

test('relatório não é um objeto (null)', () => {
  assert.throws(() => validateAudit('null', 0), (err) => {
    return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
  });
});

test('.metadata ausente', () => {
  const report = JSON.stringify({});
  assert.throws(() => validateAudit(report, 0), (err) => {
    return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
  });
});

test('.metadata.vulnerabilities ausente', () => {
  const report = JSON.stringify({ metadata: {} });
  assert.throws(() => validateAudit(report, 0), (err) => {
    return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
  });
});

test('objeto de vulnerabilidades vazio', () => {
  const report = JSON.stringify({ metadata: { vulnerabilities: {} } });
  assert.throws(() => validateAudit(report, 0), (err) => {
    return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
  });
});

test('uma contagem ausente', () => {
  const report = JSON.stringify({
    metadata: {
      vulnerabilities: {
        info: 0,
        low: 0,
        moderate: 0,
        high: 0,
        total: 0
        // critical missing
      }
    }
  });
  assert.throws(() => validateAudit(report, 0), (err) => {
    return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
  });
});

test('contagem null, string, negativa ou fracionária', () => {
  const cases = [
    { info: null, total: 0 },
    { info: '2', total: 2 },
    { info: -1, total: -1 },
    { info: 1.5, total: 1.5 }
  ];
  for (const c of cases) {
    const report = JSON.stringify({ metadata: { vulnerabilities: { low: 0, moderate: 0, high: 0, critical: 0, total: 0, ...c } } });
    assert.throws(() => validateAudit(report, 0), (err) => {
      return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
    });
  }
});

test('total inconsistente', () => {
  const report = createReport({ low: 1, total: 5 });
  assert.throws(() => validateAudit(report, 1), (err) => {
    return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
  });
});
