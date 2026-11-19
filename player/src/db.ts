// Bibliothek in IndexedDB (bleibt auf dem iPad, offline verfügbar)
import type { PackageManifest } from './musicxml/load';

export interface SongSettings {
  tempo?: number;
  showPiano?: boolean;
  zoom?: number;
  loopFrom?: string;
  loopTo?: string;
  soloPart?: string;
  notation?: 'auto' | 'concert' | 'transposed';
  /** eingeblendete Begleitstimmen */
  visibleParts?: string[];
  /** stummgeschaltete Begleitstimmen */
  mutedParts?: string[];
}

export interface Song {
  id: string;
  title: string;
  composer: string;
  xml: string;
  audio?: Blob;
  audioName?: string;
  sync?: unknown;
  manifest?: PackageManifest;
  addedAt: number;
  lastPlayed: number;
  settings: SongSettings;
}

export type SongSummary = Pick<Song, 'id' | 'title' | 'composer' | 'addedAt' | 'lastPlayed'> & { hasAudio: boolean };

const DB_NAME = 'playalong';
const STORE = 'songs';
let dbPromise: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: 'id' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then((db) => new Promise<T>((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const r = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(r.result);
    t.onerror = () => reject(t.error ?? r.error);
    t.onabort = () => reject(t.error ?? new Error('Speichern abgebrochen (Speicher voll?)'));
  }));
}

export async function listSongs(): Promise<SongSummary[]> {
  const all = await tx<Song[]>('readonly', (s) => s.getAll() as IDBRequest<Song[]>);
  return all
    .map((x) => ({ id: x.id, title: x.title, composer: x.composer, addedAt: x.addedAt, lastPlayed: x.lastPlayed, hasAudio: !!x.audio }))
    .sort((a, b) => (b.lastPlayed || b.addedAt) - (a.lastPlayed || a.addedAt));
}

export function getSong(id: string): Promise<Song | undefined> {
  return tx<Song | undefined>('readonly', (s) => s.get(id) as IDBRequest<Song | undefined>);
}

export async function putSong(song: Song): Promise<void> {
  await tx('readwrite', (s) => s.put(song));
}

export async function deleteSong(id: string): Promise<void> {
  await tx('readwrite', (s) => s.delete(id));
}

export async function updateSong(id: string, patch: Partial<Song>): Promise<void> {
  const s = await getSong(id);
  if (!s) return;
  await putSong({ ...s, ...patch, settings: { ...s.settings, ...(patch.settings ?? {}) } });
}

export function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/** Bittet den Browser, die Daten dauerhaft zu behalten (Safari löscht sonst ggf. nach Wochen ohne Nutzung). */
export async function requestPersistence(): Promise<void> {
  try {
    if (navigator.storage?.persist && !(await navigator.storage.persisted())) await navigator.storage.persist();
  } catch {
    /* egal */
  }
}
