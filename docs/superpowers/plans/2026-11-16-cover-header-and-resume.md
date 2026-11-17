# Borító fejléc és folytatható lejátszás — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A kártya tetején a most szóló Tilos-epizód borítója és szövege látszódjon (kapcsolhatóan), a kártyáról indított epizódok pozíciója pedig mentődjön és folytatható legyen Előről/Folytatás gombokkal.

**Architecture:** A backend egy entry-nkénti `Store` JSON-fájlban tartja az archív kulcs szerinti pozíciókat, 30 másodpercenként lekérdezve a figyelt lejátszókat; a select entitások attribútumaiban tesszük elérhetővé a kártyának, a seek a `tilos_player.play` szolgáltatás `resume` mezőjén megy. A fejléc a backend által a lejátszó állapotára írt `tilos_key` / `tilos_display` mezőkből dolgozik.

**Tech Stack:** Home Assistant custom integration (Python 3.13+, `DataUpdateCoordinator`, `Store`, `async_track_time_interval`), vanilla JS Lovelace card (shadow DOM), pytest (csak a HA-tól független tiszta modulokra).

**Spec:** `docs/superpowers/specs/2026-11-16-borito-fejlec-es-folytatas-design.md`

## Global Constraints

- Nincs új futásidejű függőség: `manifest.json` `requirements` marad `[]`; a tesztkövetelmény csak a `.venv`-be kerül.
- `progress.py` **kizárólag** a Python stdlib-et importálhatja (se `homeassistant`, se csomag-relatív import), különben a tesztek nem futnak HA nélkül.
- Store: `Store(hass, PLAYBACK_PROGRESS_VERSION, f"tilos_player_progress_{entry_id}", private=True)`, 1 másodperces `async_delay_save`.
- Poll intervallum pontosan 30 másodperc (`PROGRESS_POLL_INTERVAL = 30`).
- Feliratok magyarul, pontosan: „Borító megjelenítése”, „Előről”, „Folytatás”; a fejléc szövegformátuma `Műsor neve – Cím (ÉÉÉÉ.HH.NN.)`.
- A kártya API-ból jövő szöveget `textContent`/`setAttribute`-tel ír (soha nem `innerHTML`-be fűzve) — a meglévő minta szerint.
- Kártya config alapérték: `show_cover: false` (a meglévő YAML-ok változatlanul működnek).
- A dátumformázás ugyanazt a (UTC-alapú) logikát használja, mint a meglévő `TilosEpisodeSelect._format_ts`, hogy a fejléc és a legördülő ne térjen el.
- Élő adás és a link mezőből indított mp3 nem kap progress-t.
- `manifest.json` verzió: `1.7.0`.

## Review Focus

- Lejátszó, ami nem ad `media_duration`-t (stream): az adás ne legyen automatikusan „befejezett”, a bejegyzés maradjon folytatható. → `tests/test_progress.py::test_record_without_duration_keeps_the_entry_resumable`, `::test_is_resumable_with_unknown_duration`.
- A lejátszó state-jében nincs `media_position` (egyes integrációk sosem írják): ne mentődjön 0, mert a Folytatás az elejére ugrana — inkább semmi ne történjen. → `::test_effective_position_returns_none_without_media_position`, `::test_effective_position_returns_none_for_null_position`.
- Sérült / idegen / régi Store-tartalom: az integráció töltődjön be üres tárral, ne dobjon kivételt. → `::test_from_payload_tolerates_garbage`, `::test_from_payload_tolerates_bad_entries`.
- Olyan cím, ami levágás után csak a dátum (nincs valódi cím): ne „Műsor – (dátum)” legyen, hanem maradjon az eredeti cím. → `::test_format_now_playing_keeps_a_title_that_is_only_a_date`.
- `paused` állapotban is frissülhet `media_position_updated_at`: pause alatt tilos extrapolálni, különben a folytatás előrébb ugrik. → `::test_effective_position_does_not_extrapolate_when_paused`.

---

### Task 1: Tiszta progress-modell és fejléc-szöveg (`progress.py`)

**Files:**
- Create: `custom_components/tilos_player/progress.py`
- Create: `tests/conftest.py`
- Create: `tests/test_progress.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces (Task 2–4 és 6 ezt használja):
  - `PLAYBACK_PROGRESS_VERSION = 1`, `PROGRESS_POLL_INTERVAL = 30`, `PROGRESS_RESUME_MIN = 30`, `PROGRESS_FINISH_MARGIN = 30`, `PROGRESS_MAX_ENTRIES = 300`, `PROGRESS_SAVE_DELAY = 1`, `SEEK_WAIT_TIMEOUT = 20`, `SEEK_RETRY_COUNT = 5`, `SEEK_RETRY_DELAY = 3`, `SEEK_TOLERANCE = 10`
  - `format_now_playing(show_name: str, title: str, timestamp_ms: int) -> str`
  - `effective_position(attributes: Mapping[str, Any], player_state: str, now: datetime) -> float | None`
  - `is_finished(position: float, duration: float) -> bool`
  - `is_resumable(position: float, duration: float) -> bool`
  - `@dataclass ProgressEntry: key: str, position: int, duration: int, show_name: str, updated: str`
  - `class ProgressBook(max_entries: int = PROGRESS_MAX_ENTRIES)` metódusai:
    `record(key, position, duration, show_name, now: datetime | None = None) -> bool`,
    `clear(key) -> bool`, `get(key) -> ProgressEntry | None`, `has(key) -> bool`,
    `position(key) -> int`, `show_names() -> set[str]`,
    `has_any(keys: Iterable[str]) -> bool`, `to_payload() -> dict[str, Any]`,
    `take_dirty() -> bool`, `ProgressBook.from_payload(payload: Any) -> ProgressBook` (classmethod)
  - `record` akkor és csak akkor ad vissza `True`-t, ha a **folytatható kulcsok halmaza** változott (létrejött, törlődött, kiesett) — ezen a jelzésen múlik, hogy nem írunk entitás-állapotot minden 30. másodpercben.
  - `take_dirty()` adja vissza, hogy a könyv tartalma az utolsó lekérdezés óta **bármiben** változott-e (pozíció, bejegyzés, kiesés), és nullázza a jelzést — ezen múlik a fájlba írás; a pozíció 30 másodpertenként változik, a kulcshalmaz nem.

- [ ] **Step 1: Teszt-infra és a bukó tesztek**

`.gitignore` végére: `.venv/`, `.pytest_cache/`.

`tests/conftest.py` — a `progress.py` HA nélkül importálható legyen (a csomag `__init__.py`-ja `homeassistant`-t importál, ezért a modult a saját könyvtárából töltjük be):

```python
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "tilos_player"),
)
```

`tests/test_progress.py` — fejléc:

```python
from datetime import datetime, timedelta, timezone

from progress import (
    PLAYBACK_PROGRESS_VERSION,
    ProgressBook,
    effective_position,
    format_now_playing,
    is_finished,
    is_resumable,
)

KEY = "tilos-20260717-100000-120000"
KEY2 = "tilos-20260718-100000-120000"
TS = 1784282400000  # 2026-07-17T10:00:00Z
NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
```

A tesztek (minden `assert` a specifikáció pontos értékeivel):

```python
def test_format_now_playing_joins_show_title_and_date():
    assert format_now_playing("Szabadlábon", "Tracklistával", TS) == (
        "Szabadlábon – Tracklistával (2026.07.17.)"
    )

def test_format_now_playing_drops_a_leading_date_from_the_title():
    assert format_now_playing("Szabadlábon", "2026.07.17. - Tracklistával", TS) == (
        "Szabadlábon – Tracklistával (2026.07.17.)"
    )

def test_format_now_playing_keeps_a_title_that_is_only_a_date():
    assert format_now_playing("Szabadlábon", "2026.07.17.", TS) == (
        "Szabadlábon – 2026.07.17. (2026.07.17.)"
    )

def test_format_now_playing_without_show_name():
    assert format_now_playing("", "Tracklistával", TS) == "Tracklistával (2026.07.17.)"

def test_format_now_playing_without_timestamp():
    assert format_now_playing("Szabadlábon", "Tracklistával", 0) == "Szabadlábon – Tracklistával"

def test_effective_position_extrapolates_while_playing():
    attrs = {"media_position": 100.0,
             "media_position_updated_at": NOW - timedelta(seconds=10)}
    assert effective_position(attrs, "playing", NOW) == 110.0

def test_effective_position_does_not_extrapolate_when_paused():
    attrs = {"media_position": 100.0,
             "media_position_updated_at": NOW - timedelta(seconds=10)}
    assert effective_position(attrs, "paused", NOW) == 100.0

def test_effective_position_without_update_timestamp_returns_media_position():
    assert effective_position({"media_position": 42}, "playing", NOW) == 42.0

def test_effective_position_returns_none_without_media_position():
    assert effective_position({}, "playing", NOW) is None

def test_effective_position_returns_none_for_null_position():
    assert effective_position({"media_position": None}, "playing", NOW) is None

def test_is_finished_within_the_finish_margin():
    assert is_finished(4775, 4800) is True

def test_is_finished_ignores_unknown_duration():
    assert is_finished(4775, 0) is False

def test_is_resumable_needs_the_minimum_position():
    assert is_resumable(29, 4800) is False
    assert is_resumable(30, 4800) is True

def test_is_resumable_requires_room_before_the_end():
    assert is_resumable(4780, 4800) is False

def test_is_resumable_with_unknown_duration():
    assert is_resumable(120, 0) is True

def test_record_keeps_a_resumable_position():
    book = ProgressBook()
    assert book.record(KEY, 120, 4800, "Szabadlábon", NOW) is True
    assert book.has(KEY) is True
    assert book.position(KEY) == 120

def test_record_stores_the_position_as_whole_seconds():
    book = ProgressBook()
    book.record(KEY, 120.6, 4800, "Szabadlábon", NOW)
    assert book.position(KEY) == 121

def test_record_of_a_position_below_the_minimum_clears_the_entry():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.record(KEY, 5, 4800, "Szabadlábon", NOW) is True
    assert book.has(KEY) is False

def test_record_near_the_end_marks_the_episode_finished():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.record(KEY, 4780, 4800, "Szabadlábon", NOW) is True
    assert book.has(KEY) is False

def test_record_without_duration_keeps_the_entry_resumable():
    book = ProgressBook()
    assert book.record(KEY, 120, 0, "Szabadlábon", NOW) is True
    assert book.has(KEY) is True

def test_record_returns_false_when_only_the_position_moved():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.record(KEY, 150, 4800, "Szabadlábon",
                       NOW + timedelta(seconds=30)) is False

def test_clear_reports_the_change_once():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.clear(KEY) is True
    assert book.clear(KEY) is False

def test_show_names_returns_the_shows_with_a_stored_position():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    book.record(KEY2, 60, 4800, "Másik műsor", NOW)
    assert book.show_names() == {"Szabadlábon", "Másik műsor"}

def test_has_any_checks_keys():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.has_any([KEY2, KEY]) is True
    assert book.has_any([KEY2]) is False

def test_oldest_entry_is_evicted_past_the_limit():
    book = ProgressBook(max_entries=2)
    book.record(KEY, 100, 4800, "A", NOW)
    book.record(KEY2, 100, 4800, "B", NOW + timedelta(seconds=1))
    book.record("tilos-20260719-100000-120000", 100, 4800, "C",
                NOW + timedelta(seconds=2))
    assert book.has(KEY) is False
    assert book.has(KEY2) is True

def test_take_dirty_reports_and_resets():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    assert book.take_dirty() is True
    assert book.take_dirty() is False

def test_record_of_a_moved_position_marks_the_book_dirty():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    book.take_dirty()
    book.record(KEY, 150, 4800, "Szabadlábon", NOW + timedelta(seconds=30))
    assert book.take_dirty() is True

def test_clear_marks_the_book_dirty_once():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    book.take_dirty()
    assert book.clear(KEY) is True
    assert book.take_dirty() is True
    assert book.clear(KEY) is False
    assert book.take_dirty() is False

def test_payload_round_trip():
    book = ProgressBook()
    book.record(KEY, 120, 4800, "Szabadlábon", NOW)
    restored = ProgressBook.from_payload(book.to_payload())
    assert restored.position(KEY) == 120
    assert restored.get(KEY).show_name == "Szabadlábon"
    assert restored.get(KEY).updated == NOW.isoformat()
    assert restored.get(KEY).duration == 4800

def test_from_payload_tolerates_garbage():
    for payload in (None, [], "x", {}, {"entries": []}, {"entries": {"k": 5}}):
        assert ProgressBook.from_payload(payload).to_payload() == {
            "version": PLAYBACK_PROGRESS_VERSION,
            "entries": {},
        }

def test_from_payload_tolerates_bad_entries():
    payload = {"entries": {
        "k": {"position": "x"},
        "tilos-20260717-100000-120000": {"position": 90, "duration": 4800,
                                         "show_name": "Szabadlábon",
                                         "updated": NOW.isoformat()},
    }}
    book = ProgressBook.from_payload(payload)
    assert book.has("k") is False
    assert book.has(KEY) is True
```

- [ ] **Step 2: Futtasd, hogy elbukjanak**

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```
Várt: `ModuleNotFoundError: No module named 'progress'` (minden teszt gyűjtési hibával bukik).

- [ ] **Step 3: Írd meg a `progress.py`-t**

Modul-docstring: a tiszta (HA-mentes) logika + a fejléc-szöveg; a HA-ragasztás a `progress_tracker.py`-ban van. Konkrét döntések:
- A cím eleji dátum levágása: `^\d{4}\.\d{2}\.\d{2}\.?\s*(?:[-–—]\s*)?`; ha a maradék üres, az **eredeti** cím marad.
- Dátum: `datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y.%m.%d.")` (mint a `select._format_ts`).
- `effective_position`: `media_position` hiány/Nem-szám → `None`; `player_state == "playing"` és van `media_position_updated_at` → hozzáadjuk az eltelt másodperceket; az eredmény `max(0.0, …)`.
- `record`: `position`/`duration` float-ként jön; a tárolt pozíció `int(round(position))`; ha `not is_resumable(...)` → `clear`. Őrzi a `now`-ot `updated` ISO stringként, és a könyv a `record` végén a legrégebbi `updated` szerint vágja le a felesleget.
- `to_payload`: `{"version": PLAYBACK_PROGRESS_VERSION, "entries": {key: {"position", "duration", "show_name", "updated"}}}`.
- `from_payload`: bármilyen bemenet elfogadható, ami nem felel meg, kimarad (nem dob kivételt, a `version`-t olvasáskor nem ellenőrzi).

- [ ] **Step 4: Futtasd, hogy átmenjenek**

```bash
.venv/bin/python -m pytest tests -q
```
Várt: `~28 passed`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore tests/conftest.py tests/test_progress.py custom_components/tilos_player/progress.py
git commit -m "feat: playback progress model and now-playing text"
```

---

### Task 2: Progress-követő (Store, 30 s poll) és a runtime bekötése

**Files:**
- Create: `custom_components/tilos_player/progress_tracker.py`
- Modify: `custom_components/tilos_player/const.py` (új `ACTIVE_PLAYER_STATES`)
- Modify: `custom_components/tilos_player/__init__.py` (EpisodeInfo, `_remember_media`, `register_episode`, `TilosRuntimeData`, `async_setup_entry`/`async_unload_entry`)

**Interfaces:**
- Consumes: Task 1 teljes API-ja; `__init__._archive_key_from_state(state) -> str | None`.
- Produces (Task 3–4 használja):
  - `EpisodeInfo.show_name: str` és `EpisodeInfo.timestamp: int` (ms epoch)
  - `TilosRuntimeData.progress: "ProgressTracker | None" = None`
  - `class ProgressTracker(hass, entry_id: str, runtime, key_from_state: Callable[[Any], str | None])`:
    - `async_start() -> None` (Store betöltés + poll indítás), `async_stop() -> None` (poll leállítás + azonnali mentés)
    - `start_tracking(entity_id: str, key: str) -> None`, `queue_tracking(key: str) -> None`
    - `clear(key: str) -> None`, `has(key: str) -> bool`, `position(key: str) -> int`
    - `show_names() -> set[str]`, `has_any(keys: Iterable[str]) -> bool`
    - `note_state_change(entity_id: str, old_state: Any, new_state: Any) -> None`
    - `listeners: set[Callable[[], None]]` (attribútum)
  - `const.ACTIVE_PLAYER_STATES = {"playing", "paused", "buffering"}`

- [ ] **Step 1: Írd meg a `progress_tracker.py`-t**

Kulcsdöntések:
- A `progress_tracker.py` futásidőben **semmit** nem importál a csomagból (nincs körkörös import): a kulcs-feloldót (`key_from_state`) és a `runtime`-ot kapja; a típusokat `TYPE_CHECKING` alatt importálja.
- Állapot: `_active: dict[str, str]` (lejátszó → kulcs), `_queued: set[str]`; mindkettő memóriabeli (újraindítás után csak a Store-ból dolgozunk).
- `_async_poll(_now)` a `runtime.watched_players` elemein:
  - `state = hass.states.get(entity_id)`; nincs → tovább.
  - `key = self._key_from_state(state)` csak `state.state in ACTIVE_PLAYER_STATES` esetén.
  - Ha az entitás `_active`-ban van és a `key` más (vagy nincs) → a bejegyzés zárása: `self._active.pop(entity_id)`; a legutóbb mentett pozíció marad.
  - Ha `key` a `_queued`-ben van → `_active[entity_id] = key`, `_queued.discard(key)`.
  - Ha `key` az `_active[entity_id]` → `position = effective_position(state.attributes, state.state, now)`; `None` → tovább (semmit nem írunk); `show_name` a `runtime.media_index.get(key).show_name`-ból (ha nincs a indexben, `""`); `duration = state.attributes.get("media_duration") or 0`.
  - `changed = book.record(key, position, duration, show_name, now)`; ha `changed`, akkor a `listeners` hívása. Ha a `book` már nem tartalmazza a kulcsot (befejezett), az entitás kikerül az `_active`-ból.
  - Mentés: `if self.book.take_dirty(): self._save()` — `_save()` = `store.async_delay_save(self.book.to_payload, PROGRESS_SAVE_DELAY)`. (A `take_dirty` a pozícióváltozást is jelzi, nem csak a kulcshalmazét — enélkül a pozíció soha nem íródna ki.)
  - A `listeners` hívása kizárólag a `record` `True` visszatérésekor történik (kulcshalmaz-változás), hogy ne írjunk entitás-állapotot minden 30. másodpercben.
- `note_state_change`: ha az entitás `_active`-ban van és az új állapot nem aktív, vagy a kulcsa más → a régi állapot `media_position`-jét (ha szám) még mentjük, majd zárás. Ugyanezt hívja a metadata watcher `handle_state_changed`-je.
- `async_start`: `payload = await store.async_load()`; `self.book = ProgressBook.from_payload(payload)`; poll timer `async_track_time_interval(hass, self._async_poll, timedelta(seconds=PROGRESS_POLL_INTERVAL))`; kivétel a load körül → `_LOGGER.warning` + üres könyv.
- `async_stop`: timer le, `await store.async_save(self.book.to_payload())`.
- `queue_tracking`: `_queued.add(key)`, felső korlát 200 (a legrégebbit dobja — `set` helyett `OrderedDict`/lista, a sorrendhez).

- [ ] **Step 2: `__init__.py` — EpisodeInfo és a bekötés**

- `EpisodeInfo` két új mező: `show_name: str = ""`, `timestamp: int = 0`; docstring frissítés.
- `_remember_media(..., show_name: str = "", timestamp: int = 0)`; `register_episode` átadja `show_name`-t és `episode.timestamp`-et; `play_direct_url` marad az alapértéken.
- `TilosRuntimeData.progress: Any = None` (`TYPE_CHECKING` import a típusra, vagy `Any` — a dataclass a modul tetején van).
- `_ACTIVE_PLAYER_STATES` helyett `from .const import ACTIVE_PLAYER_STATES` (a `const.py`-ba új konstans, a 2 használat átírása).
- `async_setup_entry`: a runtime létrehozása után `progress = ProgressTracker(hass, entry.entry_id, runtime, _archive_key_from_state)`; `runtime.progress = progress`; `await progress.async_start()` **a platformok előtt** (hogy az első renderben már látszódjon).
- `async_unload_entry`: `if entry.runtime_data.progress: await entry.runtime_data.progress.async_stop()`.

- [ ] **Step 3: Szintaktikai ellenőrzés**

```bash
python3 -m compileall -q custom_components/tilos_player && uvx ruff check custom_components/tilos_player
```
Várt: nincs kimenet / `All checks passed!`.

- [ ] **Step 4: HA-s füstteszt**

HA újraindítás → a naplóban nincs hiba; a kártyáról indított adás ~30–60 s után megjelenik a `.storage/tilos_player_progress_<entry_id>` fájlban egy `position` bejegyzéssel; a lejátszás leállítása után a bejegyzés megmarad (megszakított adás), a végigjátszott adás bejegyzése eltűnik.

- [ ] **Step 5: Commit**

```bash
git add custom_components/tilos_player/progress_tracker.py custom_components/tilos_player/const.py custom_components/tilos_player/__init__.py
git commit -m "feat: track playback progress every 30 seconds"
```

---

### Task 3: Folytatás a play-flow-ban, `resume` mező, fejléc-jelölők a lejátszón

**Files:**
- Modify: `custom_components/tilos_player/const.py` (`ATTR_RESUME`)
- Modify: `custom_components/tilos_player/__init__.py` (`_patch_player_metadata`, `refresh_player_metadata`, `play_selected_episode`, `PLAY_SERVICE_SCHEMA`/`async_play`)

**Interfaces:**
- Consumes: Task 1 (`format_now_playing`, `effective_position`, `SEEK_*`), Task 2 (`ProgressTracker`, `EpisodeInfo.show_name`/`.timestamp`).
- Produces:
  - `const.ATTR_RESUME = "resume"`
  - `play_selected_episode(hass, runtime, entity_id, enqueue: str | None = None, resume: bool = False) -> None`
  - a lejátszó állapotán: `tilos_key`, `tilos_display`
  - `ProgressTracker.async_seek_when_ready(entity_id: str, key: str, position: int) -> None`

- [ ] **Step 1: Seek a trackerben**

`async_seek_when_ready` (`progress_tracker.py`) — csak akkor indul, ha a lejátszás tényleg elindult (lásd Step 2):
- max `SEEK_WAIT_TIMEOUT` másodpercig 1 s-es lépésben vár, hogy `state.state in ACTIVE_PLAYER_STATES` **és** `key_from_state(state) == key`;
- utána `hass.services.async_call("media_player", "media_seek", {"entity_id": entity_id, "seek_position": position}, blocking=True)` legfeljebb `SEEK_RETRY_COUNT`-szor, `SEEK_RETRY_DELAY` szünettel;
- minden próba után `effective_position(...)` alapján ellenőrizze a `SEEK_TOLERANCE`-ot, siker esetén `return`;
- kudarc → `_LOGGER.warning("Seek to %s s failed on %s", ...)`, nincs kivétel felfelé.

- [ ] **Step 2: Play-flow**

`play_selected_episode` a `register_episode(...)` visszatérési értékét (`key`) használja:
- `tracker = runtime.progress`; ha `key` és `tracker`:
  - `starts_now = enqueue in (None, "play", "replace")`
  - `resume=True` **és** `starts_now` → `position = tracker.position(key)` (0, ha nincs bejegyzés); **nem** töröl;
  - minden más esetben (nincs `resume`, vagy sorba állítás) → `tracker.clear(key)` (a régi idő azonnal eltűnik), `position = 0`;
  - `starts_now` → `tracker.start_tracking(entity_id, key)`, különben `tracker.queue_tracking(key)`.
- a `play_media` hívás(ok) után, ha `starts_now and position > 0`: `hass.async_create_task(tracker.async_seek_when_ready(entity_id, key, position))` — sorba állított tételt nem lehet seekelni.
- `episode is None` / `show is None` korai visszatérés marad.

- [ ] **Step 3: Fejléc-jelölők**

- `_patch_player_metadata` patch-listája bővül: `("tilos_key", info.key)` és `("tilos_display", format_now_playing(info.show_name, info.title, info.timestamp))`; a `hass.bus.async_fire(METADATA_EVENT, …)` payloadja is kapja meg a kettőt.
- `refresh_player_metadata`: ha a lejátszó aktív, de a kulcsról nincs `media_index` bejegyzés, **óvatosan** kell takarítani, mert a patch felülírta a `media_title`-t (egyes lejátszók csak abból adják a fájlnevet, így a kulcs „eltűnhet” anélkül, hogy a média megváltozott volna):
  - `marker = state.attributes.get("tilos_key")`; ha nincs, kész (nincs teendő).
  - `known = runtime.media_index.get(marker)`; ha `known` és `state.attributes.get("media_title") == known.title` és `…(media_artist) == known.artist` → ez még a mi számunk, **marad** a jelölő.
  - különben a lejátszó más médiára váltott → `_clear_player_markers(hass, entity_id, state)`: mindkét jelölőt törli és `hass.states.async_set(entity_id, state.state, attrs)`; ha nincs mit törölni, nem ír (nincs állapot-írás hurok).
  - Ez a szabály kezeli a Spotify/egyéb forrásra váltást (cím/előadó eltér → törlés) és a csak `media_title`-t adó lejátszót is (cím/előadó egyezik → marad).
- A metadata watcher `handle_state_changed`-je hívja a `runtime.progress.note_state_change(entity_id, old_state, new_state)`-et (ha van tracker).

- [ ] **Step 4: Szolgáltatás**

- `PLAY_SERVICE_SCHEMA`: `vol.Optional(ATTR_RESUME, default=False): cv.boolean`.
- `async_play`: `resume = call.data.get(ATTR_RESUME, False)`; `media=episode` esetén `play_selected_episode(..., resume=resume)`; `media=url`/`live` esetén figyelmen kívül marad.

- [ ] **Step 5: Szintaktikai ellenőrzés + HA-s füstteszt**

```bash
python3 -m compileall -q custom_components/tilos_player && uvx ruff check custom_components/tilos_player
```
HA-ban: `select.tilos_radio_episode` kiválaszt → `tilos_player.play` (`entity_id`, `media: episode`) → a lejátszó entitás attribútumai között megjelenik a `tilos_key` és a `tilos_display` (`Műsor – Cím (dátum)`); ugyanezen a lejátszón egy Spotify/egyéb szám indítása után ~15 s-en belül eltűnnek. `resume: true`-val indítva a pozíció a mentett értékre ugrik (a lejátszó `media_position`-je).

- [ ] **Step 6: Commit**

```bash
git add custom_components/tilos_player/const.py custom_components/tilos_player/__init__.py custom_components/tilos_player/progress_tracker.py
git commit -m "feat: resume archive episodes from the stored position"
```

---

### Task 4: Progress az entitás-attribútumokban (kártya bemenet)

**Files:**
- Modify: `custom_components/tilos_player/select.py` (`TilosShowSelect`, `TilosEpisodeSelect`)

**Interfaces:**
- Consumes: `runtime.progress` (`has`, `position`, `show_names`, `has_any`, `listeners`), `saved_episode_key`, `saved_episode_payload`.
- Produces:
  - `TilosEpisodeSelect._labeled_episodes(self) -> list[tuple[str, Episode]]` (az `options`, a `current_option` és az attribútum közös forrása)
  - epizód attribútumok: `episodes: list[{"label": str, "key": str, "progress": bool}]`, a kiválasztottnál `progress: bool`; `_unrecorded_attributes` tartalmazza az `"episodes"`-t is
  - műsor attribútumok: `shows: list[{"id", "name", "type", "progress": bool}]`, `saved_progress: bool`

- [ ] **Step 1: Epizód select**

- `_labeled_episodes()`: a jelenlegi `options` címke-dedup logikája (a `f"{label} ({count})"` toldással) egy helyre; `options` → `[label for label, _ in self._labeled_episodes()]`.
- `extra_state_attributes`: `episodes` lista a fenti alakban; a `key` a `saved_episode_key(episode)`, a `progress` `bool(key and progress and progress.has(key))`.
- a kiválasztott epizód mellett `attrs["progress"] = …` ugyanígy.
- `async_added_to_hass`: `self._runtime.progress.listeners.add(self._handle_progress_changed)`; `async_will_remove_from_hass`: `discard`; a handler `self.async_write_ha_state()`.

- [ ] **Step 2: Műsor select**

- `shows` elemei kapnak `"progress": show.name in progress_names`-t (`progress_names = progress.show_names()`), a `saved_progress` pedig `progress.has_any(saved_episode_key(ep) for ep in self._runtime.saved_episodes.values())`.
- ugyanaz a listener-hozzáadás/levétel, mint az epizód selectnél (a meglévő `_handle_saved_episodes_changed` mintájára).

- [ ] **Step 3: Ellenőrzés**

```bash
python3 -m compileall -q custom_components/tilos_player && uvx ruff check custom_components/tilos_player
```
HA → Fejlesztőeszközök → Állapotok: `select.tilos_radio_episode` attribútumaiban ott az `episodes` lista (label + key + progress), `select.tilos_radio_show` attribútumaiban a `shows[].progress` és a `saved_progress`. Félbeszakított adás után a megfelelő elem `progress: true`.

- [ ] **Step 4: Commit**

```bash
git add custom_components/tilos_player/select.py
git commit -m "feat: expose playback progress to the card"
```

---

### Task 5: Kártya — borító fejléc

**Files:**
- Modify: `custom_components/tilos_player/www/tilos-player-card.js` (`setConfig`, `_render` CSS + markup, `_update`, új `_updateCover`/`_playingInfo`, editor séma és feliratok)

**Interfaces:**
- Consumes: a lejátszó állapotának `tilos_key` / `tilos_display` / `entity_picture` mezői; a meglévő `_targetPlayer()`, `hassUrl()`.
- Produces (Task 6 használja): `_playingInfo() -> {image: string, text: string} | null`.

- [ ] **Step 1: Config és szerkesztő**

- `setConfig` alapérték: `show_cover: false`.
- `EDITOR_LABELS.show_cover = "Borító megjelenítése"`; `EDITOR_HELPERS.show_cover` = „Bekapcsolva a kártya tetején a most szóló adás borítója látszik a logó helyett, alatta a műsor neve és az epizód címe. Lejátszás nélkül a logó marad.”
- `_schema()` új elem: `{ name: "show_cover", selector: { boolean: {} } }` (a `link_player` után).

- [ ] **Step 2: Markup és CSS**

A `<img class="logo" alt="Tilos Rádió">` **elé** kerül:

```html
<div class="cover" hidden>
  <img class="cover-image" alt="">
  <div class="cover-text"></div>
</div>
```

CSS (a `.logo` szabályai után): `.cover { margin-bottom: 16px; }`, `.cover[hidden], .logo[hidden] { display: none; }` (a `[hidden]` nem érvényesül `display:block` mellett), `.cover-image { display:block; width:100%; height:auto; max-height:220px; object-fit:cover; border-radius:8px; }`, `.cover-text { margin-top:10px; color:#fff; font-size:19px; font-weight:600; line-height:1.3; }` — a `#fff` azért, mert a kártya háttere fix fekete (a többi szöveg fehér dobozon ül).

- [ ] **Step 3: Frissítés**

`_playingInfo()`: `_targetPlayer()` → state; `null`, ha nincs state, ha `state.state` nem `playing|paused|buffering`, vagy ha nincs `attributes.tilos_key`; egyébként `{ image: attributes.entity_picture || "", text: attributes.tilos_display || attributes.media_title || "" }`; üres `text` esetén `null`.

`_updateCover()`: `info = this._config.show_cover ? this._playingInfo() : null`; a `.logo` `hidden = Boolean(info)`, a `.cover` `hidden = !info`; ha van info, a kép `src`-je `hassUrl()`-vel, ha `/`-lel kezdődik, különben nyersen; a szöveg `textContent`-tel (csak ha változott).

`_update()` végén: `this._updateCover();`.

- [ ] **Step 4: Ellenőrzés**

```bash
node --check custom_components/tilos_player/www/tilos-player-card.js
```
HA-ban: kapcsoló be → archív adás indítása a kártyáról: a logó helyén a borító, alatta `Műsor – Cím (dátum)`; pause → marad; stop/befejezés → vissza a logóra; másik (nem Tilos) médiára váltás → max ~15 s alatt logó; kapcsoló ki → mindig logó; élő adás → logó.

- [ ] **Step 5: Commit**

```bash
git add custom_components/tilos_player/www/tilos-player-card.js
git commit -m "feat: show the playing episode cover at the top of the card"
```

---

### Task 6: Kártya — listaikonok és Előről/Folytatás gombok

**Files:**
- Modify: `custom_components/tilos_player/www/tilos-player-card.js` (`_createOption`, `_renderFlatOptions`, `_renderShowOptions`, `_update`, `_callTilosPlay`, `_playSource`, gomb-markup és kattintáskezelő, ikon konstansok)

**Interfaces:**
- Consumes: `select.tilos_radio_episode` `episodes[].progress` / `progress` attribútum; `select.tilos_radio_show` `shows[].progress` / `saved_progress`; `tilos_player.play` `resume` mezője; `_playingInfo()` (nem kötelező).
- Produces: `_progressLabels() -> Set<string>`, `_selectedProgress(episodeState) -> boolean`, `_updateActionButtons(episodeState) -> void`.

- [ ] **Step 1: Ikon és opció-sor**

- Új konstans: `const PROGRESS_PATH = "M12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M10,16.5L16,12L10,7.5V16.5Z";`
- CSS: `.dropdown-option-progress { flex:0 0 auto; width:18px; height:18px; margin-right:8px; display:inline-flex; align-items:center; justify-content:center; }` + `svg { width:16px; height:16px; fill:currentColor; }`.
- `_createOption(value, label, { selected, favorite, bookmark, progress })`: a csillag/könyvjelző slot **után** mindig beszúr egy `.dropdown-option-progress` span-t; ikont csak `progress === true` esetén.
- `_progressLabels()`: az epizód select `attributes.episodes` listájából a `label`-ek halmaza, ahol `progress === true`.
- `_renderFlatOptions`: `progress: this._progressLabels().has(String(option))`.
- `_renderShowOptions`: a műsor soroknál `progress: progressNames.has(name)` (a `shows` attribútum `progress` mezőjéből); a „Mentett epizódok” sornál `progress: showState.attributes.saved_progress === true`.

- [ ] **Step 2: Gombok**

- A Lejátszás gomb után a markupban:
  - `<button class="action-button restart" data-action="restart" type="button" hidden>` — ikon `M12,5V1L7,6L12,11V7A6,6 0 0,1 18,13A6,6 0 0,1 12,19A6,6 0 0,1 6,13H4A8,8 0 0,0 12,21A8,8 0 0,0 20,13A8,8 0 0,0 12,5Z`, felirat `Előről`;
  - `<button class="action-button resume" data-action="resume" type="button" hidden>` — ikon a meglévő play-path (`M8 5v14l11-7z`), felirat `Folytatás`.
- A `.buttons` inline `grid-template-columns` a markupból ki, a `_updateActionButtons` állítja.
- `_selectedProgress(episodeState)`: `true`, ha `this._selectedEpisode !== null`, `episodeState && String(episodeState.state) === String(this._selectedEpisode)`, és `episodeState.attributes.progress === true`.
- `_updateActionButtons(episodeState)`:
  - `const resumable = this._selectedProgress(episodeState)`;
  - `.play` `hidden = resumable`; `.restart`, `.resume` `hidden = !resumable`;
  - a látható gombok száma szerint `style.gridTemplateColumns = repeat(n >= 4 ? 2 : n, 1fr)`;
  - a `restart`/`resume` engedélyezése pontosan a mai `play` feltétel: `!this._targetPlayer() || this._linkInvalid() || (this._selectedEpisode === null && this._linkUrl().length === 0)`.
- Kattintáskezelő: `restart` → `this._playSource(this._isMusicAssistant() ? "play" : undefined, false)`; `resume` → ugyanez `true`-val; a `play`/`queue`/`live` ágak változatlanok.
- `_callTilosPlay(media, enqueue, resume)` és `_playSource(enqueue, resume)`: `resume` igaz esetén `data.resume = true`; a link-ág (`_callTilosPlayUrl`) változatlan.
- `_update()` hívja: `this._updateActionButtons(episodeState)`.

- [ ] **Step 3: Ellenőrzés**

```bash
node --check custom_components/tilos_player/www/tilos-player-card.js
```
HA-ban: félbehagyott adás után a műsor- és az epizódsorban ikon; az epizód kiválasztva `Lejátszás` helyett `Előről` + `Folytatás` (HA mód: 3 gomb egy sorban, MA mód: 4 gomb 2×2-ben); `Folytatás` a mentett pozíciótól indul; `Előről` az elejéről, és az ikon eltűnik; végigjátszás után a gombpár visszavált `Lejátszás`-ra; másik műsor kiválasztva szintén.

- [ ] **Step 4: Commit**

```bash
git add custom_components/tilos_player/www/tilos-player-card.js
git commit -m "feat: resume buttons and in-progress markers in the card"
```

---

### Task 7: Dokumentáció, szolgáltatás-leírás, verzió

**Files:**
- Modify: `custom_components/tilos_player/services.yaml` (`play.resume`)
- Modify: `custom_components/tilos_player/strings.json`, `custom_components/tilos_player/translations/en.json` (ha a `play` mezők ott szerepelnek)
- Modify: `README.md` (Fícsörök + kártya-beállítások)
- Modify: `custom_components/tilos_player/manifest.json` (`"version": "1.7.0"`)

**Interfaces:**
- Consumes: Task 3 `resume` mező, Task 5–6 UI.
- Produces: semmi kód-API.

- [ ] **Step 1: `services.yaml`**

A `play` alá:

```yaml
    resume:
      name: Resume
      description: >-
        Compare with "Előről": when true, playback starts from the stored
        position of the selected episode (ignored for media: url/live and
        for queued items). Without it the episode starts from the beginning
        and the stored position is dropped.
      required: false
      default: false
      selector:
        boolean:
```

- [ ] **Step 2: README**

- „Fícsörök” közé: borító fejléc (kapcsolható) és folytatható lejátszás (Előről/Folytatás, félpercenkénti mentés, ikon a listában).
- A kártya-beállítások felsorolásába: `show_cover` (opcionális, alapból `false`).
- Egy rövid bekezdés arról, hogy a pozíció a `.storage/tilos_player_progress_<entry_id>` fájlban van, csak az innen indított epizódokra, és hogy a végigjátszott adás bejegyzése törlődik.

- [ ] **Step 3: Verzió és ellenőrzés**

`manifest.json` → `"version": "1.7.0"`.

```bash
python3 -m compileall -q custom_components/tilos_player
uvx ruff check custom_components/tilos_player
node --check custom_components/tilos_player/www/tilos-player-card.js
python3 -c "import json;json.load(open('custom_components/tilos_player/manifest.json'));json.load(open('custom_components/tilos_player/strings.json'))"
```
Várt: mind hibátlan; a hassfest/HACS workflow zöld marad.

- [ ] **Step 4: Commit**

```bash
git add README.md custom_components/tilos_player/services.yaml custom_components/tilos_player/strings.json custom_components/tilos_player/translations/en.json custom_components/tilos_player/manifest.json
git commit -m "docs: document the cover header and resume playback"
```

---

## Self-Review

- **Spec lefedettség:** fejléc kapcsoló (5), szövegformátum (1, 3), visszaállás leálláskor (3, 5), progress Store + 30 s poll (1, 2), csak innen indított (2, 3), mentett + sima epizód (1 kulcs-alapú), ikon a műsor- és epizódsorban (4, 6), Előről/Folytatás (3, 6), 3 vs 4 gomb (6), szolgáltatás + dokumentáció (3, 7). Élő adás/link kizárva (3).
- **Lépés-pásztázás:** minden lépés egyetlen írható dolog; a `progress.py` törzse signature-ökből és tesztelből áll, nem kódmásolat.
- **Típus-konzisztencia:** `ProgressBook.has/position/show_names/has_any/record/clear/take_dirty` és `ProgressTracker.start_tracking/queue_tracking/clear/has/position/show_names/has_any/async_seek_when_ready/note_state_change` ugyanazokban a taskokban, ahol felhasználásra kerülnek; `_labeled_episodes`, `_progressLabels`, `_selectedProgress`, `_updateActionButtons`, `_updateCover`, `_playingInfo` egyszer definiálva.
- **Review Focus:** mind az öt sorhoz tartozik teszt a Task 1-ben (lásd a szakasz végén a hivatkozásokat).
