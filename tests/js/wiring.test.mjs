import assert from "node:assert/strict";
import { test } from "node:test";

import { loadCardSource } from "./card-module.mjs";

const source = loadCardSource();

/*
 * Minden gombnak, ami a markupban megjelenik, kell
 * legyen click agga is: a kulonben a gomb lattszik,
 * nyomva viszont semmi sem tortenik.
 */
test("minden data-action gombhoz van click ag", () => {
  const actions = [
    ...source.matchAll(/data-action="([a-z]+)"/g),
  ].map((match) => match[1]);

  assert.ok(actions.length > 0, "nincs data-action a forrasban");

  for (const action of new Set(actions)) {
    assert.ok(
      source.includes(`=== "${action}"`),
      `nincs click ag a data-action="${action}" gombhoz`,
    );
  }
});
