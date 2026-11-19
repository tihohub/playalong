import { defineConfig, type Plugin } from 'vite';
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const BASE = '/playalong/';
const VERSION = new Date().toISOString().slice(0, 16).replace('T', ' ');

/** Erzeugt nach dem Build dist/sw.js mit der Liste aller Dateien (für den Offline-Betrieb). */
function serviceWorker(): Plugin {
  let outDir = 'dist';
  return {
    name: 'playalong-sw',
    apply: 'build',
    configResolved(c) {
      outDir = c.build.outDir;
    },
    closeBundle() {
      const files: string[] = [];
      const hash = createHash('sha256');
      const walk = (dir: string) => {
        for (const f of readdirSync(dir).sort()) {
          const p = join(dir, f);
          if (statSync(p).isDirectory()) walk(p);
          else if (f !== 'sw.js' && !f.endsWith('.map')) {
            files.push(relative(outDir, p).split('\\').join('/'));
            hash.update(f).update(readFileSync(p));
          }
        }
      };
      walk(outDir);
      const tpl = readFileSync(new URL('./sw-template.js', import.meta.url), 'utf8');
      const sw = tpl
        .replace('__CACHE__', `playalong-${hash.digest('hex').slice(0, 12)}`)
        .replace('__BASE__', BASE)
        .replace('__FILES__', JSON.stringify(['', ...files.filter((f) => f !== 'index.html')]));
      writeFileSync(join(outDir, 'sw.js'), sw);
    },
  };
}

export default defineConfig({
  base: BASE,
  define: { __APP_VERSION__: JSON.stringify(VERSION) },
  build: { target: 'safari15', chunkSizeWarningLimit: 3000 },
  plugins: [serviceWorker()],
});
