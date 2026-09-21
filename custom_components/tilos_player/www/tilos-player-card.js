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

/* Info ikon a műsorleírás gombhoz. */
const INFO_OUTLINE_PATH =
  "M11,9H13V7H11M12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M11,17H13V11H11V17Z";

/* Listához adás ikon (Music Assistant mód). */
const PLAYLIST_ADD_PATH =
  "M3,15H9V13H3V15M3,19H9V17H3V19M3,11H13V9H3V11M3,7H13V5H3V7M17,11V8H15V11H12V13H15V16H17V13H20V11H17Z";

/* X ikon a link lejátszó mező törléséhez. */
const CLOSE_PATH =
  "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z";

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

/* Címkék a vizuális beállítás-szerkesztőhöz. */
const EDITOR_LABELS = {
  integration_type: "Integráció típusa",
  media_player: "Média lejátszó entitás",
  link_player: "Link lejátszó",
};

const EDITOR_HELPERS = {
  integration_type:
    "Home Assistant: a tilos_player.play szolgáltatást használja. " +
    "Music Assistant: a backend a music_assistant.play_media szolgáltatást hívja, " +
    "így a kártya tud a lejátszási sor végére fűzni.",
  media_player:
    "A kártya gombjai ezen a lejátszón futnak. Ha üres, a Lejátszás gomb entitás " +
    "media_player attribútumából veszi a céllejátszót.",
  link_player:
    "Bekapcsolva az epizódválasztó alatt megjelenik egy mező, ahova közvetlen " +
    "mp3 linket lehet beilleszteni. Lejátszáskor ez elsőbbséget élvez a " +
    "kiválasztott epizóddal szemben.",
};

/*
 * Közvetlen link lejátszás: csak .mp3-ra végződő URL fogadható el.
 * A query string (pl. token) megengedett a .mp3 után.
 */
const LINK_URL_RE = /^https?:\/\/.+\.mp3(\?.*)?$/i;

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

    /*
     * A leírás panel nyitva van-e, és mi van épp
     * benne: "show" (műsor infó) vagy "episode"
     * (epizód leírás). Egyszerre csak az egyik
     * lehet nyitva.
     */
    this._openInfo = null;
    /* Az utoljára kirakott panel-tartalom (elkerüli az újraírást). */
    this._renderedInfo = null;

    this._documentPointerDown = null;
    this._boundReposition = null;
    this._boundKeyDown = null;
  }

  setConfig(config) {
    this._config = {
      integration_type: "home_assistant",
      show_entity: "select.tilos_radio_show",
      episode_entity: "select.tilos_radio_episode",
      favorites_entity: "sensor.tilos_radio_favorites",
      play_entity: "button.tilos_radio_play",
      live_entity: "button.tilos_radio_live",
      media_player: "",
      link_player: false,
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

  /*
   * Interaktív beállítás-szerkesztő.
   * A YAML mód mellett a Lovelace
   * vizuális szerkesztője is használható.
   */
  static getConfigElement() {
    return document.createElement(
      "tilos-player-card-editor"
    );
  }

  static getStubConfig() {
    return {
      integration_type: "home_assistant",
    };
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

    /*
     * A render új DOM-ot épít, ezért a
     * leírás tartalmát újra be kell tölteni.
     */
    this._renderedInfo = null;

    const musicAssistant =
      this._isMusicAssistant();

    const buttonColumns =
      musicAssistant ? 3 : 2;

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

        /*
         * Csillag a kártya bal felső sarkában,
         * a kártya belső eltartásához igazítva,
         * hogy a többi gombbal egy vonalban legyen.
         */
        .favorite-button {
          position: absolute;
          top: 16px;
          left: 16px;
          z-index: 3;

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

          /* A logó fölé kerül, ezért kell egy kis árnyék. */
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);

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

        /* Info gomb az epizód sorban, mint a csillag. */
        .info-button {
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

        .info-button:hover:not(:disabled) {
          background: var(--secondary-background-color, #d9d9d9);
        }

        .info-button:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        .info-button:disabled {
          opacity: 0.5;
          cursor: default;
        }

        /* Nyitott állapotban invertált szín. */
        .info-button.active {
          background: var(--primary-color);
          border-color: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .info-button svg {
          width: 26px;
          height: 26px;

          fill: currentColor;
        }

        /* Epizód választó + info gomb egy sorban. */
        .episode-row {
          display: flex;
          align-items: stretch;
          gap: 10px;
        }

        .episode-row .dropdown {
          flex: 1;
          min-width: 0;
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

        /*
         * Közvetlen link lejátszó: teljes szélességű
         * beviteli mező az epizódválasztó és a
         * gombsor között. Csak bekapcsolt opciónál
         * látszik.
         */
        .link-row {
          display: flex;
          flex-direction: column;
          gap: 4px;

          margin-bottom: 12px;
        }

        .link-row[hidden] {
          display: none;
        }

        .link-input-wrap {
          position: relative;

          display: flex;
          align-items: center;

          width: 100%;
        }

        .link-input {
          width: 100%;
          min-height: 46px;

          box-sizing: border-box;

          padding: 8px 12px;
          /* Hely az X ikonnak a mező végén. */
          padding-right: 44px;

          border: 1px solid var(--divider-color, #ddd);
          border-radius: 8px;

          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);

          font: inherit;
          font-size: 14px;
        }

        .link-input::placeholder {
          color: var(--secondary-text-color, #757575);
        }

        .link-input:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        .link-input.invalid {
          border-color: var(--error-color, #db4437);
        }

        .link-input.invalid:focus-visible {
          outline-color: var(--error-color, #db4437);
        }

        /*
         * Törlő X a link mező végén — csak akkor
         * látszik, ha van kitöltött tartalom.
         */
        .link-clear {
          position: absolute;
          right: 6px;

          width: 32px;
          height: 32px;

          box-sizing: border-box;

          display: flex;
          align-items: center;
          justify-content: center;

          padding: 0;

          border: 0;
          border-radius: 50%;

          background: transparent;
          color: var(--secondary-text-color, #757575);

          cursor: pointer;

          transition:
            background-color 0.15s ease,
            color 0.15s ease;
        }

        .link-clear:hover {
          background: var(--secondary-background-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
        }

        .link-clear:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        .link-clear[hidden] {
          display: none;
        }

        .link-clear svg {
          width: 18px;
          height: 18px;

          fill: currentColor;
        }

        .link-error {
          font-size: 12px;
          line-height: 1.3;

          color: var(--error-color, #db4437);
        }

        .link-error[hidden] {
          display: none;
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

        /*
         * Az epizód műsorleírása / tracklistája.
         * A gombsor alatt nyílik ki és lefelé
         * növeli a kártyát.
         */
        .description-panel {
          margin-top: 12px;

          box-sizing: border-box;

          padding: 12px 14px;

          border: 1px solid var(--divider-color, #ddd);
          border-radius: 8px;

          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);

          font-size: 14px;
          line-height: 1.5;

          overflow-y: auto;
          overflow-wrap: anywhere;

          max-height: 420px;

          scrollbar-width: thin;
        }

        .description-panel[hidden] {
          display: none;
        }

        .description-panel img {
          max-width: 100%;
          height: auto;

          border-radius: 6px;
        }

        .description-panel p {
          margin: 0 0 10px;
        }

        .description-panel p:last-child {
          margin-bottom: 0;
        }

        .description-panel a {
          color: var(--primary-color);
        }

        .description-panel ul,
        .description-panel ol {
          margin: 0 0 10px;
          padding-left: 22px;
        }

        .description-panel h1,
        .description-panel h2,
        .description-panel h3 {
          margin: 0 0 8px;
          font-size: 1em;
          font-weight: 700;
        }

        /* Műsor infó: a cím nagyobb az első sorban. */
        .description-panel .show-info-title {
          margin: 0 0 8px;

          font-size: 1.2em;
          font-weight: 700;
          line-height: 1.25;
        }

        .description-panel .show-info-definition {
          margin: 0 0 10px;
        }

        .description-panel .show-info-description {
          margin: 0;
        }
      </style>

      <ha-card class="card">
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

        <img class="logo" alt="Tilos Rádió">

        <div class="selectors">
          <div class="show-row">
            <button
              class="info-button"
              data-info="show"
              type="button"
              disabled
              aria-expanded="false"
              title="Nincs műsorleírás"
            >
              <svg viewBox="0 0 24 24">
                <path d="${INFO_OUTLINE_PATH}"/>
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

          <div class="episode-row">
            <button
              class="info-button"
              data-info="episode"
              type="button"
              disabled
              aria-expanded="false"
              title="Nincs műsorleírás"
            >
              <svg viewBox="0 0 24 24">
                <path d="${INFO_OUTLINE_PATH}"/>
              </svg>
            </button>

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
        </div>

        <div
          class="link-row"
          ${this._config.link_player ? "" : "hidden"}
        >
          <div class="link-input-wrap">
            <input
              class="link-input"
              type="text"
              inputmode="url"
              spellcheck="false"
              autocomplete="off"
              placeholder="Az mp3 fájl közvetlen linkje"
              aria-label="Közvetlen mp3 link"
            />

            <button
              class="link-clear"
              type="button"
              hidden
              aria-label="Link törlése"
              title="Link törlése"
            >
              <svg viewBox="0 0 24 24">
                <path d="${CLOSE_PATH}"/>
              </svg>
            </button>
          </div>

          <div class="link-error" hidden>
            Érvénytelen link – csak .mp3-ra végződő
            URL játszható le.
          </div>
        </div>

        <div
          class="buttons"
          style="grid-template-columns: repeat(${buttonColumns}, 1fr)"
        >
          ${
            musicAssistant
              ? `
          <button
            class="action-button queue"
            data-action="queue"
            type="button"
          >
            <span class="icon">
              <svg viewBox="0 0 24 24">
                <path d="${PLAYLIST_ADD_PATH}"/>
              </svg>
            </span>
            <span>Sorba</span>
          </button>
          `
              : ""
          }

          <button
            class="action-button play"
            data-action="play"
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
            data-action="live"
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

        <div class="description-panel" hidden>
          <div class="description-content"></div>
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
      .querySelectorAll(".info-button")
      .forEach((button) => {
        button.addEventListener(
          "click",
          (event) => {
            event.stopPropagation();
            this._toggleInfo(
              button.dataset.info
            );
          }
        );
      });

    const linkInput =
      this.shadowRoot.querySelector(
        ".link-input"
      );

    if (linkInput) {
      linkInput.addEventListener(
        "input",
        () => this._update()
      );
    }

    const linkClear =
      this.shadowRoot.querySelector(
        ".link-clear"
      );

    if (linkClear) {
      linkClear.addEventListener(
        "click",
        (event) => {
          event.stopPropagation();
          this._clearLink();
        }
      );
    }

    this.shadowRoot
      .querySelectorAll(".action-button")
      .forEach((button) => {
        button.addEventListener(
          "click",
          () => {
            if (button.disabled) {
              return;
            }

            const action =
              button.dataset.action;

            /*
             * Music Assistant módban a Sorba gomb
             * a sor végére fűzi az epizódot
             * (enqueue: add). A backend hívja a
             * music_assistant.play_media-t.
             */
            if (action === "queue") {
              this._playSource("add");

              return;
            }

            /*
             * Music Assistant módban a
             * lejátszás enqueue: play módon
             * indul (a sor megtartásával).
             */
            if (
              action === "play" &&
              this._isMusicAssistant()
            ) {
              this._playSource("play");

              return;
            }

            /*
             * Élő adás: a tilos_player.play
             * szolgáltatás játssza le a
             * választott lejátszón.
             */
            if (action === "live") {
              this._callTilosPlay("live");

              return;
            }

            /*
             * Home Assistant módban a
             * kiválasztott epizód a választott
             * lejátszón, metaadattal együtt.
             */
            if (action === "play") {
              this._playSource();
            }
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
        const action =
          button.dataset.action;

        /*
         * SORBA / MA LEJÁTSZÁS:
         *
         * Music Assistant módban a kártya
         * közvetlenül a music_assistant.play_media
         * szolgáltatást hívja, ezért a gomb
         * akkor aktív, ha van kiválasztott
         * epizód URL és céllejátszó.
         */
        if (
          action === "queue" ||
          (
            action === "play" &&
            this._isMusicAssistant()
          )
        ) {
          button.disabled = !this._maReady();

          return;
        }

        /*
         * LIVE: a tilos_player.play
         * szolgáltatás a választott
         * lejátszó entitáson fut, ezért az
         * a döntő, hogy van-e kiválasztott
         * lejátszó.
         */
        if (action === "live") {
          button.disabled = !this._targetPlayer();

          return;
        }

        /*
         * PLAY (Home Assistant mód):
         *
         * A button entity állapota nem dönthet arról,
         * hogy a gomb használható-e.
         *
         * A Tilos Play button "unknown" lehet,
         * illetve a backend runtime állapotától függően
         * unavailable is lehet, miközben a frontendben
         * már megvan az epizód.
         */
        if (action === "play") {
          button.disabled =
            !this._targetPlayer() ||
            this._linkInvalid() ||
            (
              this._selectedEpisode === null &&
              this._linkUrl().length === 0
            );
        }
      });

    this._updateInfoButtons(
      showState,
      episodeState
    );

    this._updateLinkInput();

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

  _isMusicAssistant() {
    return (
      this._config.integration_type ===
      "music_assistant"
    );
  }

  /*
   * A céllejátszó entitás.
   *
   * Elsődlegesen a kártya beállításaiban
   * választott media_player, tartalékként
   * a play button entity "media_player"
   * attribútuma.
   */
  _targetPlayer() {
    if (this._config.media_player) {
      return this._config.media_player;
    }

    const playState =
      this._hass.states[
        this._config.play_entity
      ];

    return (
      playState?.attributes
        ?.media_player || ""
    );
  }

  /*
   * A kiválasztott epizód mp3 URL-je.
   *
   * Csak akkor adjuk vissza, ha az
   * entity state tényleg az általunk
   * kiválasztott epizód, különben a
   * kattintás utáni rövid átmeneti
   * időben a régi URL-t kapnánk.
   */
  _episodeUrl(episodeState) {
    if (
      this._selectedEpisode === null ||
      !episodeState ||
      String(episodeState.state) !==
        String(this._selectedEpisode)
    ) {
      return "";
    }

    const url =
      episodeState.attributes?.mp3_url;

    return typeof url === "string"
      ? url
      : "";
  }

  /*
   * A kiválasztott epizód HTML
   * műsorleírása / tracklistája.
   */
  _episodeDescription(episodeState) {
    if (
      this._selectedEpisode === null ||
      !episodeState ||
      String(episodeState.state) !==
        String(this._selectedEpisode)
    ) {
      return "";
    }

    const description =
      episodeState.attributes
        ?.description;

    return typeof description === "string"
      ? description
      : "";
  }

  /*
   * A kiválasztott műsor info mezői
   * (név, definition, description) a show
   * select attribútumaiból.
   *
   * Csak akkor adjuk vissza, ha az entity
   * state tényleg az általunk kiválasztott
   * műsor, különben a váltás utáni rövid
   * átmeneti időben a régi leírást kapnánk.
   */
  _showInfo(showState) {
    if (
      this._selectedShow === null ||
      !showState ||
      String(showState.state) !==
        String(this._selectedShow)
    ) {
      return null;
    }

    const attrs =
      showState.attributes || {};

    const asText = (value) =>
      typeof value === "string"
        ? value
        : "";

    return {
      name: asText(attrs.info_name),
      definition: asText(
        attrs.info_definition
      ),
      description: asText(
        attrs.info_description
      ),
    };
  }

  _escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /*
   * Közvetlen link mező értéke
   * (nyers és validált formában).
   */
  _linkRaw() {
    const input =
      this.shadowRoot.querySelector(
        ".link-input"
      );

    return input
      ? input.value.trim()
      : "";
  }

  _linkUrl() {
    const raw = this._linkRaw();

    return raw &&
      LINK_URL_RE.test(raw)
      ? raw
      : "";
  }

  _linkInvalid() {
    const raw = this._linkRaw();

    return (
      raw.length > 0 &&
      !LINK_URL_RE.test(raw)
    );
  }

  _updateLinkInput() {
    const input =
      this.shadowRoot.querySelector(
        ".link-input"
      );

    if (!input) {
      return;
    }

    const invalid = this._linkInvalid();

    input.classList.toggle(
      "invalid",
      invalid
    );

    input.setAttribute(
      "aria-invalid",
      invalid ? "true" : "false"
    );

    const error =
      this.shadowRoot.querySelector(
        ".link-error"
      );

    if (error) {
      error.hidden = !invalid;
    }

    /*
     * A törlő X csak kitöltött mezőnél
     * látszik.
     */
    const clear =
      this.shadowRoot.querySelector(
        ".link-clear"
      );

    if (clear) {
      clear.hidden =
        this._linkRaw().length === 0;
    }
  }

  _clearLink() {
    const input =
      this.shadowRoot.querySelector(
        ".link-input"
      );

    if (!input) {
      return;
    }

    input.value = "";
    this._update();
  }

  _maReady() {
    if (!this._targetPlayer()) {
      return false;
    }

    if (this._linkInvalid()) {
      return false;
    }

    const episodeState =
      this._hass.states[
        this._config.episode_entity
      ];

    return Boolean(
      this._linkUrl() ||
        this._episodeUrl(episodeState)
    );
  }

  /*
   * Lejátszás a tilos_player.play
   * szolgáltatással a választott
   * lejátszó entitáson.
   *
   * media = "episode" -> a kiválasztott
   *                       archív epizód,
   *                       metaadattal együtt
   * media = "live"    -> az élő adás
   *
   * enqueue megadásával (Music Assistant)
   * a backend a music_assistant.play_media
   * szolgáltatást hívja, így az epizód a
   * lejátszási sorba kerül (add/play/...).
   */
  _callTilosPlay(media, enqueue) {
    const target = this._targetPlayer();

    if (!target) {
      return;
    }

    const data = {
      entity_id: target,
      media,
    };

    if (enqueue) {
      data.enqueue = enqueue;
    }

    this._hass.callService(
      "tilos_player",
      "play",
      data
    );
  }

  /*
   * Lejátszás indítása: ha a link mező ki van
   * töltve (és érvényes), azt küldjük be,
   * különben a kiválasztott epizódot.
   */
  _playSource(enqueue) {
    const link = this._linkUrl();

    if (link) {
      this._callTilosPlayUrl(link, enqueue);
      return;
    }

    this._callTilosPlay("episode", enqueue);
  }

  /*
   * Közvetlen mp3 URL lejátszása a
   * tilos_player.play szolgáltatással
   * (media = "url").
   */
  _callTilosPlayUrl(url, enqueue) {
    const target = this._targetPlayer();

    if (!target) {
      return;
    }

    const data = {
      entity_id: target,
      media: "url",
      url,
    };

    if (enqueue) {
      data.enqueue = enqueue;
    }

    this._hass.callService(
      "tilos_player",
      "play",
      data
    );
  }

  /*
   * A két info gomb és a leírás panel
   * állapotának frissítése. Egyszerre csak
   * az egyik tartalom lehet nyitva.
   */
  _updateInfoButtons(showState, episodeState) {
    const showButton =
      this.shadowRoot.querySelector(
        '.info-button[data-info="show"]'
      );

    const episodeButton =
      this.shadowRoot.querySelector(
        '.info-button[data-info="episode"]'
      );

    const panel =
      this.shadowRoot.querySelector(
        ".description-panel"
      );

    if (!showButton || !episodeButton || !panel) {
      return;
    }

    const html = {
      show: this._buildShowInfoHtml(showState),
      episode:
        this._episodeDescription(episodeState),
    };

    const available = {
      show: html.show.length > 0,
      episode: html.episode.length > 0,
    };

    /*
     * Ha a nyitott tartalom eltűnt
     * (pl. műsorváltás), zárjuk be.
     */
    if (
      this._openInfo !== null &&
      !available[this._openInfo]
    ) {
      this._openInfo = null;
    }

    [
      ["show", showButton],
      ["episode", episodeButton],
    ].forEach(([kind, button]) => {
      const hasContent = available[kind];

      const open =
        this._openInfo === kind &&
        hasContent;

      button.disabled = !hasContent;

      button.classList.toggle(
        "active",
        open
      );

      button.setAttribute(
        "aria-expanded",
        open ? "true" : "false"
      );

      button.title = !hasContent
        ? kind === "show"
          ? "Nincs műsorleírás"
          : "Nincs epizódleírás"
        : open
          ? "Leírás elrejtése"
          : "Leírás megjelenítése";
    });

    const content =
      panel.querySelector(
        ".description-content"
      );

    const activeHtml =
      this._openInfo === null
        ? ""
        : html[this._openInfo];

    /*
     * Csak akkor írjuk újra a DOM-ot, ha
     * tényleg változott a tartalom —
     * így a görgetési pozíció megmarad.
     */
    const renderKey =
      this._openInfo === null
        ? ""
        : `${this._openInfo}:${activeHtml}`;

    if (
      content &&
      this._renderedInfo !== renderKey
    ) {
      this._renderedInfo = renderKey;

      content.innerHTML = activeHtml;
    }

    panel.hidden = this._openInfo === null;
  }

  /*
   * A műsor info HTML-je: nagyobb cím,
   * majd a definition, végül a description
   * (ez HTML lehet, ezért nem escape-eljük).
   */
  _buildShowInfoHtml(showState) {
    const info = this._showInfo(showState);

    if (!info) {
      return "";
    }

    const parts = [];

    if (info.name) {
      parts.push(
        `<div class="show-info-title">${this._escapeHtml(
          info.name
        )}</div>`
      );
    }

    if (info.definition) {
      parts.push(
        `<div class="show-info-definition">${this._escapeHtml(
          info.definition
        )}</div>`
      );
    }

    if (info.description) {
      parts.push(
        `<div class="show-info-description">${info.description}</div>`
      );
    }

    return parts.join("");
  }

  _toggleInfo(kind) {
    const button =
      this.shadowRoot.querySelector(
        `.info-button[data-info="${kind}"]`
      );

    if (!button || button.disabled) {
      return;
    }

    /*
     * Ugyanarra a gombra kattintva zár, a
     * másikra váltva pedig lecseréli a
     * tartalmat (a másik gomb visszaáll).
     */
    this._openInfo =
      this._openInfo === kind
        ? null
        : kind;

    this._updateInfoButtons(
      this._hass.states[
        this._config.show_entity
      ],
      this._hass.states[
        this._config.episode_entity
      ]
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

          /*
           * A nyitott leírás panel is zárul,
           * mert mindkét tartalom cserélődik.
           */
          this._openInfo = null;

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

/*
 * Vizuális beállítás-szerkesztő.
 *
 * A Lovelace "Vizuális szerkesztő"
 * fület ez a ha-form alapú elem adja.
 * Az integráció típusa legördülőből
 * választható, Music Assistant módban
 * megjelenik a céllejátszó mező is.
 */
class TilosPlayerCardEditor extends HTMLElement {
  constructor() {
    super();

    this._hass = null;
    this._config = null;
    this._form = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._sync();
  }

  get hass() {
    return this._hass;
  }

  setConfig(config) {
    this._config = config || {};
    this._sync();
  }

  _sync() {
    if (!this._hass || !this._config) {
      return;
    }

    if (!this._form) {
      this._form =
        document.createElement("ha-form");

      this._form.addEventListener(
        "value-changed",
        (event) => {
          event.stopPropagation();

          this.dispatchEvent(
            new CustomEvent(
              "config-changed",
              {
                detail: {
                  config: event.detail.value,
                },
                bubbles: true,
                composed: true,
              }
            )
          );
        }
      );

      this.appendChild(this._form);
    }

    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = this._schema();

    this._form.computeLabel = (schema) =>
      EDITOR_LABELS[schema.name] ||
      schema.name;

    this._form.computeHelper = (schema) =>
      EDITOR_HELPERS[schema.name] || "";
  }

  _schema() {
    return [
      {
        name: "integration_type",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              {
                value: "home_assistant",
                label: "Home Assistant",
              },
              {
                value: "music_assistant",
                label: "Music Assistant",
              },
            ],
          },
        },
      },
      {
        name: "media_player",
        selector: {
          entity: {
            domain: "media_player",
          },
        },
      },
      {
        name: "link_player",
        selector: {
          boolean: {},
        },
      },
    ];
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

if (
  !customElements.get(
    "tilos-player-card-editor"
  )
) {
  customElements.define(
    "tilos-player-card-editor",
    TilosPlayerCardEditor
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
