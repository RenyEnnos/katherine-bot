/* global process */
import fs from 'fs';
import { fileURLToPath } from 'url';

export function validateAudit(fileContent, auditExitCode) {
  const exitCode = parseInt(auditExitCode, 10);
  if (isNaN(exitCode) || (exitCode !== 0 && exitCode !== 1)) {
    throw { message: `OPERATIONAL_ERROR: npm audit exited with unexpected exit code: ${auditExitCode}`, code: 4 };
  }

  let data;
  try {
    data = JSON.parse(fileContent);
  } catch (err) {
    throw { message: `INVALID_STRUCTURE: Audit report contains invalid JSON: ${err.message}`, code: 3 };
  }

  if (!data || typeof data !== 'object') {
    throw { message: 'INVALID_STRUCTURE: Audit report is not an object', code: 5 };
  }

  if (!data.metadata || typeof data.metadata !== 'object' || data.metadata === null) {
    throw { message: 'INVALID_STRUCTURE: .metadata is missing or not an object', code: 5 };
  }

  const vulnerabilities = data.metadata.vulnerabilities;
  if (!vulnerabilities || typeof vulnerabilities !== 'object' || vulnerabilities === null) {
    throw { message: 'INVALID_STRUCTURE: .metadata.vulnerabilities is missing, null, or not an object', code: 5 };
  }

  const severities = ['info', 'low', 'moderate', 'high', 'critical'];
  const allKeys = [...severities, 'total'];

  for (const key of allKeys) {
    if (!(key in vulnerabilities)) {
      throw { message: `INVALID_STRUCTURE: Vulnerability count for '${key}' is missing`, code: 5 };
    }
    const val = vulnerabilities[key];
    if (val === null || typeof val !== 'number' || !Number.isInteger(val) || val < 0) {
      throw { message: `INVALID_STRUCTURE: Vulnerability count for '${key}' is invalid (value: ${val})`, code: 5 };
    }
  }

  const sum = severities.reduce((acc, key) => acc + vulnerabilities[key], 0);
  if (vulnerabilities.total !== sum) {
    throw { message: `INVALID_STRUCTURE: Total count (${vulnerabilities.total}) does not match sum of severities (${sum})`, code: 5 };
  }

  if (vulnerabilities.high > 0 || vulnerabilities.critical > 0) {
    throw { message: `SECURITY_POLICY_VIOLATION: Found ${vulnerabilities.high} high and ${vulnerabilities.critical} critical vulnerabilities`, code: 6 };
  }

  return vulnerabilities;
}

const isMain = process.argv[1] && (
  process.argv[1] === fileURLToPath(import.meta.url) ||
  process.argv[1].endsWith('audit-validator.js')
);

if (isMain) {
  try {
    const filePath = process.argv[2];
    const auditExitCodeStr = process.argv[3];

    if (!filePath || auditExitCodeStr === undefined) {
      console.error('Usage: node audit-validator.js <path_to_audit.json> <audit_exit_code>');
      process.exit(2);
    }

    if (!fs.existsSync(filePath)) {
      console.error(`OPERATIONAL_ERROR: Audit report file is missing at: ${filePath}`);
      process.exit(2);
    }

    const fileContent = fs.readFileSync(filePath, 'utf8');
    validateAudit(fileContent, auditExitCodeStr);

    console.log('Auditoria passou com sucesso!');
    process.exit(0);
  } catch (err) {
    console.error(err.message || err);
    process.exit(err.code || 1);
  }
}
