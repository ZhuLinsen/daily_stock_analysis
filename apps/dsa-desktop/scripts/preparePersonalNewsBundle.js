const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const templatePath = path.join(repoRoot, 'packaging', 'personal-news.env.template');
const defaultPrivatePath = path.join(repoRoot, '.env.personal-news-bundle');
const outputPath = path.join(repoRoot, 'dist', 'desktop-bundle', '.env.initial');

const ALLOWED_KEYS = new Set([
  'PERSONAL_NEWS_BUNDLE',
  'OPENAI_BASE_URL',
  'OPENAI_API_KEY',
  'OPENAI_MODEL',
  'BOCHA_API_KEYS',
  'FEISHU_WEBHOOK_URL',
  'FEISHU_WEBHOOK_SECRET',
  'APP_TIMEZONE',
  'NEWS_PUSH_INTERVAL_HOURS',
  'REFRESH_ON_OPEN',
  'OPEN_REFRESH_COOLDOWN_MINUTES',
  'MAX_AI_ITEMS_PER_RUN',
  'WEBUI_HOST',
]);

function parseEnv(text) {
  const values = new Map();
  String(text || '').split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return;
    const separator = line.indexOf('=');
    if (separator < 1) throw new Error(`Invalid bundle config line ${index + 1}`);
    const key = line.slice(0, separator).trim();
    if (!ALLOWED_KEYS.has(key)) throw new Error(`Unsupported bundle config key: ${key}`);
    values.set(key, line.slice(separator + 1).trim());
  });
  return values;
}

function prepareBundleConfig({ privatePath, destination = outputPath } = {}) {
  const selectedPrivatePath = privatePath || process.env.DSA_BUNDLE_ENV_FILE || defaultPrivatePath;
  const values = parseEnv(fs.readFileSync(templatePath, 'utf-8'));
  const hasPrivateConfig = fs.existsSync(selectedPrivatePath);
  if (hasPrivateConfig) {
    parseEnv(fs.readFileSync(selectedPrivatePath, 'utf-8')).forEach((value, key) => values.set(key, value));
  }
  values.set('PERSONAL_NEWS_BUNDLE', 'true');
  values.set('WEBUI_HOST', '127.0.0.1');

  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(
    destination,
    `${[...values.entries()].map(([key, value]) => `${key}=${value}`).join('\n')}\n`,
    { encoding: 'utf-8', mode: 0o600 },
  );
  return { destination, hasPrivateConfig, keys: [...values.keys()] };
}

if (require.main === module) {
  const result = prepareBundleConfig();
  console.log(`Prepared personal-news initial config (${result.keys.length} keys, private=${result.hasPrivateConfig}).`);
}

module.exports = { ALLOWED_KEYS, parseEnv, prepareBundleConfig };
