# Borító fejléc és folytatható lejátszás — design

Dátum: 2026-11-16
Státusz: jóváhagyásra vár

## Miért

A kártya ma mindig a statikus Tilos-logót mutatja a tetején, és minden
lejátszás a nulláról indul. A felhasználó hosszabb archív adásokat
(műsorokat) hallgat, gyakran több alkalommal, ezért kell:

1. A kártya tetején a **most szóló adás borítója** látszódjon, alatta a
   műsor neve és az epizód címe — a statikus logó helyett.
2. A kártyáról indított epizódok **lejátszási pozíciója** megmaradjon
   (saját tárolóban), a listában ikon jelezze, hol van folytatnivaló, és
   a Lejátszás gomb helyett **Előről / Folytatás** gombpár legyen.

## Célok

- Bekapcsolható (kártya-beállítás) borító-fejléc: borító + egy sor szöveg,
  csak akkor, ha épp Tilos-archív epizód szól a céllejátszón.
- Ha a lejátszás véget ér vagy nem Tilos-epizód szól, a fejléc visszaáll
  a statikus logóra, a szöveg eltűnik.
- Epizód (= archív mp3 kulcs) szintű pozíció mentése 30 másodpercenként,
  a lejátszótól lekérdezve, csak a kártyáról/integrációból indított
  lejátszásra; sima és „mentett későbbre” epizódokra egyaránt.
- A műsor- és az epizód-legördülőben ikon jelzi a folyamatban lévő
  (folytatható) elemet.
- Folytatható epizód kiválasztásakor a Lejátszás gomb helyett
  **Előről** és **Folytatás**; a gombsor 4 gombos lesz (Music Assistant
  módban Sorba + Előről + Folytatás + Élő adás), egyébként 3.
- A folytatás valódi seek: a lejátszó a mentett pozíciótól indul.

## Nem célok

- Élő adás és a „Link lejátszó” mezőből indított tetszőleges mp3
  követése (nincs epizód-kulcsuk, nincs listaelemük).
- Haladássáv / hátralévő idő kijelzése a kártyán; csak az „van
  folytatnivaló” tény és a két gomb.
- Kereszt-eszközös vagy felhős szinkron: a pozíció a Home Assistant
  példányhoz kötődik.
- SQLite vagy külön adatbázis-szerver. A HA `Store` JSON fájl a minta
  (lásd a mentett epizódokat), plusz függőség nélkül.
- Music Assistant sorba állított (még nem játszott) elem seekje; a
  „Folytatás” sorba állításnál nem értelmezett.

## Adottságok (amit a mai kód tud)

- A kártya kizárólag entitás-állapotokból dolgozik; saját UI-állapota
  (kiválasztott műsor/epizód) és `ha-form` alapú szerkesztője van
  (`www/tilos-player-card.js`).
- A backend az archív mp3 **fájlnevével** (`tilos-YYYYMMDD-HHMMSS-HHMMSS`,
  `archive_key()`) azonosítja, mi szól, és ráírja a lejátszó állapotára a
  `media_title` / `media_artist` / `entity_picture` hármast
  (`_patch_player_metadata`, `refresh_player_metadata`). A figyelő
  `state_changed` + 15 másodperces poll minden figyelt lejátszóra.
- Az integráció indításkor a beállított lejátszót is figyeli, tehát a
  metaadat akkor is helyes, ha a lejátszást nem a kártya indította.
- A „mentett epizódok” `Store` fájlban élnek
  (`.storage/tilos_player_saved_episodes_<entry_id>`), 1 másodperces
  késleltetett írással (`sensor.py`). Ugyanezt a mintát követjük.
- A lejátszás a `tilos_player.play` szolgáltatáson megy (HA mód), illetve
  `music_assistant.play_media`-en (MA mód). Seek ma nincs.
- Az epizód select `options`-ként csak **címkéket** ad; a kártya nem
  tudja, melyik címke melyik archív kulcs. A `save_key` csak a
  kiválasztott epizódra van meg.
- A kártya `_targetPlayer()`-e a beállított `media_player`, vagy a play
  button `media_player` attribútuma.

## Megközelítések

**A. Backend-oldali követés + `Store` (választott).**
A backend 30 másodpercenként lekérdezi a figyelt lejátszó(k) állapotát,
a pozíciót archív kulcs szerint tárolja egy entry-nkénti JSON fájlba, és
az epizód/műsor select attribútumaiban teszi elérhetővé a kártyának. A
fejléc a lejátszó állapotából (a backend által ráírt mezőkből) dolgozik.
Előny: kártya bezárva is követ, újraindítás után is megvan, automatizálásból
is olvasható, és a seek is a backendben van, egy helyen.
Hátrány: több backend kód (tároló, poller, seek, attribútumok).

**B. Kártya-oldali követés `localStorage`-ban.**
A kártya 30 másodpercenként mentené a lejátszó pozícióját a böngészőbe.
Előny: nincs backend munka. Hátrány: eszközönként/böngészőnként külön,
zárt kártyánál nincs követés, újraindítás/telefon nem látja, automatizálásból
nem elérhető. A kért „percenként kérdezze le a lejátszót” követelmény
csak nyitott kártyával teljesülne.
Elvetve.

**C. HA history/recorder alapú számítás.**
Elvetve: nincs epizód-szintű szemantika, a törléspolitika elviszi, és a
seek-pozícióhoz nem elég pontos.

**D. Music Assistant saját queue-pozíciójára építeni.**
Elvetve: az archív mp3-ak URL-ként mennek be, az MA nem tart rájuk
folytatható állapotot, és HA módban nem is elérhető.

## A felhasználó által eldöntött kérdések

1. **Fejléc szövege**: műsor neve, kötőjel, majd a cím, a végén a dátum
   zárójelben. Egy blokk, nagyobb betűkkel, mint a mostani címkék.
2. **Folyamatban ikon**: a műsor- és az epizódsorban is.
3. **Pause**: a borító és a szöveg marad; csak akkor áll vissza a logó,
   ha a lejátszás véget ért / leállt.
4. **Tárolás**: HA `Store` JSON, entry-nként (mint a mentett epizódok).

## Hogyan

### 1. Adatmodell — `progress.py` (új modul)

```python
PLAYBACK_PROGRESS_VERSION = 1
PROGRESS_POLL_INTERVAL = 30      # a kért félperces lekérdezés
PROGRESS_RESUME_MIN = 30         # ennél rövidebb pozíció nem folytatható
PROGRESS_FINISH_MARGIN = 30      # a vége előtt ennyivel már "befejezett"
PROGRESS_MAX_ENTRIES = 300       # felső korlát, a legrégebbi esik ki
PROGRESS_SAVE_DELAY = 1          # Store async_delay_save késleltetés
SEEK_WAIT_TIMEOUT = 20           # eddig várunk, hogy a lejátszó elinduljon
SEEK_RETRY_COUNT = 5
SEEK_RETRY_DELAY = 3
SEEK_TOLERANCE = 10              # ennyi másodpercen belül elfogadjuk
```

Tárolt bejegyzés (kulcs: archív fájlnév):

```json
{
  "version": 1,
  "entries": {
    "tilos-20260717-100000-120000": {
      "position": 1234,
      "duration": 4800,
      "show_name": "Szabadlábon",
      "updated": "2026-11-16T10:12:00+00:00"
    }
  }
}
```

`show_name` azért kell, hogy a műsor-legördülőben ikont tudjunk tenni
anélkül, hogy a teljes epizódlistát ismernénk (a mentett epizódok
esetében sem).

`TilosProgress` osztály (a runtime-ban: `runtime.progress`):

- `async_load()` — egyszer, az entry setupban, a platformok előtt.
- `record(key, position, duration)` — beírja/frissíti; ha
  `position < PROGRESS_RESUME_MIN`, inkább töröl.
- `clear(key)` — törlés (befejezés, vagy „Előről”).
- `has(key) -> bool`, `resumable(key) -> bool`, `position(key) -> int`,
  `show_names() -> set[str]`, `has_any(keys) -> bool`.
- `start(entity_id, key)` / `queue(key)` — a követés jelölése.
- `async_poll(_now)` — a 30 másodperces kör.
- `async_flush()` — kilépéskor azonnali írás.
- `listeners: set[Callable[[], None]]` — a select entitások frissítéséhez.

Korlát: `PROGRESS_MAX_ENTRIES` felett a legrégebbi `updated` esik ki, így
a fájl nem nő korlátlanul.

### 2. Követés (backend)

- `runtime.active_playback: dict[str, str]` — lejátszó entitás → archív
  kulcs, amit **innen** indítottunk.
- `runtime.queued_keys: set[str]` — MA sorból (enqueue: add/next/
  replace_next) várakozó kulcsok, legfeljebb 200 elem.
- Indításkor (`play_selected_episode`) a kulcs bekerül
  `active_playback`-be (közvetlen lejátszás, `enqueue` nélkül vagy
  `play`/`replace`) vagy `queued_keys`-be (sorba állítás).
- 30 másodperces kör minden figyelt lejátszóra (`watched_players`):
  - ha az állapot `playing`/`paused`/`buffering` és az aktuális média
    archív kulcsa ismert, és a kulcs `active_playback`-ben vagy
    `queued_keys`-ben van → `record(...)`, a kulcs átkerül
    `active_playback`-be;
  - **a pozíció számítása** (a `media_position` önmagában elavult: a HA
    csak állapotíráskor frissíti, a poll 30 másodperccel később olvassa):
    `position = media_position`, és ha van `media_position_updated_at`
    attribútum, akkor `playing` állapotban hozzáadjuk az eltelt
    másodperceket (`now - media_position_updated_at`), `paused`-ban nem.
    Ha `media_duration` nincs vagy 0, csak a pozíciót mentjük, a
    befejezettséget nem tudjuk eldönteni (a bejegyzés megmarad);
  - a `show_name` a `media_index[key].show_name`-ből jön (ezért kapja
    meg az `EpisodeInfo`), nem a lejátszó `media_artist`-jéből (abban
    ott a ` // Tilos Rádió` utótag);
  - ha a pozíció elérte `duration - PROGRESS_FINISH_MARGIN`-t → `clear(key)`
    (befejezett adás nem folytatható);
  - minden más eset (más média, nem aktív állapot) → a kulcs kikerül a
    követésből; a legutóbb mentett pozíció megmarad (megszakított adás
    folytatható).
- A meglévő `state_changed` figyelő (metadata watcher) azonnal zárja a
  követést, ha a figyelt lejátszó más médiára vált vagy leáll; a záró
  pozíció az `old_state` `media_position` értéke, ha van (így legfeljebb
  30 másodpercet veszíthetünk).
- Csak a `tilos-…` kulcsú archív epizódok követettek; élő adás, direkt
  link, más forrás nem.

### 3. Folytatás (seek)

- `play_selected_episode(..., resume: bool = False)`:
  - `resume=True` és van mentett pozíció → `position` a mentett érték;
  - `resume=True`, de nincs (már) mentett pozíció → 0-ról indul;
  - `resume=False` (Előről, Lejátszás) → `clear(key)` (a régi idő törlődik,
    az ikon eltűnik), 0-ról indul.
- `play_media` után, ha `position > 0`: `async_seek_when_ready()`:
  - max `SEEK_WAIT_TIMEOUT` másodpercig 1 másodperces lépésben várja, hogy
    a lejátszó aktív legyen **és** a kulcs az legyen, ami szól;
  - `media_player.media_seek` `seek_position: position`;
  - legfeljebb `SEEK_RETRY_COUNT` próba `SEEK_RETRY_DELAY`-jel, amíg a
    lejátszó pozíciója (a fenti, `media_position_updated_at`-tel
    korrigált érték) `SEEK_TOLERANCE`-on belülre nem kerül;
  - kudarc esetén `_LOGGER.warning`, a lejátszás elölről megy tovább (nem
    áll meg, nem jelez hibát a felhasználónak).
- MA mód: ugyanez a `media_player.media_seek` a lejátszó entitáson,
  `enqueue: play` / `replace` után. `add` / `next` / `replace_next`
  esetén a `resume` figyelmen kívül marad (a tétel még nem szól).

### 4. Amit a kártya lát (entitás-attribútumok)

Lejátszó állapotára írt plusz mezők (`_patch_player_metadata` bővítése):

- `tilos_key` — a most szóló archív kulcs;
- `tilos_display` — kész fejléc-szöveg:
  `"{műsor neve} – {cím} ({YYYY.MM.DD.})"`.
  A cím eleji dátumot levágjuk, ha a cím már azzal kezdődik (a Tilos
  címek gyakran `2026.07.17. - …` alakúak), hogy ne legyen dupla dátum.
  Ha nincs műsornév/dátum (direkt link), csak a cím.
- A `refresh_player_metadata` akkor is írjon állapotot, ha a lejátszó
  aktív, de **nem** archív kulcs szól: ilyenkor a `tilos_key` és a
  `tilos_display` kerüljön le (a `media_title`/`media_artist`/
  `entity_picture` marad, azt nem bántjuk). Csak akkor ír, ha tényleg
  volt mit törölni — nincs állapot-írás kör.

Epizód select (`select.py`) — `_unrecorded_attributes` bővítve:

- `episodes: [{label, key, progress}]` — a legördülő opcióival azonos
  sorrendben és címkékkel (a címke-dedup logika egy helyre, közös
  `_labeled_episodes()` segédbe kerül, amit az `options` és az
  attribútum is használ);
- a kiválasztott epizódnál: `progress: bool` (a meglévő `save_key` mellé).

Műsor select (`select.py`):

- a `shows` lista elemei: `{id, name, type, progress}` — `progress` igaz,
  ha a progress-tárban van olyan kulcs, aminek a `show_name`-je ez a
  műsor;
- `saved_progress: bool` — a „Mentett epizódok” sor ikonjához (van-e
  mentett idő bármelyik mentett epizódra).

Mindkét select `async_write_ha_state`-et hív, amikor a progress-változás
egy `progress` logikai értéket átbillent (nem minden pollnál).

### 5. Kártya — fejléc

- Új config: `show_cover` (boolean, alapból `false`), a szerkesztőben
  kapcsoló: „Borító megjelenítése” + súgó.
- DOM: a logó `<img>` mellé egy rejtett fejléc blokk:

```html
<div class="cover" hidden>
  <img class="cover-image" alt="">
  <div class="cover-text"></div>
</div>
<img class="logo" ...>
```

- `_update()` minden állapotváltozásnál eldönti:
  - `show_cover` be, a céllejátszó állapota `playing|paused|buffering`,
    és van `tilos_key` → borító + `tilos_display` szöveg, logó rejtve;
  - minden más esetben (nincs lejátszás, nem Tilos-epizód, üres beállítás)
    → logó, fejléc rejtve.
- A borító `src`: abszolút URL, vagy `/`-lel kezdődő relatív útvonal
  `hassUrl()`-lel (mint a logó).
- A szöveg egy blokk, nagyobb betűkkel (a legördülő érték mérete felett),
  maximum 2 sor, `text-overflow: ellipsis` — a pontos méret a builderé.
- A borító ugyanazt a szélességet/lekerekítést kapja, mint a logó; a
  kép helye nem ugrál (fix magasságú konténer, `object-fit: cover`).

### 6. Kártya — listaikonok és gombsor

- Ikon: a csillag/könyvjelző mellett egy külön `dropdown-option-progress`
  slot (18 px, minden sorban jelen van, üresen is, hogy a címkék egy
  vonalban maradjanak). Kitöltve `play-circle-outline` ikonnal.
- A műsor sorban a csillag és a progress ikon egymás mellett fér el.
- A „Mentett epizódok” sor a `saved_progress` alapján kap ikont.
- Az epizód sorok progress értéke a select `episodes` attribútumából, a
  címke alapján párosítva (a címkék egyediek). A kiválasztott epizód
  gombpárjánál ugyanaz a védőfeltétel, mint a `_selectedEpisodeInfo`-nál:
  az attribútum csak akkor számít, ha `episodeState.state` megegyezik a
  kártya `_selectedEpisode`-jével (a kattintás utáni átmeneti időben
  különben a régi epizód adata jönne).
- Gombsor: a `_render()` továbbra is kirakja mind az öt lehetséges gombot
  (Sorba [csak MA], Lejátszás, Előről, Folytatás, Élő adás), és a
  `_update()` kapcsolgatja a `hidden`-t:
  - kiválasztott epizód `progress === true` → Lejátszás rejtve,
    Előről + Folytatás látszik;
  - egyébként Lejátszás látszik, a másik kettő rejtve.
- Oszlopok: látható gombok száma → `grid-template-columns:
  repeat(n, 1fr)`; 4 gombnál 2×2 (`repeat(2, 1fr)`), hogy a hosszabb
  feliratok elférjenek.
- Gombok:
  - **Előről** → `tilos_player.play` `{media: "episode"}`, `resume` nélkül
    (a backend törli a mentett időt);
  - **Folytatás** → `tilos_player.play` `{media: "episode", resume: true}`;
  - MA módban `enqueue: "play"` megy velük (mint a mai Lejátszásnál);
  - a link mező tartalma továbbra is elsőbbséget élvez: ha van érvényes
    link, a két gomb is azt játssza (a resume ilyenkor nem értelmezett).
- Engedélyezés: a két új gomb ugyanazt a feltételt kapja, mint a mai
  Lejátszás (`van céllejátszó`, `van kiválasztott epizód`).

### 7. Szolgáltatás

`tilos_player.play` új opcionális mező: `resume` (boolean, alapból
`false`). Csak `media: episode` esetén van hatása. `services.yaml` +
`strings.json`/`translations` frissítés.

### 8. Érintett fájlok

- `custom_components/tilos_player/progress.py` (új) — tár, poller, seek.
- `custom_components/tilos_player/__init__.py` — runtime mezők, progress
  létrehozása/indítása/leállítása, `EpisodeInfo` (`show_name`,
  `timestamp`), `tilos_key`/`tilos_display` patch + takarítás,
  `play_selected_episode(resume)`, szolgáltatás séma.
- `custom_components/tilos_player/select.py` — `episodes` attribútum,
  `shows[].progress`, `saved_progress`, közös `_labeled_episodes()`.
- `custom_components/tilos_player/www/tilos-player-card.js` — fejléc,
  ikonok, gombok, `show_cover` config + szerkesztő mező + súgó.
- `custom_components/tilos_player/services.yaml`, `strings.json`,
  `translations/en.json` — `resume` mező.
- `README.md` — új fícsörök + kártya-beállítás leírása.
- `manifest.json` — verzió 1.7.0.

## Élek és hibakezelés

- A lejátszó nem tud seekelni → figyelmeztetés a logban, lejátszás
  elölről; a mentett pozíció megmarad.
- „Folytatás” olyan epizódra, aminek közben elfogyott a mentett ideje
  (pl. másik böngészőben befejezték) → 0-ról indul.
- Archívumból kikerült / már nem listázott epizód → a kulcs alapján
  továbbra is folytatható, ha a lejátszó tudja; a tár nem hivatkozik
  listára.
- Két kártya / két lejátszó: a követés lejátszónként külön (`active_playback`
  entitás → kulcs), a tár közös.
- Újraindítás: a `Store` betöltése a platformok előtt történik, így az
  első renderben már látszik az ikon és a gombpár.
- „Előről” után azonnal törlődik a bejegyzés → az ikon és a gombpár a
  következő állapotfrissítésnél visszavált; az első mentés 30 másodperc
  után jön.
- A `tilos_display`/`tilos_key` mezők a recorderbe bekerülnek (kis
  szövegek), ez elfogadható; az epizódlista attribútum viszont
  `_unrecorded_attributes`-ben marad.

## Builder-kör utáni pontosítások (saját döntések)

Ezeket a terv írásakor még nem rögzítettem; egy builder-átolvasás után
saját döntésként kerültek bele, mert egyik sem változtat a
viselkedésen, csak a megvalósítás helyességén:

1. **Pozíció frissessége** — a `media_position` a HA-ban csak az utolsó
   állapotíráskor pontos, ezért `media_position_updated_at`-tel kell
   korrigálni (lásd 2. pont). Enélkül a mentett pozíció rendszeresen
   fél perccel lemaradna, és a seek utáni ellenőrzés is hibás lenne.
2. **`show_name` forrása a pollerben** — a `media_index` bejegyzésből,
   nem a lejátszó `media_artist`-jéből (utótag). Ezért bővül az
   `EpisodeInfo` `show_name` és `timestamp` mezővel.
3. **Átnevezett műsor** — a műsor-ikon párosítás név alapján történik; ha
   a Tilos API átnevez egy műsort, a régi bejegyzés ikonja eltűnik a
   műsorsorból (az epizódsorban és a „Mentett epizódok” sornál marad). Ez
   kozmetikai hiba, ezért nem tárolunk külön show ID-t a mentett
   epizódokhoz (azoknál nincs is megbízható ID).
4. **`tilos_display` hiánya** — ha a lejátszó állapotán nincs
   `tilos_display` (pl. HA újraindítás utáni első pillanat), a fejléc a
   `media_title`-re esik vissza; ha az sincs, a fejléc nem jelenik meg.

## Amit a builderre hagyok

- Ikon-previewk: pontos mdi path-ok (progress ikon), px méretek, a
  fejléc-szöveg betűmérete és tördelése.
- A poll indításának helye és a `state_changed`-kezelő pontos
  összefésülése a meglévő metadata watcherrel (közös listener vagy külön).
- Hány elemig tartsuk a `queued_keys` halmazt, illetve a `Store` írás
  késleltetését.
- Teszt(ek) formája: a repóban ma nincs teszt-infrastruktúra; a seek és a
  progress számítás tiszta függvényeire érdemes egységet írni, a
  lejátszó-interakcióra nem.

## Kockázatok

1. **Seek időzítés** — a `play_media` utáni seeket nem minden lejátszó
   fogadja el azonnal; a poll+retry kezeli, de lassabb indulásnál a
   folytatás elmaradhat (log warning). Ez a legnagyobb bizonytalanság.
2. **Music Assistant seek** — MA lejátszón a `media_seek` támogatás
   verziófüggő; ugyanaz a fallback.
3. **Állapot-írások száma** — a 30 másodperces poll csak akkor ír
   állapotot, ha egy `progress` logikai érték megváltozott, így a
   recorder és az eseménybusz nem kap 30 másodpercenként frissítést.
4. **Borító forrása** — a `tilos_display`/`tilos_key` a lejátszó
   állapotára írt mező; ha egy másik integráció felülírja a lejátszó
   attribútumait, a fejléc visszaáll a logóra (nem hiba, csak elveszik a
   kijelzés a következő patchig).
