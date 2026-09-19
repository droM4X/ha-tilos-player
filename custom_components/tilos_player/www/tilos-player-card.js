/*
 * Kedvencek és a műsorlista csoportosítása.
 *
 * A kedvenc műsorok ID-ját a backend sensor
 * entitása tárolja, a név -> típus -> id
 * leképezést pedig a show select "shows"
 * attribútuma adja.
 */
const STAR_FILLED_PATH =
  "M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z";

const STAR_OUTLINE_PATH =
  "M12,15.39L8.24,17.66L9.23,13.38L5.91,10.5L10.29,10.13L12,6.09L13.71,10.13L18.09,10.5L14.77,13.38L15.76,17.66M22,9.24L14.81,8.63L12,2L9.19,8.63L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z";

const FAVORITES_GROUP_LABEL =
  "Kedvencek";

/* A típuscsoportok sorrendje a listában. */
const SHOW_TYPE_GROUPS = [
  {
    type: "MUSIC",
    label: "Zenei műsorok",
  },
  {
    type: "SPEECH",
    label: "Beszélgetős műsorok",
  },
];

class TilosPlayerCard extends HTMLElement {
  constructor() {
    super();

    this.attachShadow({ mode: "open" });

    this._hass = null;
    this._config = {};

    // A kártya saját UI-állapota.
    this._selectedShow = null;
    this._selectedEpisode = null;

    // Az entity state-ekből csak egyszer,
    // a kártya inicializálásakor állítjuk vissza
    // a kiválasztást.
    this._selectionInitialized = false;

    this._openDropdown = null;
    this._activeMenu = null;

    this._documentPointerDown = null;
    this._boundReposition = null;
    this._boundKeyDown = null;
  }

  setConfig(config) {
    this._config = {
      show_entity: "select.tilos_radio_show",
      episode_entity: "select.tilos_radio_episode",
      favorites_entity: "sensor.tilos_radio_favorites",
      reload_entity: "button.tilos_radio_reload_shows",
      play_entity: "button.tilos_radio_play",
      live_entity: "button.tilos_radio_live",
      logo: "/api/brands/integration/tilos_player/logo.png",
      ...config,
    };

    this._render();
  }

  set hass(hass) {
    this._hass = hass;

    if (!this._config) {
      return;
    }

    if (!this.shadowRoot.querySelector(".card")) {
      this._render();
      return;
    }

    this._update();
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 6;
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    this._closeDropdown();
  }

  _render() {
    if (!this._hass || !this._config) {
      return;
    }

    this._closeDropdown();

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          overflow: visible;
        }

        .card {
          position: relative;
          overflow: visible;
          box-sizing: border-box;

          padding: 16px;

          border-radius: var(--ha-card-border-radius, 12px);

          /* Csak maga a kártya fekete. */
          background: #000;
          color: var(--primary-text-color, #212121);
          box-shadow: var(--ha-card-box-shadow, none);
        }

        .logo {
          display: block;
          width: 100%;
          height: auto;
          margin-bottom: 16px;
          border-radius: 8px;
        }

        .selectors {
          display: flex;
          flex-direction: column;
          gap: 10px;
          margin-bottom: 12px;
        }

        .dropdown {
          position: relative;
          width: 100%;
        }

        /* Csillag + műsor választó egy sorban. */
        .show-row {
          display: flex;
          align-items: stretch;
          gap: 10px;
        }

        .show-row .dropdown {
          flex: 1;
          min-width: 0;
        }

        .favorite-button {
          flex: 0 0 auto;

          width: 52px;
          min-height: 52px;

          box-sizing: border-box;

          display: flex;
          align-items: center;
          justify-content: center;

          padding: 0;

          border: 1px solid var(--divider-color, #ddd);
          border-radius: 8px;

          background: var(--card-background-color, #d9d9d9);
          color: var(--secondary-text-color, #757575);

          cursor: pointer;

          transition:
            background-color 0.15s ease,
            color 0.15s ease,
            border-color 0.15s ease;
        }

        .favorite-button:hover:not(:disabled) {
          background: var(--secondary-background-color, #d9d9d9);
        }

        .favorite-button:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        .favorite-button:disabled {
          opacity: 0.5;
          cursor: default;
        }

        .favorite-button.active {
          color: var(--warning-color, #ffa726);
          border-color: var(--warning-color, #ffa726);
        }

        .favorite-button svg {
          width: 26px;
          height: 26px;

          fill: currentColor;
        }

        .dropdown-button {
          width: 100%;
          min-height: 52px;

          box-sizing: border-box;

          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;

          padding: 7px 14px;

          border: 1px solid var(--divider-color, #ddd);
          border-radius: 8px;

          background: var(--card-background-color, #d9d9d9);
          color: var(--primary-text-color, #212121);

          font: inherit;
          text-align: left;

          cursor: pointer;

          transition:
            background-color 0.15s ease,
            border-color 0.15s ease;
        }

        .dropdown-button:hover {
          background: var(--secondary-background-color, #d9d9d9);
        }

        .dropdown-button:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        .dropdown-button.disabled {
          opacity: 0.5;
          cursor: default;
        }

        .dropdown-content {
          min-width: 0;
          flex: 1;
          overflow: hidden;

          display: flex;
          flex-direction: column;
          justify-content: center;
        }

        .dropdown-caption {
          display: block;
          margin-bottom: 1px;

          font-size: 12px;
          font-weight: 700;
          line-height: 1.15;

          color: var(--primary-text-color, #212121);
        }

        .dropdown-value {
          min-width: 0;
          width: 100%;
          overflow: hidden;

          font-size: 14px;
          line-height: 1.35;
        }

        .dropdown-label {
          display: block;
          width: 100%;

          overflow: hidden;
          white-space: nowrap;

          font-size: 14px;
          line-height: 1.35;

          color: var(--primary-text-color, #212121);
        }

        .dropdown-label.placeholder {
          color: var(--secondary-text-color, #757575);
        }

        .dropdown-label.marquee {
          overflow: hidden;
        }

        .marquee-track {
          display: flex;
          width: max-content;

          white-space: nowrap;
          will-change: transform;

          animation:
            dropdown-marquee
            var(--marquee-duration, 12s)
            linear
            infinite;
        }

        .marquee-item {
          flex: 0 0 auto;
          white-space: nowrap;
        }

        .marquee-gap {
          width: 10px;
          flex: 0 0 10px;
          text-align: center;
        }

        .marquee-gap::after {
          content: "|";
        }

        @keyframes dropdown-marquee {
          from {
            transform: translateX(0);
          }

          to {
            transform: translateX(
              var(--marquee-distance)
            );
          }
        }

        .dropdown-arrow {
          flex: 0 0 auto;

          width: 0;
          height: 0;

          border-left: 5px solid transparent;
          border-right: 5px solid transparent;
          border-top: 6px solid currentColor;

          transition: transform 0.15s ease;
        }

        .dropdown.open .dropdown-arrow {
          transform: rotate(180deg);
        }

        .dropdown-menu {
          position: fixed;
          z-index: 999999;

          box-sizing: border-box;
          overflow-y: auto;

          padding: 4px;

          border: 1px solid var(--divider-color, #ddd);
          border-radius: 8px;

          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);

          box-shadow:
            0 4px 12px rgba(0, 0, 0, 0.18),
            0 1px 3px rgba(0, 0, 0, 0.12);

          scrollbar-width: thin;
        }

        .dropdown-option {
          width: 100%;
          min-height: 42px;

          box-sizing: border-box;

          display: flex;
          align-items: center;

          padding: 9px 12px;

          border: 0;
          border-radius: 6px;

          background: transparent;
          color: var(--primary-text-color, #212121);

          font: inherit;
          font-size: 15px;
          line-height: 1.3;
          text-align: left;

          cursor: pointer;
        }

        .dropdown-option:hover {
          background: var(--secondary-background-color, #f5f5f5);
        }

        .dropdown-option.selected {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .dropdown-option.selected:hover {
          background: var(--primary-color);
        }

        /* optgroup-szerű csoportcím a listában. */
        .dropdown-group-label {
          position: sticky;
          top: 0;
          z-index: 1;

          padding: 8px 12px 4px;

          background: var(--card-background-color, #fff);
          color: var(--secondary-text-color, #757575);

          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .dropdown-group-label:first-child {
          padding-top: 4px;
        }

        /* A csillag helye minden műsor sorban foglalt. */
        .dropdown-option-star {
          flex: 0 0 auto;

          width: 18px;
          height: 18px;

          margin-right: 8px;

          display: inline-flex;
          align-items: center;
          justify-content: center;
        }

        .dropdown-option-star svg {
          width: 16px;
          height: 16px;

          fill: currentColor;
        }

        .dropdown-option-label {
          flex: 1;
          min-width: 0;
        }

        .buttons {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 10px;
        }

        .action-button {
          min-height: 76px;

          display: flex;
          align-items: center;
          justify-content: center;
          flex-direction: column;
          gap: 6px;

          padding: 8px 10px;

          border: 1px solid var(--divider-color, #ddd);
          border-radius: 8px;

          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);

          font: inherit;
          font-size: 14px;
          font-weight: 500;

          cursor: pointer;

          transition:
            background-color 0.15s ease,
            opacity 0.15s ease;
        }

        .action-button:hover {
          background: var(--secondary-background-color, #f5f5f5);
        }

        .action-button:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        .action-button:disabled {
          opacity: 0.5;
          cursor: default;
        }

        .action-button.live {
          color: var(--error-color, #db4437);
        }

        .action-button.play {
          color: var(--primary-text-color, #212121);
        }

        .icon {
          width: 32px;
          height: 32px;

          flex: 0 0 32px;

          display: inline-flex;
          align-items: center;
          justify-content: center;

          border-radius: 50%;

          background: var(--secondary-background-color, #eeeeee);
          color: inherit;
        }

        .icon svg {
          width: 24px;
          height: 24px;

          fill: currentColor;
        }
      </style>

      <ha-card class="card">
        <img class="logo" alt="Tilos Rádió">

        <div class="selectors">
          <div class="show-row">
            <button
              class="favorite-button"
              type="button"
              disabled
              aria-pressed="false"
              title="Hozzáadás a kedvencekhez"
            >
              <svg viewBox="0 0 24 24">
                <path d="${STAR_OUTLINE_PATH}"/>
              </svg>
            </button>

            <div
              class="dropdown"
              data-entity="${this._config.show_entity}"
            >
              <button class="dropdown-button" type="button">
                <span class="dropdown-content">
                  <span class="dropdown-caption">
                    Műsor
                  </span>

                  <span class="dropdown-value">
                    <span
                      class="dropdown-label placeholder"
                      data-text="Válassz műsort..."
                    >
                      Válassz műsort...
                    </span>
                  </span>
                </span>

                <span class="dropdown-arrow"></span>
              </button>
            </div>
          </div>

          <div
            class="dropdown"
            data-entity="${this._config.episode_entity}"
          >
            <button
              class="dropdown-button disabled"
              type="button"
              disabled
            >
              <span class="dropdown-content">
                <span class="dropdown-caption">
                  Epizód
                </span>

                <span class="dropdown-value">
                  <span
                    class="dropdown-label placeholder"
                    data-text="Válassz epizódot..."
                  >
                    Válassz epizódot...
                  </span>
                </span>
              </span>

              <span class="dropdown-arrow"></span>
            </button>
          </div>
        </div>

        <div class="buttons">
          <button
            class="action-button"
            data-entity="${this._config.reload_entity}"
            type="button"
          >
            <span class="icon">
              <svg viewBox="0 0 24 24">
                <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
              </svg>
            </span>
            <span>Frissítés</span>
          </button>

          <button
            class="action-button play"
            data-entity="${this._config.play_entity}"
            type="button"
          >
            <span class="icon">
              <svg viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z"/>
              </svg>
            </span>
            <span>Lejátszás</span>
          </button>

          <button
            class="action-button live"
            data-entity="${this._config.live_entity}"
            type="button"
          >
            <span class="icon">
              <svg viewBox="0 0 24 24">
                <path d="M20 7.5v9A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-9A2.5 2.5 0 0 1 6.5 5h11A2.5 2.5 0 0 1 20 7.5ZM7 8.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm4 0v3h6v-3h-6Zm-4 5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm4 0v3h6v-3h-6ZM7 2h1v2H7V2Zm4-1h2v3h-2V1Zm5 1h1v2h-1V2Z"/>
              </svg>
            </span>
            <span>Élő adás</span>
          </button>
        </div>
      </ha-card>
    `;

    const logo =
      this.shadowRoot.querySelector(".logo");

    if (logo && this._config.logo) {
      logo.src =
        this._hass.hassUrl(this._config.logo);
    }

    this.shadowRoot
      .querySelectorAll(".dropdown")
      .forEach((dropdown) => {
        const button =
          dropdown.querySelector(
            ".dropdown-button"
          );

        button.addEventListener(
          "click",
          (event) => {
            event.stopPropagation();
            this._toggleDropdown(dropdown);
          }
        );
      });

    const favoriteButton =
      this.shadowRoot.querySelector(
        ".favorite-button"
      );

    if (favoriteButton) {
      favoriteButton.addEventListener(
        "click",
        (event) => {
          event.stopPropagation();
          this._toggleFavorite();
        }
      );
    }

    this.shadowRoot
      .querySelectorAll(".action-button")
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            const entityId =
              button.dataset.entity;

            if (
              !entityId ||
              button.disabled
            ) {
              return;
            }

            this._hass.callService(
              "button",
              "press",
              {
                entity_id: entityId,
              }
            );
          }
        );
      });

    this._update();
  }

  _update() {
    if (!this._hass) {
      return;
    }

    const showState =
      this._hass.states[
        this._config.show_entity
      ];

    const episodeState =
      this._hass.states[
        this._config.episode_entity
      ];

    /*
     * A kártya első inicializálásakor
     * visszaolvassuk az entity-kből az aktuális
     * kiválasztást.
     */
    if (!this._selectionInitialized) {
      this._syncSelectionFromEntities(
        showState,
        episodeState
      );
    }

    this._updateShowDropdown(
      showState
    );

    this._updateFavoriteButton(
      showState
    );

    this._updateEpisodeDropdown(
      episodeState
    );

    this.shadowRoot
      .querySelectorAll(".action-button")
      .forEach((button) => {
        const entityId =
          button.dataset.entity;

        const state =
          entityId
            ? this._hass.states[entityId]
            : null;

        /*
         * PLAY:
         *
         * A button entity állapota nem dönthet arról,
         * hogy a gomb használható-e.
         *
         * A Tilos Play button "unknown" lehet,
         * illetve a backend runtime állapotától függően
         * unavailable is lehet, miközben a frontendben
         * már megvan az epizód.
         */
        if (
          entityId ===
          this._config.play_entity
        ) {
          button.disabled =
            this._selectedEpisode === null;

          return;
        }

        /*
         * Reload / Live:
         * csak a ténylegesen unavailable entity
         * legyen letiltva.
         */
        button.disabled =
          !state ||
          state.state === "unavailable";
      });

    if (this._openDropdown) {
      this._repositionDropdown();
    }
  }

  _syncSelectionFromEntities(
    showState,
    episodeState
  ) {
    let showInitialized = false;

    /*
     * MŰSOR visszaállítása.
     */
    if (
      showState &&
      showState.state !== "unknown" &&
      showState.state !== "unavailable"
    ) {
      const showOptions =
        showState.attributes?.options || [];

      const currentShow =
        showOptions.find(
          (option) =>
            String(option) ===
            String(showState.state)
        );

      if (
        currentShow !== undefined
      ) {
        this._selectedShow =
          String(currentShow);

        showInitialized = true;
      }
    }

    /*
     * EPIZÓD visszaállítása.
     */
    if (
      this._selectedShow !== null &&
      episodeState &&
      episodeState.state !== "unknown" &&
      episodeState.state !== "unavailable"
    ) {
      const episodeOptions =
        episodeState.attributes?.options || [];

      const currentEpisode =
        episodeOptions.find(
          (option) =>
            String(option) ===
            String(episodeState.state)
        );

      if (
        currentEpisode !== undefined
      ) {
        this._selectedEpisode =
          String(currentEpisode);
      }
    }

    /*
     * Csak akkor tekintjük inicializáltnak,
     * ha legalább a műsor állapota már értelmezhető.
     *
     * Így ha induláskor még loading/unknown van,
     * a későbbi HA state update után még
     * vissza tudjuk állítani.
     */
    if (showInitialized) {
      this._selectionInitialized = true;
    }
  }

  _updateShowDropdown(stateObj) {
    const dropdown =
      this.shadowRoot.querySelector(
        `.dropdown[data-entity="${this._config.show_entity}"]`
      );

    if (!dropdown) {
      return;
    }

    const button =
      dropdown.querySelector(
        ".dropdown-button"
      );

    if (!stateObj) {
      button.disabled = true;
      button.classList.add(
        "disabled"
      );

      this._setDropdownLabel(
        dropdown,
        "Válassz műsort...",
        true
      );

      return;
    }

    const options =
      stateObj.attributes?.options || [];

    if (!options.length) {
      button.disabled = true;
      button.classList.add(
        "disabled"
      );

      this._setDropdownLabel(
        dropdown,
        "Nincs műsor",
        true
      );

      return;
    }

    button.disabled = false;
    button.classList.remove(
      "disabled"
    );

    if (
      this._selectedShow === null
    ) {
      this._setDropdownLabel(
        dropdown,
        "Válassz műsort...",
        true
      );
    } else {
      this._setDropdownLabel(
        dropdown,
        this._selectedShow,
        false
      );
    }

    if (
      this._openDropdown === dropdown
    ) {
      this._renderDropdownOptions(
        dropdown,
        options,
        this._selectedShow
      );
    }
  }

  /*
   * A kedvenc ID-k a sensor entitás
   * "favorites" attribútumából jönnek.
   */
  _favoriteIds() {
    const stateObj =
      this._hass.states[
        this._config.favorites_entity
      ];

    const ids =
      stateObj?.attributes?.favorites;

    if (!Array.isArray(ids)) {
      return new Set();
    }

    return new Set(
      ids.map((id) => String(id))
    );
  }

  /*
   * A kiválasztott műsor ID-ja.
   *
   * Elsődlegesen a shows attribútumból
   * oldjuk fel név alapján, így akkor is
   * helyes, ha a select entity state-je
   * még nem frissült a kattintás után.
   */
  _selectedShowId(showState) {
    if (this._selectedShow === null) {
      return null;
    }

    const shows =
      showState?.attributes?.shows;

    if (Array.isArray(shows)) {
      const match = shows.find(
        (show) =>
          String(show.name) ===
          this._selectedShow
      );

      if (match && match.id != null) {
        return String(match.id);
      }
    }

    /*
     * Tartalék: az entity saját id
     * attribútuma, de csak ha a state
     * tényleg az általunk kiválasztott
     * műsor.
     */
    if (
      showState &&
      String(showState.state) ===
        this._selectedShow &&
      showState.attributes?.id != null
    ) {
      return String(
        showState.attributes.id
      );
    }

    return null;
  }

  _updateFavoriteButton(showState) {
    const button =
      this.shadowRoot.querySelector(
        ".favorite-button"
      );

    if (!button) {
      return;
    }

    const showId =
      this._selectedShowId(showState);

    const favorite =
      showId !== null &&
      this._favoriteIds().has(showId);

    button.disabled =
      showId === null;

    button.classList.toggle(
      "active",
      favorite
    );

    button.setAttribute(
      "aria-pressed",
      favorite ? "true" : "false"
    );

    button.title = favorite
      ? "Eltávolítás a kedvencek közül"
      : "Hozzáadás a kedvencekhez";

    const path =
      button.querySelector("path");

    if (path) {
      path.setAttribute(
        "d",
        favorite
          ? STAR_FILLED_PATH
          : STAR_OUTLINE_PATH
      );
    }
  }

  _toggleFavorite() {
    const showState =
      this._hass.states[
        this._config.show_entity
      ];

    const showId =
      this._selectedShowId(showState);

    if (showId === null) {
      return;
    }

    const favorite =
      this._favoriteIds().has(showId);

    this._hass.callService(
      "tilos_player",
      favorite
        ? "remove_favorite"
        : "add_favorite",
      {
        show_id: showId,
      }
    );
  }

  _updateEpisodeDropdown(stateObj) {
    const dropdown =
      this.shadowRoot.querySelector(
        `.dropdown[data-entity="${this._config.episode_entity}"]`
      );

    if (!dropdown) {
      return;
    }

    const button =
      dropdown.querySelector(
        ".dropdown-button"
      );

    const options =
      stateObj?.attributes?.options || [];

    /*
     * Műsor nélkül az epizód select
     * nem használható.
     */
    if (
      this._selectedShow === null ||
      !options.length
    ) {
      button.disabled = true;
      button.classList.add(
        "disabled"
      );

      this._setDropdownLabel(
        dropdown,
        "Válassz epizódot...",
        true
      );

      return;
    }

    button.disabled = false;
    button.classList.remove(
      "disabled"
    );

    if (
      this._selectedEpisode === null
    ) {
      this._setDropdownLabel(
        dropdown,
        "Válassz epizódot...",
        true
      );
    } else {
      this._setDropdownLabel(
        dropdown,
        this._selectedEpisode,
        false
      );
    }

    if (
      this._openDropdown === dropdown
    ) {
      this._renderDropdownOptions(
        dropdown,
        options,
        this._selectedEpisode
      );
    }
  }

  _setDropdownLabel(
    dropdown,
    text,
    placeholder
  ) {
    const label =
      dropdown.querySelector(
        ".dropdown-label"
      );

    if (!label) {
      return;
    }

    const newText =
      String(text);

    const oldText =
      label.dataset.text;

    /*
     * Ha ugyanaz az érték van már kinn,
     * és az állapotnak megfelelő megjelenítés
     * már létezik, ne indítsuk újra.
     */
    if (
      oldText === newText &&
      (
        placeholder
          ? label.classList.contains(
              "placeholder"
            )
          : label.classList.contains(
              "marquee"
            )
      )
    ) {
      return;
    }

    label.dataset.text =
      newText;

    label.classList.remove(
      "marquee"
    );

    label.style.removeProperty(
      "--marquee-distance"
    );

    label.style.removeProperty(
      "--marquee-duration"
    );

    if (placeholder) {
      label.innerHTML = "";
      label.textContent =
        newText;

      label.classList.add(
        "placeholder"
      );

      return;
    }

    label.classList.remove(
      "placeholder"
    );

    /*
     * Először normál szövegként jelenítjük meg,
     * hogy meg lehessen mérni.
     */
    label.innerHTML = "";
    label.textContent =
      newText;

    this._scheduleMarquee(
      dropdown
    );
  }

  _scheduleMarquee(dropdown) {
    const label =
      dropdown.querySelector(
        ".dropdown-label"
      );

    const valueContainer =
      dropdown.querySelector(
        ".dropdown-value"
      );

    if (
      !label ||
      !valueContainer
    ) {
      return;
    }

    requestAnimationFrame(() => {
      if (!label.isConnected) {
        return;
      }

      /*
       * Normál szöveg tényleges szélessége.
       */
      const overflow =
        label.scrollWidth -
        valueContainer.clientWidth;

      /*
       * Ha elfér, nincs marquee.
       */
      if (overflow <= 2) {
        label.classList.remove(
          "marquee"
        );

        label.style.removeProperty(
          "--marquee-distance"
        );

        label.style.removeProperty(
          "--marquee-duration"
        );

        return;
      }

      const text =
        label.dataset.text ||
        label.textContent;

      /*
       * Két példány egymás után,
       * közöttük 10 px + |.
       */
      label.innerHTML = `
        <span class="marquee-track">
          <span class="marquee-item"></span>
          <span class="marquee-gap"></span>
          <span class="marquee-item"></span>
        </span>
      `;

      const items =
        label.querySelectorAll(
          ".marquee-item"
        );

      items.forEach((item) => {
        item.textContent =
          text;
      });

      const firstItem =
        items[0];

      /*
       * Az első szöveg + a 10 px-es rés
       * a ciklus pontos távolsága.
       */
      const textWidth =
        firstItem.getBoundingClientRect()
          .width;

      const gap = 10;

      const distance =
        textWidth + gap;

      /*
       * Kb. 25 px/sec sebesség,
       * minimum 10 sec, maximum 40 sec.
       */
      const duration =
        Math.max(
          10,
          Math.min(
            40,
            distance / 25
          )
        );

      label.style.setProperty(
        "--marquee-distance",
        `-${distance}px`
      );

      label.style.setProperty(
        "--marquee-duration",
        `${duration}s`
      );

      label.classList.add(
        "marquee"
      );
    });
  }

  _toggleDropdown(dropdown) {
    if (
      dropdown.classList.contains(
        "open"
      )
    ) {
      this._closeDropdown();
      return;
    }

    this._closeDropdown();

    this._openDropdownMenu(
      dropdown
    );
  }

  _openDropdownMenu(dropdown) {
    const entityId =
      dropdown.dataset.entity;

    const stateObj =
      this._hass.states[
        entityId
      ];

    if (!stateObj) {
      return;
    }

    /*
     * Az epizódlista csak kiválasztott műsor
     * után nyitható meg.
     */
    if (
      entityId ===
        this._config.episode_entity &&
      this._selectedShow === null
    ) {
      return;
    }

    const options =
      stateObj.attributes?.options ||
      [];

    if (!options.length) {
      return;
    }

    const menu =
      document.createElement(
        "div"
      );

    menu.className =
      "dropdown-menu";

    this._openDropdown =
      dropdown;

    this._activeMenu =
      menu;

    const currentValue =
      entityId ===
        this._config.show_entity
        ? this._selectedShow
        : this._selectedEpisode;

    this._renderDropdownOptions(
      dropdown,
      options,
      currentValue
    );

    menu.addEventListener(
      "click",
      (event) => {
        const option =
          event.target.closest(
            ".dropdown-option"
          );

        if (!option) {
          return;
        }

        const value =
          option.dataset.value;

        /*
         * MŰSOR választás.
         */
        if (
          entityId ===
          this._config.show_entity
        ) {
          this._selectedShow =
            value;

          /*
           * Másik műsor választásakor
           * az előző epizódot töröljük.
           */
          this._selectedEpisode =
            null;

          this._selectionInitialized =
            true;

          this._hass.callService(
            "select",
            "select_option",
            {
              entity_id:
                entityId,
              option:
                value,
            }
          );

          this._closeDropdown();
          this._update();

          return;
        }

        /*
         * EPIZÓD választás.
         */
        if (
          entityId ===
          this._config.episode_entity
        ) {
          this._selectedEpisode =
            value;

          this._selectionInitialized =
            true;

          this._hass.callService(
            "select",
            "select_option",
            {
              entity_id:
                entityId,
              option:
                value,
            }
          );

          this._closeDropdown();
          this._update();
        }
      }
    );

    this.shadowRoot.appendChild(
      menu
    );

    dropdown.classList.add(
      "open"
    );

    this._repositionDropdown();

    this._documentPointerDown =
      (event) => {
        const path =
          event.composedPath();

        if (
          !path.includes(this) &&
          !path.includes(dropdown) &&
          !path.includes(menu)
        ) {
          this._closeDropdown();
        }
      };

    this._boundReposition =
      () => {
        if (this._openDropdown) {
          this._repositionDropdown();
        }
      };

    this._boundKeyDown =
      (event) => {
        if (
          event.key ===
          "Escape"
        ) {
          this._closeDropdown();
        }
      };

    document.addEventListener(
      "pointerdown",
      this._documentPointerDown,
      true
    );

    window.addEventListener(
      "resize",
      this._boundReposition
    );

    window.addEventListener(
      "scroll",
      this._boundReposition,
      true
    );

    window.addEventListener(
      "keydown",
      this._boundKeyDown
    );
  }

  _renderDropdownOptions(
    dropdown,
    options,
    currentValue
  ) {
    const menu =
      this._activeMenu;

    if (!menu) {
      return;
    }

    menu.innerHTML = "";

    /*
     * A műsorlista csoportosítva jelenik meg
     * (kedvencek, majd típus szerint),
     * az epizódlista marad lapos.
     */
    if (
      dropdown.dataset.entity ===
      this._config.show_entity
    ) {
      this._renderShowOptions(
        menu,
        options,
        currentValue
      );

      return;
    }

    this._renderFlatOptions(
      menu,
      options,
      currentValue
    );
  }

  _renderFlatOptions(
    menu,
    options,
    currentValue
  ) {
    options.forEach((option) => {
      menu.appendChild(
        this._createOption(
          option,
          option,
          {
            selected:
              currentValue !== null &&
              String(option) ===
                String(currentValue),
            favorite: null,
          }
        )
      );
    });
  }

  _renderShowOptions(
    menu,
    options,
    currentValue
  ) {
    const showState =
      this._hass.states[
        this._config.show_entity
      ];

    const shows =
      showState?.attributes?.shows;

    /*
     * Ha a backend még nem adja a shows
     * attribútumot, marad a lapos lista.
     */
    if (
      !Array.isArray(shows) ||
      !shows.length
    ) {
      this._renderFlatOptions(
        menu,
        options,
        currentValue
      );

      return;
    }

    const favorites =
      this._favoriteIds();

    const current =
      currentValue === null
        ? null
        : String(currentValue);

    const byName = (items) =>
      [...items].sort((a, b) =>
        String(a.name).localeCompare(
          String(b.name),
          "hu",
          { sensitivity: "base" }
        )
      );

    const groups = [
      {
        label: FAVORITES_GROUP_LABEL,
        items: byName(
          shows.filter((show) =>
            favorites.has(
              String(show.id)
            )
          )
        ),
      },
      ...SHOW_TYPE_GROUPS.map((group) => ({
        label: group.label,
        items: byName(
          shows.filter(
            (show) =>
              String(show.type) ===
              group.type
          )
        ),
      })),
    ];

    groups.forEach((group) => {
      if (!group.items.length) {
        return;
      }

      const label =
        document.createElement("div");

      label.className =
        "dropdown-group-label";

      label.textContent = group.label;

      menu.appendChild(label);

      group.items.forEach((show) => {
        const name =
          String(show.name);

        menu.appendChild(
          this._createOption(
            name,
            name,
            {
              selected:
                current !== null &&
                name === current,
              favorite:
                favorites.has(
                  String(show.id)
                ),
            }
          )
        );
      });
    });
  }

  /*
   * Egy legördülő opció.
   *
   * A `favorite` értéke:
   *   null  -> nincs csillag oszlop (epizód)
   *   false -> üres csillag hely, hogy a nevek
   *            egy vonalban maradjanak
   *   true  -> kitöltött csillag
   */
  _createOption(
    value,
    label,
    { selected, favorite }
  ) {
    const optionButton =
      document.createElement("button");

    optionButton.type = "button";

    optionButton.className =
      "dropdown-option";

    optionButton.dataset.value =
      String(value);

    if (favorite !== null) {
      const star =
        document.createElement("span");

      star.className =
        "dropdown-option-star";

      if (favorite) {
        star.innerHTML = `
          <svg viewBox="0 0 24 24">
            <path d="${STAR_FILLED_PATH}"/>
          </svg>
        `;
      }

      optionButton.appendChild(star);
    }

    const text =
      document.createElement("span");

    text.className =
      "dropdown-option-label";

    text.textContent = label;

    optionButton.appendChild(text);

    if (selected) {
      optionButton.classList.add(
        "selected"
      );
    }

    return optionButton;
  }

  _repositionDropdown() {
    if (
      !this._openDropdown ||
      !this._activeMenu
    ) {
      return;
    }

    const dropdown =
      this._openDropdown;

    const menu =
      this._activeMenu;

    const button =
      dropdown.querySelector(
        ".dropdown-button"
      );

    if (!button) {
      return;
    }

    const rect =
      button.getBoundingClientRect();

    const viewportWidth =
      window.innerWidth;

    const viewportHeight =
      window.innerHeight;

    const margin = 8;
    const gap = 4;
    const maxMenuHeight = 300;

    const spaceAbove =
      rect.top -
      margin -
      gap;

    const spaceBelow =
      viewportHeight -
      rect.bottom -
      margin -
      gap;

    menu.style.maxHeight =
      `${maxMenuHeight}px`;

    menu.style.height =
      "auto";

    const naturalHeight =
      Math.min(
        menu.scrollHeight,
        maxMenuHeight
      );

    /*
     * Ha lefelé nincs elég hely,
     * de fent több van, felfelé nyitunk.
     */
    const shouldOpenUp =
      spaceBelow <
        naturalHeight &&
      spaceAbove >
        spaceBelow;

    const availableSpace =
      shouldOpenUp
        ? spaceAbove
        : spaceBelow;

    const menuHeight =
      Math.max(
        40,
        Math.min(
          naturalHeight,
          availableSpace
        )
      );

    let top;

    if (shouldOpenUp) {
      top =
        rect.top -
        gap -
        menuHeight;
    } else {
      top =
        rect.bottom +
        gap;
    }

    /*
     * Ne lógjon ki a viewportból.
     */
    top = Math.max(
      margin,
      Math.min(
        top,
        viewportHeight -
          menuHeight -
          margin
      )
    );

    let left =
      rect.left;

    /*
     * Jobb oldalon se lógjon ki.
     */
    if (
      left + rect.width >
      viewportWidth - margin
    ) {
      left =
        viewportWidth -
        rect.width -
        margin;
    }

    left =
      Math.max(
        margin,
        left
      );

    menu.style.left =
      `${left}px`;

    menu.style.top =
      `${top}px`;

    menu.style.width =
      `${rect.width}px`;

    menu.style.maxHeight =
      `${menuHeight}px`;
  }

  _closeDropdown() {
    if (this._openDropdown) {
      this._openDropdown.classList.remove(
        "open"
      );
    }

    if (this._activeMenu) {
      this._activeMenu.remove();
    }

    if (
      this._documentPointerDown
    ) {
      document.removeEventListener(
        "pointerdown",
        this._documentPointerDown,
        true
      );
    }

    if (
      this._boundReposition
    ) {
      window.removeEventListener(
        "resize",
        this._boundReposition
      );

      window.removeEventListener(
        "scroll",
        this._boundReposition,
        true
      );
    }

    if (
      this._boundKeyDown
    ) {
      window.removeEventListener(
        "keydown",
        this._boundKeyDown
      );
    }

    this._openDropdown =
      null;

    this._activeMenu =
      null;

    this._documentPointerDown =
      null;

    this._boundReposition =
      null;

    this._boundKeyDown =
      null;
  }
}

if (
  !customElements.get(
    "tilos-player-card"
  )
) {
  customElements.define(
    "tilos-player-card",
    TilosPlayerCard
  );
}

window.customCards =
  window.customCards || [];

if (
  !window.customCards.some(
    (card) =>
      card.type ===
      "tilos-player-card"
  )
) {
  window.customCards.push({
    type: "tilos-player-card",
    name: "Tilos Player Card",
    description:
      "Tilos Rádió archivum lejátszó",
    preview: true,
  });
}
