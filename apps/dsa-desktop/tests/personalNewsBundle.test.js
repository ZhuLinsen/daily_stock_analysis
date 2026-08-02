const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { parseEnv, prepareBundleConfig } = require('../scripts/preparePersonalNewsBundle');

test('bundle config accepts only the personal-news allowlist', () => {
  assert.throws(() => parseEnv('UNEXPECTED_SECRET=value\n'), /Unsupported bundle config key/);
});

test('private config overrides template without printing or changing unrelated defaults', (t) => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-personal-news-bundle-'));
  t.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));
  const privatePath = path.join(tempDir, 'private.env');
  const destination = path.join(tempDir, '.env.initial');
  fs.writeFileSync(
    privatePath,
    'OPENAI_API_KEY=test-key\nBOCHA_API_KEYS=bocha-key\nFEISHU_WEBHOOK_URL=https://example.test/hook\n',
    'utf-8',
  );

  const result = prepareBundleConfig({ privatePath, destination });
  const values = parseEnv(fs.readFileSync(destination, 'utf-8'));

  assert.equal(result.hasPrivateConfig, true);
  assert.equal(values.get('OPENAI_API_KEY'), 'test-key');
  assert.equal(values.get('PERSONAL_NEWS_BUNDLE'), 'true');
  assert.equal(values.get('WEBUI_HOST'), '127.0.0.1');
  assert.equal(values.get('APP_TIMEZONE'), 'Asia/Shanghai');
});
