import { readFileSync } from "node:fs";
import vm from "node:vm";

const CARD_URL = new URL(
  "../../custom_components/tilos_player/www/tilos-player-card.js",
  import.meta.url,
);

/*
 * A kártya egy sima browser-szkript: a tetejénálló `function`
 * deklarációk a globálra kerülnek, az osztálydeklarációk nem.
 * A browser-stubok elégnek ahhoz, hogy a fájl betöltsön.
 */
export function loadCard() {
  const context = vm.createContext({
    customElements: {
      get: () => undefined,
      define: () => {},
    },
    document: {
      createElement: () => ({}),
    },
    window: {},
    HTMLElement: class {},
  });

  vm.runInContext(readFileSync(CARD_URL, "utf8"), context, {
    filename: CARD_URL.pathname,
  });

  return context;
}
