// Generates web/static/css/tailwind.css from the classes used by the core UI.
//
//   npm run build   regenerate the file (commit the result)
//   npm run check   fail when the committed file is out of date
//
// Build-time only: end users never run this, they receive the generated file.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const target = resolve(here, '../../web/static/css/tailwind.css');
const bin = resolve(here, 'node_modules/.bin/tailwindcss');
const check = process.argv.includes('--check');

function build(out) {
  execFileSync(bin, [
    '-c', resolve(here, 'tailwind.config.cjs'),
    '-i', resolve(here, 'input.css'),
    '-o', out,
    '--minify',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
}

if (check) {
  const dir = mkdtempSync(join(tmpdir(), 'wb-css-'));
  try {
    const fresh = join(dir, 'tailwind.css');
    build(fresh);
    const same = readFileSync(fresh, 'utf8') === readFileSync(target, 'utf8');
    if (!same) {
      console.error('web/static/css/tailwind.css is out of date. Run: cd tools/css && npm run build');
      process.exit(1);
    }
    console.log('tailwind.css is up to date');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
} else {
  build(target);
  const size = readFileSync(target).length;
  console.log(`wrote web/static/css/tailwind.css (${size} bytes)`);
}
