// Build-time assertions against the pinned upstream service, not a vendored fork.
const fs = require('fs');
const path = '/app/server.js';
let source = fs.readFileSync(path, 'utf8');
const launch = 'headless: useVirtualDisplay ? false : !useDesktopWindow,';
const logger = 'function log(level, msg, fields = {}) {';
if (!source.includes(launch) || !source.includes(logger)) {
  throw new Error('Pinned CamoFox hardening contract changed');
}
source = source.replace(launch, 'headless: true,');
// Only static source-code event names and numeric/boolean metrics may be logged.
// In particular: no navigation hints, raw errors, context IDs or request paths.
const events = [...source.matchAll(/\blog\(['"](?:info|warn|error|debug)['"], ['"]([^'"]+)['"]/g)].map(x => x[1]);
const fields = ['status', 'ms', 'attempt', 'maxAttempts', 'port', 'pid', 'activeTabs', 'activeSessions', 'virtualDisplay'];
source = source.replace(logger, logger + '\n' +
  '  const events = new Set(' + JSON.stringify(events) + ');\n' +
  "  msg = events.has(msg) ? msg : 'browser_event';\n" +
  '  const metrics = new Set(' + JSON.stringify(fields) + ');\n' +
  "  fields = Object.fromEntries(Object.entries(fields).filter(([key, value]) => metrics.has(key) && ['number', 'boolean'].includes(typeof value)));\n");
fs.writeFileSync(path, source);
