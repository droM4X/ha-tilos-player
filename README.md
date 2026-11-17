# Tilos Radio Player (Home Assistant custom component)
![GitHub releases](https://img.shields.io/github/v/release/droM4X/ha-tilos-player?style=for-the-badge)
![GitHub last release](https://img.shields.io/github/release-date/droM4X/ha-tilos-player?style=for-the-badge)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/droM4X/ha-tilos-player?style=for-the-badge)
![GitHub License](https://img.shields.io/github/license/droM4X/ha-tilos-player?style=for-the-badge)


A Tilos Rádió archívumából közvetlen lejátszás a Home Assistantban a megadott media player entitáson keresztül, saját kártyával.

## Fícsörök
- Műsor választás az összes archivált adásból (kedvencek elöl, majd zenei és beszélgetős műsorok csoportban ABC sorrendben) + élő műsor
- Kedvenc műsorok csillagozása a műsor info gomb alatt, a műsorlista elejére kerülnek
- Epizód mentése későbbre, külön listából választhatóan
- Műsorleírás megjelenítése (műsor infó gomb) és epizód műsorleírás / tracklista megjelenítése
- Közvetlen mp3 link lejátszása (opcionális)
- Lejátszó lista támogatása (csak Music Assistant esetén)
- Borító megjelenítése a kártya tetején (kapcsolható, `show_cover`, alapból kikapcsolt): archív epizód lejátszásakor a borító és a `Műsor – Cím (dátum)` sor van a fejlécben, máskor a logó marad
- Folytatható lejátszás: a félbehagyott archív adás a mentett pozícióról indul vissza — félpercenként mentjük a pozíciót, a listákban ikon jelzi, ahol van ilyen, az epizód kiválasztásakor a Lejátszás gomb helyett **Előről** / **Folytatás** pár van
- HACS-ból is telepíthető, egyedi integrációként, így később tud frissülni.
- Saját Lovelace kártya vizuális (interaktív) szerkesztővel és YAML móddal.

## Villantás
#### A kártya
![Kártya előnézet](assets/card-preview.png)

## Felpattintás
### HACS-al
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=droM4X&repository=ha-tilos-player&category=integration)

- A HACS legyen feltelepítve
- Oldalsó sávban: HACS, jobbra fent 3 pötty majd: Egyedi repók
- A felbukkanó ablakban: 
  - Repó megnyitása: `droM4X/ha-tilos-player`
  - Típus: `Integráció`
- Hozzáadás után HA újraindítása

### Manuálisan
- Repo klónozása/letöltése
- A HA könyvtárába a custom_components mappa bemásolása
- HA újraindítása

## Bekonfig
- Új integráció hozzáadása, Tilos Radio Player. A lejátszó entitást kell beállítani.
- A felületen kártya hozzáadása: Tilos Player Card
- A kártya beállításainál (vizuális szerkesztő vagy YAML) az alábbiakat lehet megadni:
  - **Integráció típusa**: Home Assistant vagy Music Assistant
  - **Média lejátszó entitás**: ezen a lejátszón futnak a kártya gombjai
  - **Link lejátszó**: közvetlen mp3 lejátszás vagy várólistára adás linkről
  - **Borító megjelenítése** (`show_cover`): opcionális, alapból `false` — a kártya tetején az éppen lejátszott archív epizód borítója és a `Műsor – Cím (dátum)` sor látszik a logó helyett (szünet alatt is megmarad)
- A műsorlista induláskor és 12 óránként automatikusan frissül.
- Műsor választás, lejátszás.
- Örvendezés a remek muzsikáknak :)

### Epizód mentése későbbre
Az archív epizódlista csak a beállított időablakban (alapból 4 hónap) lévő epizódokat mutatja, de a lejátszható mp3-k nem tűnnek el. Az info gomb megnyomásakor a lenyíló rész első sora egy gomb:

- **Mentés későbbre** – elmenti az epizódot minden adatával együtt (cím, leírás/tracklista, műsor neve, borító, mp3 link). Mentés után a sor felirata **Eltávolítás a mentettek közül** lesz, amivel vissza is lehet venni.
- Amíg van mentett epizód, a **Műsor** legördülő legelső eleme a **Mentett epizódok** (könyvjelző ikonnal). Kiválasztásakor az **Epizód** legördülő csak a mentett epizódokat listázza — a műsor nevével együtt, a legfrissebb elöl —, és onnan a szokásos Lejátszás / Sorba gombokkal indítható.

A mentett lista a `sensor.tilos_radio_saved_episodes` entitásban van (állapota a darabszám), a mentett epizódok adatai pedig fájlban, így újraindítás után is megmaradnak. Automatizáláshoz a `tilos_player.save_episode` / `tilos_player.remove_saved_episode` szolgáltatások használhatók (az epizód select `save_key` attribútumában lévő kulccsal, vagy üresen a kiválasztott epizódra).

### Folytatható lejátszás

A pozíció a `.storage/tilos_player_progress_<entry_id>` fájlban van, így újraindítás után is megmarad. Félpercenként (30 másodpercenként) mérjük a lejátszó pozícióját, és csak folytatásra érdemes pozíciót tartunk meg: egy végigjátszott adás bejegyzése törlődik, egy félbehagyott viszont folytatás marad.

- Csak az ezen a kártyán indított epizódokhoz tartozik mentett pozíció (a mentett epizódok is), az élő adás és a link lejátszó soha.
- A kártyán az **Előről** gomb viszi az epizód elejére (a bejegyzést törli), a **Folytatás** a mentett pozícióról indul. Az ikon a műsor- és epizódsorban jelzi, hogy mely epizódhoz van mentett pozíció.
- Automatizáláshoz a `tilos_player.play` `resume: true` mezővel hívható ugyanez (a `url`/`live` mediákra és a csak sorba adott epizódra nem vonatkozik).
- A fejléc és az epizódsor ugyanazt az UTC dátum-formátumot használja (`YYYY.MM.DD.`), a zóna beállításától függetlenül.

### Minimális kézi config
```
type: custom:tilos-player-card
media_player: media_player.lejatszo   # a lejátszásra használt media_player entitás
integration_type: home_assistant      # integráció típusa (opciók: home_assistant|music_assistant)
link_player: false                    # link lejátszó megjelenítése (opciók: true|false)
```

---
<small>Disclaimer: Csak egy lelkes hallgatói megoldás, semmilyen kapcsolatban nem voltam/vagyok a rádióval, nem volt semmi ráhatásuk erre a projectre. Természetesen nagy nyelvi modellekkel (ami továbbra sem ai) készült (DS 4.1 Flash, GPT 5.6 Luna, GLM 5.3 Flash). Korábban összeraktam ezt sh scriptekkel és egyéb patkolásokkal, ez az átírat arra alapul, hogy könnyebben megosztható legyen.</small>
