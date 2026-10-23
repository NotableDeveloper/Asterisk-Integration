import {build} from 'esbuild';
import {createHash} from 'node:crypto';
import {readFile, writeFile} from 'node:fs/promises';

const output = new URL('../stt-server/static/phone.js', import.meta.url);
const page = new URL('../stt-server/static/index.html', import.meta.url);
await build({
  entryPoints: [new URL('src/phone.js', import.meta.url).pathname],
  bundle: true, format: 'esm', minify: true, outfile: output.pathname
});
const version = createHash('sha256').update(await readFile(output)).digest('hex').slice(0, 16);
const html = await readFile(page, 'utf8');
if (!/src="\/static\/phone\.js(?:\?v=[a-f0-9]+)?"/.test(html)) {
  throw new Error('Missing phone bundle script in index.html');
}
await writeFile(page, html.replace(/src="\/static\/phone\.js(?:\?v=[a-f0-9]+)?"/,
  `src="/static/phone.js?v=${version}"`));
