import test from 'node:test';
import assert from 'node:assert';
import { validateAudit } from './audit-validator.js';

test('validateAudit - success cases', () => {
  // Case 1: All severities are 0, exit code 0
  const validReport1 = JSON.stringify({
    metadata: {
      vulnerabilities: {
        info: 0,
        low: 0,
        moderate: 0,
        high: 0,
        critical: 0,
        total: 0
      }
    }
  });
  const res1 = validateAudit(validReport1, 0);
  assert.deepStrictEqual(res1, {
    info: 0,
    low: 0,
    moderate: 0,
    high: 0,
    critical: 0,
    total: 0
  });

  // Case 2: Some low/moderate vulnerabilities, exit code 1 (normal npm audit failure but under threshold)
  const validReport2 = JSON.stringify({
    metadata: {
      vulnerabilities: {
        info: 2,
        low: 5,
        moderate: 1,
        high: 0,
        critical: 0,
        total: 8
      }
    }
  });
  const res2 = validateAudit(validReport2, '1'); // test string exit code
  assert.deepStrictEqual(res2, {
    info: 2,
    low: 5,
    moderate: 1,
    high: 0,
    critical: 0,
    total: 8
  });
});

test('validateAudit - invalid exit code', () => {
  const report = JSON.stringify({
    metadata: {
      vulnerabilities: {
        info: 0, low: 0, moderate: 0, high: 0, critical: 0, total: 0
      }
    }
  });

  // exit code not 0 or 1 (e.g. 2, or some other code indicating operational failure)
  assert.throws(() => {
    validateAudit(report, 2);
  }, (err) => {
    return err.code === 4 && err.message.includes('OPERATIONAL_ERROR: npm audit exited with unexpected exit code');
  });

  assert.throws(() => {
    validateAudit(report, 'unexpected');
  }, (err) => {
    return err.code === 4 && err.message.includes('OPERATIONAL_ERROR');
  });
});

test('validateAudit - invalid JSON', () => {
  assert.throws(() => {
    validateAudit('{ invalid json }', 0);
  }, (err) => {
    return err.code === 3 && err.message.includes('INVALID_STRUCTURE: Audit report contains invalid JSON');
  });
});

test('validateAudit - invalid structures', () => {
  // Not an object
  assert.throws(() => {
    validateAudit('null', 0);
  }, (err) => err.code === 5 && err.message.includes('Audit report is not an object'));

  // Missing metadata
  assert.throws(() => {
    validateAudit(JSON.stringify({}), 0);
  }, (err) => err.code === 5 && err.message.includes('.metadata is missing'));

  // Missing vulnerabilities
  assert.throws(() => {
    validateAudit(JSON.stringify({ metadata: {} }), 0);
  }, (err) => err.code === 5 && err.message.includes('.metadata.vulnerabilities is missing'));

  // Missing a severity key
  assert.throws(() => {
    validateAudit(JSON.stringify({
      metadata: {
        vulnerabilities: {
          info: 0, low: 0, moderate: 0, high: 0, total: 0
          // critical missing
        }
      }
    }), 0);
  }, (err) => err.code === 5 && err.message.includes("Vulnerability count for 'critical' is missing"));

  // Invalid value (non-integer)
  assert.throws(() => {
    validateAudit(JSON.stringify({
      metadata: {
        vulnerabilities: {
          info: 0, low: 0, moderate: 'none', high: 0, critical: 0, total: 0
        }
      }
    }), 0);
  }, (err) => err.code === 5 && err.message.includes("Vulnerability count for 'moderate' is invalid"));

  // Sum mismatch
  assert.throws(() => {
    validateAudit(JSON.stringify({
      metadata: {
        vulnerabilities: {
          info: 1, low: 2, moderate: 0, high: 0, critical: 0, total: 10
        }
      }
    }), 0);
  }, (err) => err.code === 5 && err.message.includes('Total count (10) does not match sum of severities (3)'));
});

test('validateAudit - security policy violations', () => {
  // High vulnerabilities
  assert.throws(() => {
    validateAudit(JSON.stringify({
      metadata: {
        vulnerabilities: {
          info: 0, low: 0, moderate: 0, high: 1, critical: 0, total: 1
        }
      }
    }), 1);
  }, (err) => err.code === 6 && err.message.includes('SECURITY_POLICY_VIOLATION: Found 1 high and 0 critical vulnerabilities'));

  // Critical vulnerabilities
  assert.throws(() => {
    validateAudit(JSON.stringify({
      metadata: {
        vulnerabilities: {
          info: 0, low: 0, moderate: 0, high: 0, critical: 2, total: 2
        }
      }
    }), 1);
  }, (err) => err.code === 6 && err.message.includes('SECURITY_POLICY_VIOLATION: Found 0 high and 2 critical vulnerabilities'));
});
