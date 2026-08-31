# Tilos Radio Player (Home Assistant custom component)

A Tilos Rádió archívumából közvetlen lejátszás a Home Assistantban a megadott media player entitáson keresztül.

## Fícsörök
- Műsor választás (zenei a lista elején, beszélgetősek a végén ABC sorrendben)
- Epizód választás cím alapján az utolsó 4 hónapból
- Lejátszás az archívum gombbal, az élő műsort is lehet hallgatni.

## Villantás
![well](imgs/preview.png)

## Hozd magaddal
Bubble Card-ot érdemes feltenni a HACS-ból, mert szép legörülőket tud prezentálni, a villantós képen is azzal látszik. Nélküle is megy, de úgy meh...

## Felpattintás
- Repo klónozása/letöltése
- A HA könyvtárába a custom_components és a www mappa bemásolása. Utóbbiban a logó van.
- HA újraindítása
- Új integráció hozzáadása, Tilos Radio Player. A lejátszó entitást kell beállítani.
- A kártya beállítása (kód alább)
- Műsorlista frissítése (újraindításkor és 12 óránként lefut), műsor választás, lejátszás.
- Örvendezés a remek muzsikáknak :)

## 🂡 Pikk Ász
A kártya yaml fájlja alant, kézi hozzáadás.

```
type: vertical-stack
cards:
  - type: picture
    image: /local/tilos_player/tilos_logo.jpg
    tap_action:
      action: none
    hold_action:
      action: none
  - type: custom:bubble-card
    card_type: select
    entity: select.tilos_radio_show
    name: Műsor választó
    icon: mdi:radio
    icon_color: grey
    show_state: true
  - type: custom:bubble-card
    card_type: select
    entity: select.tilos_radio_episode
    name: Epizód választó
    icon: mdi:playlist-music
    icon_color: grey
    show_state: true
  - type: horizontal-stack
    cards:
      - type: custom:mushroom-template-card
        entity: button.tilos_radio_reload_shows
        primary: Műsorlista
        icon: mdi:refresh
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.tilos_radio_reload_shows
        color: grey
        features_position: bottom
        vertical: true
        card_mod:
          style: |
            ha-card {
              border-radius: 16px;
              {% if is_state('button.tilos_radio_reload_shows', 'unavailable') %}
              opacity: 0.4;
              {% endif %}
            }
      - type: custom:mushroom-template-card
        entity: button.tilos_radio_play
        primary: Archívum
        icon: mdi:play
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.tilos_radio_play
        color: black
        features_position: bottom
        vertical: true
        card_mod:
          style: |
            ha-card {
              border-radius: 16px;
              {% if is_state('button.tilos_radio_play', 'unavailable') %}
              opacity: 0.4;
              {% endif %}
            }
      - type: custom:mushroom-template-card
        entity: button.tilos_radio_live
        primary: ÉLŐ
        icon: mdi:radio
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.tilos_radio_live
        color: red
        features_position: bottom
        vertical: true
        card_mod:
          style: |
            ha-card {
              border-radius: 16px;
            }
```
> [!TIP]
> A szakasz színének feketére állításával lehet elérni a fenti kinézetet. Ezt utólag kell beállítani az adott szakaszra ahol a kártya van. Szakasz szerkesztése, háttér szín fekete, átlátszóság 100%.

<small>Disclaimer: Természetesen AI-val készült, GLM 5.3 Flash volt az elkövető. Korábban összeraktam ezt sh scriptekkel és egyéb patkolásokkal, ez az átírat arra alapul, hogy könnyebben megosztható legyen.</small>
