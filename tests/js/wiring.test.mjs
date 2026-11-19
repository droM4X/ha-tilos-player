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

/*
 * A lathato gombok sorrendjet a sablon DOM sorrendje
 * adja: ha az Elorol megjelenik, mindig o jon eloszor.
 */
test("Előről gomb a Lejátszás és a Stop slot elé kerül", () => {
  const at = (action) =>
    source.indexOf(`data-action="${action}"`);

  assert.ok(at("restart") !== -1, "nincs Előről gomb");

  assert.ok(
    at("restart") < at("play"),
    "az Előről a Lejátszás slot elé kerüljön",
  );

  assert.ok(
    at("restart") < at("stop"),
    "az Előről a Stop slot elé kerüljön",
  );
});
