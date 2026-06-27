import { readFileSync } from 'node:fs';

const input = readFileSync(0, 'utf8');
process.stdout.write(input.replace(/\n+$/u, '\n'));
