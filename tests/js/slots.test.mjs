import assert from "node:assert/strict";
import { test } from "node:test";

import { loadCard } from "./card-module.mjs";

const card = loadCard();

/*
 * A vm contextben keletkezett objektum prototípusa más realm-beli,
 * ezért a négy mezőt külön ellenőrizzük.
 */
const assertSlots = (actual, expected) => {
  assert.deepEqual(
    Object.keys(actual).sort(),
    ["play", "restart", "resume", "stop"],
  );

  for (const key of ["play", "restart", "resume", "stop"]) {
    assert.equal(actual[key], expected[key], key);
  }
};

test("slot: nincs aktív lejátszás, nincs mentett pozíció → csak play", () => {
  assertSlots(card.slotVisibility(false, false), {
    play: true,
    restart: false,
    resume: false,
    stop: false,
  });
});

test("slot: mentett pozíció → előről + folytatás", () => {
  assertSlots(card.slotVisibility(false, true), {
    play: false,
    restart: true,
    resume: true,
    stop: false,
  });
});

test("slot: aktív lejátszás → stop váltja ki a playt és a párt", () => {
  assertSlots(card.slotVisibility(true, false), {
    play: false,
    restart: false,
    resume: false,
    stop: true,
  });

  assertSlots(card.slotVisibility(true, true), {
    play: false,
    restart: false,
    resume: false,
    stop: true,
  });
});
