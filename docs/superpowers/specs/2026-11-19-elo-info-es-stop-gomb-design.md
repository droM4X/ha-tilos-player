# Élő adás infó, pulzáló Élő gomb, Stop gomb — design

Dátum: 2026-11-19
Státusz: jóváhagyásra vár

## Miért

A kártya fejléce ma csak archív epizódra mutat képet + szöveget: a
`_playingInfo()` a lejátszón írt `tilos_key`-t követeli, amit a backend
csak archív mp3-ra ír rá. Élő adás (`stream.tilos.hu`) alatt ezért sosem
látjuk, mi szól, pedig a stream metaadata a lejátszó `media_artist` /
`media_title` attribútumaiban elérkezik, és folyamatosan változik.

Másik hiány: lejátszás alatt a kártyán nincs stop. A Lejátszás gomb
mindig lejátszást indít, leállítani csak a Home Assistantban lehet.

## Célok

- Élő adás alatt a kártya tetején a **logó marad a kép**, alá a most szóló
  előadó és cím, ugyanott, ahol archív lejátszásnál a borító szövege van.
- Az élő felirat és az Élő gomb jelzése a lejátszó attribútumaiból jön,
  frissül, ahogy a stream metaadata változik.
- Az **Élő gomb pirosan pulzál** (CSS), halvány háttér-változással, amíg
  a rádió szól.
- Aktív lejátszás alatt a **Lejátszás gomb Stop gombbal váltódik fel**
  (negyzet stop ikon), nyomása `media_player.media_stop`-ot hív.
- Egy kapcsoló (`show_info`) kezeli a fejléc-infót archívra és élőre
  egyaránt, **alapból bekapcsolva**.

## Nem célok

- Backend változás nincs: nem írunk `tilos_key`-t az élő adásra, nem hozunk
  létre sensor entitást, nem polledünk Icecast statuszt.
- Nincs Pause gomb, nincs haladássáv, nincs hangerő-szabályozás.
- A stop nem törli a mentett lejátszási pozíciót (a midway stop után a
  **Folytatás** megmarad — a `is_finished` ezt így kezeli).
- A logó képfájlját nem nyúlunk hozzá.

## Anti-célok

- Ne legyen kirívó, "figyelemfelhívó" animáció: a pulzálás halvány, lassú,
  a kártya fekete hátterébe illeszkedő jelzés.
- Ne mutasson live feliratot, ha nem Tilos rádió szól (pl. másik stream a
  lejátszón) — ezt a `stream.tilos.hu` szűrés dönti el.
- Ne törölje a stop a folytatás lehetőségét.
- Egy már beállított, `show_cover: false`-szal rendelkező kártya ne kapjon
  hirtelen bekapcsolt fejlécet frissítéskor.

## Adottságok (mit tud a mai kód)

- A kártya (`www/tilos-player-card.js`) kizárólag entitás-állapotokból
  dolgozik; Lovelace minden álltozáskor új `hass`-t ad át, így `_update()`
  a lejátszó attrib-változásaira is lefut.
- `_playingInfo()` (~1712) archív ág: `state ∈ {playing, paused, buffering}`
  + `attrs.tilos_key` + `tilos_display` (vagy `media_title`).
- `_updateCover()` (~1753): `show_cover` && info → `.logo` elrejtése,
  `.cover` (`.cover-image` + `.cover-text`) kirakása; info nélkül a logó.
- Gombsor: `.buttons` grid, `_updateActionButtons()` (~1630) rejti el a
  `play`-t a `restart`/`resume` párra, és a látható gombok számából számolja
  a `grid-template-columns`-t.
- Élő indítás: `_callTilosPlay("live")` → `tilos_player.play media: live` →
  `LIVE_STREAM_URL = https://stream.tilos.hu/tilos` (const.py).
- A kártya jelenleg **egyetlen** `media_player` service call-t sem hív.
- Editor: `EDITOR_LABELS` / `EDITOR_HELPERS` / `_schema()` tartalmazzák a
  `show_cover` boolt; a form `value-changed` a teljes configot továbbadja.

## Megvalósítások (ahogy láttam)

**A) Minden a kártyában** *(választott)* — `_liveInfo()` + `_headerInfo()`
egységes fejléc-api, `.live-active` CSS pulzálás, `show_info` kulcs, Stop gomb
közvetlen `media_player.media_stop` call-lal. Backend érinthetlen, egyetlen
JS fájl változik (+README). Tráding: a Live felirat csak olyan lejátszón
lesz jó, ami tényleg közvetíti a stream metaadatát.

**B) A backend írja az élőre is a `tilos_key`/`tilos_display` pár** — a
kártya útvonala változatlan maradna. Elvetve: a kérés explicit nem kérte, a
`tilos_key` archív kulcs-formátum (`tilos-YYYYMMDD-...`) élő streamre nem
adható, és a backend metaadat-öre (`METADATA_REWRITE_INTERVAL = 5`)
visszaírná a saját mezőit, elütve a stream saját metaadatát.

**C) Új backend sensor az élő artist/címre (Icecast status)** — működne
olyan lejátszón is, ami nem adja tovább a metaadatot. Elvetve: explicit nem
kért, új entitás + polling + hibakezelés.

A Stop megvalósítása szintén közvetlen service call (nem új
`tilos_player.stop` service): a pozíció-fejlesztő 30 mp-enként ment, így a
stop nem igényel backend flush-t.

## Elintézett részletek

- **`show_info` (boolean, alapértelmezett: `true`)** felváltja a
  `show_cover`-t az editorban (label: „Adásinfó megjelenítése", helper
  szöveg frissítve), és mindkét ágra vonatkozik. Visszafelé kompatibilitás:
  `show_info: config.show_info ?? config.show_cover`, azaz aki expliciten
  `show_cover: false`-ot állított, annál `false` marad. Amikor az editor
  `show_info`-t ír, a régi `show_cover` kulcsot törli a configból.
- **Fejléc állapotok:**
  1. `show_info` kikapcsolva → statikus logó, szöveg nélkül (mai viselkedés).
  2. Archív (`tilos_key`) → borító + `Műsor – Cím (dátum)` (szünet alatt is,
     mint eddig).
  3. Élő → **logó + szöveg alatta**. Szöveg: `media_artist – media_title`,
     hiányzó mező kihagyva (csak az egyik → egy mezős sor), egyik sincs →
     vissza a sima logóra. Az élő ágon az `entity_picture`-t nem
     használjuk, a kártya `logo` beállításában lévő kép marad.
- **Élő felismerés** (single source: `_liveInfo()` / `_isLiveRadio()`, ebből
  indul a felirat és a pulzálás is): a `_targetPlayer()` entitása
  `state === "playing"` **és** a `media_content_id` tartalmazza a
  `stream.tilos.hu` szöveget. Szünetben (`paused`) a live felirat és a
  pulzálás eltűnik — a kérés szerint.
- **Pulzálás:** `.action-button.live` kap egy `live-active` osztályt.
  `@keyframes` a `background-color`-t animálja halvány vörösek között
  (`rgba(219,68,55,0.10)` → `rgba(219,68,55,0.26)`), az ikon színe
  `var(--error-color)` marad, az animáció `~1.8s ease-in-out infinite`.
  A `.action-button:hover` háttér megmarad (az animáció felülírja).
  `@media (prefers-reduced-motion: reduce)` → nincs animáció, csak egy
  állandó halvány háttér + piros ikon. A jelzés csak a gombon van, se a
  kártyán, se a logón.
- **Stop gomb:** action `stop`, ikon egy kitöltött négyzet (`STOP_PATH`
  konstans a `PLAY_PATH` mellé, 24×24 viewBox), `aria-label`/`title`:
  „Leállítás". Nyomása `callService("media_player","media_stop",
  {entity_id: target})`. Letiltva, ha nincs céllejátszó.
- **Slot-szabály** (`_updateActionButtons()`):
  - céllejátszó `playing` vagy `buffering` → **Stop** a Lejátszás slotjában,
    az Előről/Folytatás pár elrejtve;
  - különben ha van mentett pozíció a kiválasztott epizódhoz → **Előről +
    Folytatás**;
  - különben → **Lejátszás**.
  A Sorba (MA mód) és az Élő gomb mindig megmarad. A meglévő
  `repeat(N,1fr)` látható-számolás így is működik.
  Élő stream stopja után a felirat és a pulzálás is elmúlik (`media_stop` →
  `idle`).
- **README:** a `show_cover` leírása `show_info`-ra átnevezése + új bekezdés
  az élő adás infóról és a Stop gombról.

## Építőre hagyott részek

- A `STOP_PATH` pontos SVG útvonala (a `PLAY_PATH` stílusához illő, kis
  sarkú négyzet) és a pulzálás timing/értékeinek finomhangolása — a fenti
  értékek
  indulópontok.
- A kártya JS-re nincs teszt-harness (a `tests/` Python-only), a
  ellenőrzés: `node --check`, `pytest`, `ruff check` + manuális kipróbálás
  a HA-ban.
