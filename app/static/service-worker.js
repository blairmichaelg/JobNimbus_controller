/**
 * Wickham Roofing Field App — Offline-First Service Worker v2
 *
 * Strategy:
 * - App shell (HTML, CSS, manifest): Cache-first. Served instantly offline.
 * - API POST /api/field/leads: Intercepted. Stored in IndexedDB queue.
 *   Flushed via Background Sync when connection restores.
 * - All other API calls: Network-first with silent failure fallback.
 */

const CACHE_NAME = 'field-app-shell-v2';
const SYNC_TAG = 'field-lead-sync';
const IDB_NAME = 'wickham-field-queue';
const IDB_STORE = 'pending-submissions';

const APP_SHELL = [
    '/field',
    '/static/manifest.json',
    'https://cdn.tailwindcss.com',
];

// ── Install: cache app shell ────────────────────────────────────────────
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL))
    );
    self.skipWaiting();
});

// ── Activate: purge old caches ──────────────────────────────────────────
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            )
        )
    );
    self.clients.claim();
});

// ── IndexedDB helpers ───────────────────────────────────────────────────
function openDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(IDB_NAME, 1);
        req.onupgradeneeded = e => {
            e.target.result.createObjectStore(
                IDB_STORE, { keyPath: 'id', autoIncrement: true }
            );
        };
        req.onsuccess = e => resolve(e.target.result);
        req.onerror = e => reject(e.target.error);
    });
}

async function queueRequest(requestData) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(IDB_STORE, 'readwrite');
        tx.objectStore(IDB_STORE).add({
            url: requestData.url,
            method: requestData.method,
            headers: requestData.headers,
            body: requestData.body,
            queuedAt: Date.now(),
        });
        tx.oncomplete = () => resolve();
        tx.onerror = e => reject(e.target.error);
    });
}

async function flushQueue() {
    const db = await openDB();
    const records = await new Promise((resolve, reject) => {
        const tx = db.transaction(IDB_STORE, 'readonly');
        const req = tx.objectStore(IDB_STORE).getAll();
        req.onsuccess = e => resolve(e.target.result);
        req.onerror = e => reject(e.target.error);
    });

    for (const record of records) {
        try {
            const res = await fetch(record.url, {
                method: record.method,
                headers: record.headers,
                body: record.body,
            });
            if (res.ok) {
                // Delete only on confirmed server acceptance
                const tx = db.transaction(IDB_STORE, 'readwrite');
                tx.objectStore(IDB_STORE).delete(record.id);
                await new Promise(r => { tx.oncomplete = r; });
            }
        } catch (e) {
            // Network still down — leave record in queue for next sync
            console.warn('[SW] Flush failed for record', record.id, e);
        }
    }
}

// ── Background Sync ─────────────────────────────────────────────────────
self.addEventListener('sync', (event) => {
    if (event.tag === SYNC_TAG) {
        event.waitUntil(flushQueue());
    }
});

// ── Fetch Interception ──────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // 1. App shell: cache-first
    if (APP_SHELL.includes(url.pathname) || url.pathname === '/field') {
        event.respondWith(
            caches.match(request).then(cached => cached || fetch(request))
        );
        return;
    }

    // 2. Lead submission POST: queue offline, sync when online
    if (url.pathname === '/api/field/jobs' && request.method === 'POST') {
        event.respondWith(
            fetch(request.clone()).catch(async () => {
                // Network failed — clone body and queue
                const bodyText = await request.text();
                await queueRequest({
                    url: request.url,
                    method: request.method,
                    headers: Object.fromEntries(request.headers.entries()),
                    body: bodyText,
                });
                // Register background sync for when connection restores
                await self.registration.sync.register(SYNC_TAG);
                // Return synthetic 202 Accepted so field app shows
                // "Saved offline — will sync when connected"
                return new Response(
                    JSON.stringify({
                        status: 'queued_offline',
                        message: 'Lead saved locally. Will sync when connected.'
                    }),
                    {
                        status: 202,
                        headers: { 'Content-Type': 'application/json' }
                    }
                );
            })
        );
        return;
    }

    // 3. All other requests: network-first, silent fail
    event.respondWith(
        fetch(request).catch(() => {
            return new Response(
                JSON.stringify({ error: 'offline' }),
                {
                    status: 503,
                    headers: { 'Content-Type': 'application/json' }
                }
            );
        })
    );
});
