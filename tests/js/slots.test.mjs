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

test("slot: nincs lejátszás, nincs mentett pozíció → csak play", () => {
  assertSlots(card.slotVisibility(false, false, false), {
    play: true,
    restart: false,
    resume: false,
    stop: false,
  });
});

test("slot: mentett pozíció, nincs lejátszás → előről + folytatás", () => {
  assertSlots(card.slotVisibility(false, true, false), {
    play: false,
    restart: true,
    resume: true,
    stop: false,
  });
});

test("slot: aktív lejátszás, nem archív (élő) → csak stop", () => {
  assertSlots(card.slotVisibility(true, false, false), {
    play: false,
    restart: false,
    resume: false,
    stop: true,
  });

  assertSlots(card.slotVisibility(true, true, false), {
    play: false,
    restart: false,
    resume: false,
    stop: true,
  });
});

test("slot: archív lejátszás → előről és stop", () => {
  assertSlots(card.slotVisibility(true, false, true), {
    play: false,
    restart: true,
    resume: false,
    stop: true,
  });

  assertSlots(card.slotVisibility(true, true, true), {
    play: false,
    restart: true,
    resume: false,
    stop: true,
  });
});
