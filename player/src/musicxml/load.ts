// Import von Dateien: .playalong (Liedpaket), .mxl (komprimiertes MusicXML), .musicxml/.xml
import { unzipSync, strFromU8 } from 'fflate';
import { readTitle, parseXml } from './prepare';

export interface PackageManifest {
  format?: string;
  version?: number;
  title?: string;
  composer?: string;
  score?: string;
  audio?: string;
  sync?: string;
  soloPart?: string;
  notation?: 'auto' | 'concert' | 'transposed';
  [k: string]: unknown;
}

export interface ImportedSong {
  title: string;
  composer: string;
  xml: string;
  audio?: Blob;
  audioName?: string;
  sync?: unknown;
  manifest?: PackageManifest;
}

function isZip(b: Uint8Array): boolean {
  return b.length > 4 && b[0] === 0x50 && b[1] === 0x4b && b[2] === 0x03 && b[3] === 0x04;
}

function decodeText(b: Uint8Array): string {
  // UTF-16 mit BOM (manche Programme exportieren so)
  if (b[0] === 0xff && b[1] === 0xfe) return new TextDecoder('utf-16le').decode(b);
  if (b[0] === 0xfe && b[1] === 0xff) return new TextDecoder('utf-16be').decode(b);
  return new TextDecoder('utf-8').decode(b);
}

function findEntry(files: Record<string, Uint8Array>, name: string): Uint8Array | undefined {
  if (files[name]) return files[name];
  const lower = name.toLowerCase();
  const k = Object.keys(files).find((f) => f.toLowerCase() === lower || f.toLowerCase().endsWith('/' + lower));
  return k ? files[k] : undefined;
}

function scoreFromMxl(files: Record<string, Uint8Array>): string {
  const container = findEntry(files, 'META-INF/container.xml');
  if (container) {
    const doc = new DOMParser().parseFromString(decodeText(container), 'application/xml');
    const path = doc.querySelector('rootfile')?.getAttribute('full-path');
    if (path) {
      const f = findEntry(files, path);
      if (f) return decodeText(f);
    }
  }
  const k = Object.keys(files).find((f) => /\.(musicxml|xml)$/i.test(f) && !f.startsWith('META-INF'));
  if (!k) throw new Error('In der Datei wurde keine MusicXML-Partitur gefunden.');
  return decodeText(files[k]);
}

function mimeFor(name: string): string {
  if (/\.m4a$|\.aac$/i.test(name)) return 'audio/mp4';
  if (/\.ogg$/i.test(name)) return 'audio/ogg';
  if (/\.wav$/i.test(name)) return 'audio/wav';
  return 'audio/mpeg';
}

export async function importFile(file: File): Promise<ImportedSong> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const baseName = file.name.replace(/\.[^.]+$/, '');

  if (isZip(bytes)) {
    const files = unzipSync(bytes);
    const manifestBytes = findEntry(files, 'manifest.json');
    if (manifestBytes) {
      const manifest = JSON.parse(strFromU8(manifestBytes)) as PackageManifest;
      const scoreName = manifest.score ?? Object.keys(files).find((f) => /\.(musicxml|xml|mxl)$/i.test(f));
      if (!scoreName) throw new Error('Das Liedpaket enthält keine Partitur.');
      const scoreBytes = findEntry(files, scoreName);
      if (!scoreBytes) throw new Error(`Die Partitur „${scoreName}“ fehlt im Liedpaket.`);
      const xml = isZip(scoreBytes) ? scoreFromMxl(unzipSync(scoreBytes)) : decodeText(scoreBytes);
      const meta = readTitle(parseXml(xml));
      const song: ImportedSong = {
        title: manifest.title || meta.title || baseName,
        composer: manifest.composer || meta.composer,
        xml,
        manifest,
      };
      const audioName = manifest.audio ?? Object.keys(files).find((f) => /\.(mp3|m4a|aac|ogg|wav)$/i.test(f));
      if (audioName) {
        const a = findEntry(files, audioName);
        if (a) {
          song.audio = new Blob([a as BlobPart], { type: mimeFor(audioName) });
          song.audioName = audioName;
        }
      }
      const syncName = manifest.sync ?? (findEntry(files, 'sync.json') ? 'sync.json' : undefined);
      if (syncName) {
        const s = findEntry(files, syncName);
        if (s) song.sync = JSON.parse(strFromU8(s));
      }
      return song;
    }
    const xml = scoreFromMxl(files);
    const meta = readTitle(parseXml(xml));
    return { title: meta.title || baseName, composer: meta.composer, xml };
  }

  const xml = decodeText(bytes);
  const meta = readTitle(parseXml(xml));
  return { title: meta.title || baseName, composer: meta.composer, xml };
}
