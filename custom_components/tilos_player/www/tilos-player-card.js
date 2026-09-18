class TilosPlayerCard extends HTMLElement {
  constructor() {
    super();

    this.attachShadow({ mode: "open" });

    this._hass = null;
    this._config = {};

    // A kártya saját UI-állapota.
    // Az entity state-et nem használjuk automatikusan
    // kiválasztott értékként.
    this._selectedShow = null;
    this._selectedEpisode = null;

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

          /*
           * Csak maga a kártya fekete.
           */
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

          /*
           * A select marad világos.
           */
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
          background: var(--secondary-background-color, #f5f5f5);
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

        /*
         * Marquee konténer.
         * A szöveg két példánya egymás mögött halad,
         * így a ciklus végén nincs látható ugrás.
         */
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

        /*
         * A dropdown fixed pozíciójú, ezért ki tud lógni
         * a kártyából.
         */
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

          /*
           * A gombok is világosak maradnak.
           */
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

        @media (max-width: 500px) {
          .buttons {
            grid-template-columns: 1fr;
          }
        }
      </style>

      <ha-card class="card">
        <img class="logo" alt="Tilos Rádió">

        <div class="selectors">

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
                <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 7.99 7.99 7.99c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
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

    this._updateShowDropdown(
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

        button.disabled =
          !state ||
          state.state === "unavailable" ||
          state.state === "unknown";
      });

    if (this._openDropdown) {
      this._repositionDropdown();
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
      button.classList.add("disabled");

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
      button.classList.add("disabled");

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

    /*
     * Nem az entity state-et mutatjuk,
     * hanem kizárólag azt, amit ténylegesen
     * kiválasztott a felhasználó.
     */
    if (this._selectedShow === null) {
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

    /*
     * Az epizód entity state-ét sem vesszük
     * automatikusan kiválasztottnak.
     */
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

    const newText = String(text);
    const oldText =
      label.dataset.text;

    /*
     * Ha ugyanaz az érték van már kinn,
     * és az animáció már fut, ne indítsuk újra.
     *
     * Ez fontos, mert a Home Assistant rendszeresen
     * küld state update-eket.
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
     * Először normál szövegként rakjuk be,
     * hogy meg tudjuk mérni a tényleges szélességét.
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
       * Nem lóg ki -> nincs marquee.
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
       * Két példány + köztes rés.
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
       * Az első szöveg + hézag a teljes
       * periodikus egység szélessége.
       */
      const textWidth =
        firstItem.getBoundingClientRect()
          .width;

      const gap = 10;

      const distance =
        textWidth + gap;

      /*
       * Kb. 25 px/sec.
       * A hosszabb címek természetesen lassabban
       * mennek végig a teljes cikluson.
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
     * Az epizódlista csak kiválasztott
     * műsor után nyitható meg.
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
           * Új műsornál az előző epizód
           * már nem tekinthető kiválasztottnak.
           */
          this._selectedEpisode =
            null;

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

    options.forEach(
      (option) => {
        const optionButton =
          document.createElement(
            "button"
          );

        optionButton.type =
          "button";

        optionButton.className =
          "dropdown-option";

        optionButton.dataset.value =
          String(option);

        optionButton.textContent =
          option;

        if (
          currentValue !== null &&
          String(option) ===
            String(currentValue)
        ) {
          optionButton.classList.add(
            "selected"
          );
        }

        menu.appendChild(
          optionButton
        );
      }
    );
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
     * de fent több van, akkor felfelé nyit.
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
     * Biztosítjuk, hogy ne lógjon ki
     * a viewportból.
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
      "Tilos Rádió archive player card",
    preview: true,
  });
}
