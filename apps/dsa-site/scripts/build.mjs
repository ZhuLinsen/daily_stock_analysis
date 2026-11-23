process.env.ASTRO_TELEMETRY_DISABLED = '1';

// Invoke Astro's command implementation directly so Workers Builds can use the
// Node runtime it provides without the CLI wrapper rejecting a patch release.
const astroPackage = new URL(import.meta.resolve('astro/package.json'));
const astroRoot = new URL('.', astroPackage);
const { cli } = await import(new URL('dist/cli/index.js', astroRoot));
await cli([process.argv[0], 'astro', 'build', ...process.argv.slice(2)]);
