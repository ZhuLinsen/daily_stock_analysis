process.env.ASTRO_TELEMETRY_DISABLED = '1';
// Invoke Astro's command implementation directly so Workers Builds can use the
// Node runtime it provides without the CLI wrapper rejecting a patch release.
const { cli } = await import('../node_modules/astro/dist/cli/index.js');
await cli([process.argv[0], 'astro', 'build', ...process.argv.slice(2)]);
