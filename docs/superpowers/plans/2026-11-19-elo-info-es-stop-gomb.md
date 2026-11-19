# Élő adás infó, pulzáló Élő gomb, Stop gomb — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Élő Tilos adás alatt a kártya a logó alá kiírja a lejátszó `media_artist` / `media_title` mezőiből az előadót és a címet, az Élő gomb halványan pulzál, aktív lejátszás alatt a Lejátszás gomb Stop gombbal váltódik fel, és egy `show_info` kapcsoló (alapból be) kezeli a fejléc-infót archívra és élőre.

**Architecture:** Minden a Lovelace kártyában (`www/tilos-player-card.js`), backend érintés nélkül. A döntő logika (élő felismerés, szövegformázás, gomb-látványosság, config-feloldás) a fájl tetejénálló, tiszta `function` deklarációkba kerül, amiket a kártya metódusai csak meghívnak — így node `vm` alapú smoke teszttel tesztelhetők browser nélkül. A fejlécnek egy renderelő útvonala marad (`.cover`), a `.cover[data-kind]` CSS-attribútum választja szét az archív és az élő képillesztést.

**Tech Stack:** vanilla JS Lovelace card (shadow DOM, `ha-card`, `ha-form`), `node --test` + `node:vm` smoke tesztek a kártya tiszta függvényeire, `pytest` a Python progress-modulokra, Home Assistant service call (`media_player.media_stop`).

**Spec:** `docs/superpowers/specs/2026-11-19-elo-info-es-stop-gomb-design.md`

## Global Constraints

- Branch: `feat/live-info-and-stop` (a `master`-ről), a korábbi `feat/cover-header-and-resume` mintájára.
- **Nincs Python-változás**: `custom_components/tilos_player/*.py` érintetlen (a spec nem célja). Nincs új dependency, nincs build lépés, a kártya maradjon egyetlen, browserben közvetlenül betöltött JS fájl.
- Nincs `npm` / `package.json`: a JS tesztek only a node beépített moduljaival (`node:test`, `node:vm`, `node:fs`) dolgoznak.
- A kártya tiszta helper-ei a fájl tetején **`function` deklarációk** legyenek (nem `const` nyíl-függvények), különben a `node:vm` smoke teszt nem éri el őket.
- A kártya UI-szövegei magyarul; a fejléc szövegében a határolójel pontosan ` – ` (en dash, szóközökkel), mint az archív `Műsor – Cím (dátum)` formátumban.
- Idegen szöveget `textContent` / `setAttribute` ír, soha `innerHTML`-be nem fűzve (a meglévő minta).
- A kártya config kulcsa `show_info`, alapértelmezett `true`; a régi `show_cover` csak visszafelé kompatibilitásként maradt meg (`config.show_info ?? config.show_cover`), és az editor írásaikor törlődik.
- Az élő felismerés egyetlen forrásból: a céllejátszó `state === "playing"` ÉS a `media_content_id` (kisbetűsítve) tartalmazza a `stream.tilos.hu` szöveget.
- A kártya stílusa változatlan: 2 szóköz behúzás, szűk sorhossz, magyar commentek.
- `manifest.json` verzió: `1.8.0`.

## Review Focus

- A céllejátszó `unknown` / `unavailable` / `off` / `idle`, vagy nincs egyáltalán beállított `media_player`: se live felirat, se pulzálás, a Stop gomb rejtve, a Lejátszás gomb a régi feltételek szerint. → `tests/js/header.test.mjs::élő fejléc: nincs állapot vagy nincs lejátszó → null`, `tests/js/slots.test.mjs::aktív nélkül a stop rejtve marad`.
- Más forrás szól a lejátszón (pl. Spotify, vagy egy másik mp3 URL, amiben nincs `stream.tilos.hu`): a live felirat nem jelenik meg, az archív `tilos_key` ág zavartalanul nyer először. → `::élő fejléc: nem Tilos tartalom → null`.
- Csak az egyik mező van meg (`media_artist` VAGY `media_title`), vagy mindkettő üres/whitespace: egy mezős sor, illetve egyik sincs → sima logó szöveg nélkül. → `::élő szöveg: csak előadó / csak cím / egyik sincs`.
- `media_content_id` eltérő forma (http, `tilos.mp3`, nagybetűk): a kisbetűs részegyezés ezeket is elkapja. → `::élő fejléc: tartalom-id formafüggetlen`.
- Frissítés után egy régi, explicit `show_cover: false`-ot tartalmazó kártya NE kapjon bekapcsolt fejlécet; a `show_info` explicit hamis bármikor felülbírálja a régi kulcsot. → `tests/js/config.test.mjs::show_info: a régi show_cover csak hiányban dönt`.
- Mozgáscsökkentés (`prefers-reduced-motion: reduce`): a pulzálás helyett állandó halvány háttér marad, az ikon piros. Ellenőrzés: Task 3 Step 5 (manuális, devtools).

---

### Task 1: `show_info` config kulcs és editor

**Files:**
- Modify: `custom_components/tilos_player/www/tilos-player-card.js` (`setConfig` ~181–195, `EDITOR_LABELS` ~70, `EDITOR_HELPERS` ~85, `_updateCover()` ~1763, editor `_schema()` ~4156, editor `value-changed` ~4085)
- Create: `tests/js/card-module.mjs`
- Create: `tests/js/config.test.mjs`
- Modify: `README.md` (Bekonfig + minimális YAML)

**Interfaces:**
- Produces (Task 2–4 ezt használja): `this._config.show_info: boolean`; tiszta függvények `resolveShowInfo(config: object): boolean` és `editorConfig(value: object): object`; a `show_cover` olvasása mindenhol megszűnik.

- [ ] **Step 1: Branch és betöltő segéd**

```bash
git checkout -b feat/live-info-and-stop
```

`tests/js/card-module.mjs`: `readFileSync` + `vm.createContext` stubokkal (`customElements: {get: () => undefined, define: () => {}}`, `document: {createElement: () => ({})}`, `window: {}`, `HTMLElement: class {}`), a kártya forrását `vm.runInContext`-tal futtatja, és visszaadja a contextet. A forráshoz `new URL("../../custom_components/tilos_player/www/tilos-player-card.js", import.meta.url)`-lal fér hozzá.

- [ ] **Step 2: Failing test — a config-feloldás**

`tests/js/config.test.mjs` (a `node:test` + `node:assert/strict` párossal, `const card = loadCard();` a fájl tetején):

```js
test("show_info: alapból be, ha nincs se show_info, se show_cover", () => {
  assert.equal(card.resolveShowInfo({}), true);
});

test("show_info: a régi show_cover csak hiányban dönt", () => {
  assert.equal(card.resolveShowInfo({ show_cover: false }), false);
  assert.equal(card.resolveShowInfo({ show_cover: true }), true);
  assert.equal(card.resolveShowInfo({ show_cover: false, show_info: true }), true);
  assert.equal(card.resolveShowInfo({ show_cover: true, show_info: false }), false);
});

test("show_info: az editor törli a régi show_cover kulcsot", () => {
  assert.deepEqual(
    card.editorConfig({ show_cover: false, show_info: false }),
    { show_info: false },
  );
});
```

- [ ] **Step 3: Futtatás, hogy bukjon**

Run: `node --test tests/js`
Expected: FAIL — `card.resolveShowInfo is not a function`.

- [ ] **Step 4: Implementálás**

A kártya fájl tetejére (a `LINK_URL_RE` konstans mellé) a két tiszta függvény:

```js
function resolveShowInfo(config) {
  if (config.show_info !== undefined) {
    return Boolean(config.show_info);
  }
  if (config.show_cover !== undefined) {
    return Boolean(config.show_cover);
  }
  return true;
}

function editorConfig(value) {
  const config = { ...value };
  delete config.show_cover;
  return config;
}
```

`setConfig`-ban a `show_cover: false` alapértelmezés törlése, és a spread **után** `this._config.show_info = resolveShowInfo(config);`. `_updateCover()` a `this._config.show_cover` olvasást `this._config.show_info`-ra cseréli. Az editorban: `EDITOR_LABELS.show_cover` → `show_info: "Adásinfó megjelenítése"`, `EDITOR_HELPERS.show_info` szövege: „Bekapcsolva a kártya tetején az éppen szóló adás infója látszik: archív epizódborító a logó helyett, élő adásnál a logó alatt az előadó és a cím. Kikapcsolva mindig a sima logó marad.”, `_schema()`-ban a `name: "show_info"`, a `value-changed` handler pedig `config: editorConfig(event.detail.value)`-t küld.

- [ ] **Step 5: Tesztek + szintaxis**

Run: `node --test tests/js` → PASS
Run: `node --check custom_components/tilos_player/www/tilos-player-card.js` → nincs kimenet
Run: `grep -n "show_cover" custom_components/tilos_player/www/tilos-player-card.js`
Expected: csak a `resolveShowInfo` visszafelé kompatibilis soraiban maradjon meg.

- [ ] **Step 6: README + commit**

README „Bekonfig” listájában a `show_cover` sor → `show_info` (`Adásinfó megjelenítése` (`show_info`): opcionális, **alapból `true`**), a minimális YAML példában `show_info: true` sor.

```bash
git add custom_components/tilos_player/www/tilos-player-card.js tests/js README.md
git commit -m "feat: show_info kapcsoló az adásinfóhoz (alapból be)"
```

---

### Task 2: Élő adás fejléc (logó + előadó – cím)

**Files:**
- Modify: `custom_components/tilos_player/www/tilos-player-card.js` (konstansok ~40, `_playingInfo()` ~1696, `_updateCover()` ~1753, CSS `.cover-*` ~295–330)
- Create: `tests/js/header.test.mjs`

**Interfaces:**
- Consumes (Task 1): `this._config.show_info`, `tests/js/card-module.mjs::loadCard()`.
- Produces (Task 3 ezt használja): a `const LIVE_STREAM_HOST = "stream.tilos.hu";` konstans, a `function liveHeaderInfo(state, logoUrl): {image, text} | null` és a kártya `_liveRadioState(): object | null` (a céllejátszó state-je, ha élő Tilos adás szól; különben `null`) metódus.

- [ ] **Step 1: Failing test — élő fejléc és szöveg**

`tests/js/header.test.mjs`:

```js
const LOGO = "/api/brands/integration/tilos_player/logo.png";

test("élő fejléc: playing + stream.tilos.hu → logó és szöveg", () => {
  assert.deepEqual(
    card.liveHeaderInfo(
      {
        state: "playing",
        attributes: {
          media_content_id: "https://stream.tilos.hu/tilos",
          media_artist: "Kowalsky",
          media_title: "Somewhere",
        },
      },
      LOGO,
    ),
    { image: LOGO, text: "Kowalsky – Somewhere" },
  );
});

test("élő fejléc: nem playing → null", () => {
  assert.equal(card.liveHeaderInfo({ state: "paused", attributes: {
    media_content_id: "https://stream.tilos.hu/tilos",
    media_title: "x",
  } }, LOGO), null);
});

test("élő fejléc: nem Tilos tartalom → null", () => {
  assert.equal(card.liveHeaderInfo({ state: "playing", attributes: {
    media_content_id: "https://example.com/stream.mp3",
    media_artist: "A",
    media_title: "B",
  } }, LOGO), null);
});

test("élő fejléc: nincs állapot vagy nincs lejátszó → null", () => {
  assert.equal(card.liveHeaderInfo(null, LOGO), null);
  assert.equal(card.liveHeaderInfo({ state: "playing", attributes: {} }, LOGO), null);
});

test("élő fejléc: tartalom-id formafüggetlen", () => {
  const ok = card.liveHeaderInfo({ state: "playing", attributes: {
    media_content_id: "http://Stream.Tilos.hu/tilos.mp3?token=1",
    media_title: "Cím",
  } }, LOGO);
  assert.equal(ok.text, "Cím");
});

test("élő szöveg: csak előadó / csak cím / egyik sincs", () => {
  assert.equal(card.liveHeaderText("Kowalsky", ""), "Kowalsky");
  assert.equal(card.liveHeaderText("", "Somewhere"), "Somewhere");
  assert.equal(card.liveHeaderText("  ", null), "");
});

test("élő fejléc: nincs szöveg → null (marad a sima logó)", () => {
  assert.equal(card.liveHeaderInfo({ state: "playing", attributes: {
    media_content_id: "https://stream.tilos.hu/tilos",
  } }, LOGO), null);
});
```

- [ ] **Step 2: Futtatás, hogy bukjon**

Run: `node --test tests/js/header.test.mjs`
Expected: FAIL — `card.liveHeaderInfo is not a function`.

- [ ] **Step 3: Implementálás: tiszta függvények + `_liveRadioState()`**

Fájl tetejére a `LIVE_STREAM_HOST` konstans, és a két `function`: `liveHeaderText(artist, title)` (a nem-üres szöveges feleket ` – `-sel fűzi össze, a hiányzókat kihagyja) és `liveHeaderInfo(state, logoUrl)` — a teszt feltételei szerint: `state.state === "playing"`, a `media_content_id` kisbetűsítve tartalmazza `LIVE_STREAM_HOST`-ot, a szöveg `liveHeaderText(...)`-ből, üres szöveg → `null`, egyébként `{ image: logoUrl, text }`.

A kártyában:

```js
_liveRadioState() {
  const target = this._targetPlayer();
  const state = target ? this._hass.states[target] : null;
  const contentId = String(
    (state && state.attributes ? state.attributes.media_content_id : "") || "",
  ).toLowerCase();
  return state && state.state === "playing" &&
    contentId.includes(LIVE_STREAM_HOST)
    ? state
    : null;
}

_liveHeaderInfo() {
  return liveHeaderInfo(this._liveRadioState(), this._config.logo);
}

_headerInfo() {
  if (!this._config.show_info) {
    return null;
  }
  const archive = this._playingInfo();
  if (archive) {
    return { ...archive, kind: "archive" };
  }
  const live = this._liveHeaderInfo();
  return live ? { ...live, kind: "live" } : null;
}
```

- [ ] **Step 4: Implementálás: `_updateCover()` egységes útvonala**

`_updateCover()` a `_headerInfo()`-t hívja (a `show_info`-ellenőrzés már benne van), `logo.hidden = Boolean(info)` — az élő ágon is a `.cover` tartja a képet, így a logó ugyanaz a fájl marad —, `cover.hidden = !info`, és `cover.setAttribute("data-kind", info ? info.kind : "")`. A `kind === "live"` esetén a `.cover-image` **ne vágja** a logót:

```css
.cover[data-kind="live"] .cover-image {
  max-height: none;
  object-fit: contain;
}
```

- [ ] **Step 5: Tesztek + szintaxis**

Run: `node --test tests/js` → PASS
Run: `node --check custom_components/tilos_player/www/tilos-player-card.js` → nincs kimenet

- [ ] **Step 6: Manuális ellenőrzés a HA-ban**

Kártyán Élő gomb → a logó **változatlan képként** marad fent, alatta `előadó – cím`; a stream közben (új szám) a szöveg frissül; a lejátszó szüneteltetésére a szöveg eltűnik és a sima logó marad szöveg nélkül. Várható kudarc, ha a lejátszó nem adja tovább a stream metaadatát: akkor a logó szöveg nélkül marad — ekkor a `media_artist` / `media_title` tartalmát a Dev Tools → Entitások képernyőn kell ellenőrizni.

- [ ] **Step 7: README + commit**

README Fícsörök listájába: „Élő adás alatt a logó alatt az éppen szóló előadó és cím (a lejátszó `media_artist` / `media_title` mezőiből)”.

```bash
git add custom_components/tilos_player/www/tilos-player-card.js tests/js README.md
git commit -m "feat: élő adás előadó és cím a kártya fejlécében"
```

---

### Task 3: Halványan pulzáló Élő gomb

**Files:**
- Modify: `custom_components/tilos_player/www/tilos-player-card.js` (CSS `.action-button.live` ~948, `_updateActionButtons()` ~1630)

**Interfaces:**
- Consumes (Task 2): `_liveRadioState()`.
- Produces: a `.action-button.live.live-active` CSS osztály, amit Task 4 nem használ.

- [ ] **Step 1: CSS**

A `.action-button.live` mellé:

```css
.action-button.live.live-active {
  animation: tilos-live-pulse 1.8s ease-in-out infinite;
}

@keyframes tilos-live-pulse {
  0%,
  100% {
    background-color: rgba(219, 68, 55, 0.10);
  }
  50% {
    background-color: rgba(219, 68, 55, 0.26);
  }
}

@media (prefers-reduced-motion: reduce) {
  .action-button.live.live-active {
    animation: none;
    background-color: rgba(219, 68, 55, 0.16);
  }
}
```

- [ ] **Step 2: Osztály váltása**

`_updateActionButtons()`-ban a live gomb lekérése (`container.querySelector('.action-button[data-action="live"]')`) és `classList.toggle("live-active", this._liveRadioState() !== null)`.

- [ ] **Step 3: Szintaxis + regresszió**

Run: `node --test tests/js` → PASS
Run: `node --check custom_components/tilos_player/www/tilos-player-card.js` → nincs kimenet

- [ ] **Step 4: Manuális ellenőrzés**

Élő adás: az Élő gomb halványan, lassan pulzál (a kártya fekete hátterén halvány vöröses háttér, az ikon piros marad); stop/szünet után nyugalomban. Devtools-ban `prefers-reduced-motion` emulation: nincs animáció, állandó halvány háttér.

- [ ] **Step 5: Commit**

```bash
git add custom_components/tilos_player/www/tilos-player-card.js
git commit -m "feat: pulzáló Élő gomb, ha a rádió szól"
```

---

### Task 4: Stop gomb aktív lejátszás alatt

**Files:**
- Modify: `custom_components/tilos_player/www/tilos-player-card.js` (`PLAY_PATH` ~31, gombsor markup ~1210–1300, gomb click handler ~1425, `_update()` disabled ág ~1546, `_updateActionButtons()` ~1630)
- Create: `tests/js/slots.test.mjs`
- Modify: `README.md`, `custom_components/tilos_player/manifest.json`

**Interfaces:**
- Consumes (Task 1–3): `this._config.show_info`, `_liveRadioState()`.
- Produces: a `function slotVisibility(active: boolean, resumable: boolean): {play, restart, resume, stop}` tiszta függvény, a `const STOP_PATH` ikon-útvonal, a kártya `_playerActive(): boolean` és `_stopPlayer(): void` metódusai, `.action-button.stop[data-action="stop"]` gomb.

- [ ] **Step 1: Failing test — a slot-szabály**

`tests/js/slots.test.mjs`:

```js
test("slot: nincs aktív lejátszás, nincs mentett pozíció → csak play", () => {
  assert.deepEqual(
    card.slotVisibility(false, false),
    { play: true, restart: false, resume: false, stop: false },
  );
});

test("slot: mentett pozíció → előről + folytatás", () => {
  assert.deepEqual(
    card.slotVisibility(false, true),
    { play: false, restart: true, resume: true, stop: false },
  );
});

test("slot: aktív lejátszás → stop váltja ki a playt és a párt", () => {
  assert.deepEqual(
    card.slotVisibility(true, false),
    { play: false, restart: false, resume: false, stop: true },
  );
  assert.deepEqual(
    card.slotVisibility(true, true),
    { play: false, restart: false, resume: false, stop: true },
  );
});
```

- [ ] **Step 2: Futtatás, hogy bukjon**

Run: `node --test tests/js/slots.test.mjs`
Expected: FAIL — `card.slotVisibility is not a function`.

- [ ] **Step 3: Implementálás: slot-függvény, `_playerActive()`, `_stopPlayer()`**

`slotVisibility(active, resumable)` a tesztek szerinti négy boolean mezővel. A kártyában:

```js
_playerActive() {
  const target = this._targetPlayer();
  const state = target ? this._hass.states[target] : null;
  return Boolean(state) &&
    (state.state === "playing" || state.state === "buffering");
}

_stopPlayer() {
  const target = this._targetPlayer();
  if (!target) {
    return;
  }
  this._hass.callService(
    "media_player",
    "media_stop",
    { entity_id: target },
  );
}
```

- [ ] **Step 4: Implementálás: gomb + click + láthatóság**

`STOP_PATH` a `PLAY_PATH` mellé (24×24 viewBox, behúzott négyzet): `const STOP_PATH = "M7.5,7.5H16.5V16.5H7.5Z";`. A Lejátszás gomb után a markupban egy `hidden` indulású `<button class="action-button stop" data-action="stop" type="button" aria-label="Leállítás" title="Leállítás">` a `<path d="${STOP_PATH}"/>`-val. A click handlerben az `action === "live"` ág **elé**: `if (action === "stop") { this._stopPlayer(); return; }`.

`_updateActionButtons()`-ban a `const visible = slotVisibility(this._playerActive(), resumable);` és a `play` / `restart` / `resume` / `stop` elemek `.hidden`-ja a négy mező szerint; a `restart` / `resume` `disabled` maradjon a meglévő `this._playDisabled()`, a `stop.disabled = !this._targetPlayer()`. A meglévő `repeat(N,1fr)` újra-számolás változatlanul működik a `hidden` szűrővel. A stop ikon színe a play-é marad (`--primary-text-color`), a piros az Élő gombé.

- [ ] **Step 5: Tesztek + szintaxis + Python regresszió**

Run: `node --test tests/js` → PASS
Run: `node --check custom_components/tilos_player/www/tilos-player-card.js` → nincs kimenet
Run: `.venv/bin/pytest -q` → `35 passed`

- [ ] **Step 6: Manuális ellenőrzés**

(a) Archív epizód lejátszása: a sor `[■ Leállítás] [Élő]`; a Stop-ra nyomva a lejátszó `idle`, a sor visszaáll `[Előről][Folytatás][Élő]`-re (a midway pozíció megmaradt). (b) Élő adás: `[■][Élő pulzál]`, Stop-ra a pulzálás és a felirat is elmúlik. (c) `media_player` nincs beállítva: a Stop rejtve, a Lejátszás letiltva. (d) MA módban: `[Sorba][■][Élő]`.

- [ ] **Step 7: README + verzió + commit**

README Fícsörök: „Aktív lejátszás alatt a Lejátszás gomb **Leállítás** gombbal váltódik fel (`media_player.media_stop`)”. `manifest.json` `version`: `1.8.0`.

```bash
git add custom_components/tilos_player/www/tilos-player-card.js custom_components/tilos_player/manifest.json tests/js README.md
git commit -m "feat: stop gomb aktív lejátszás alatt"
```
