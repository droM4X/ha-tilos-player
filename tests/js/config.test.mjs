import assert from "node:assert/strict";
import { test } from "node:test";

import { loadCard } from "./card-module.mjs";

const card = loadCard();

test("show_info: alapból be, ha nincs se show_info, se show_cover", () => {
  assert.equal(card.resolveShowInfo({}), true);
});

test("show_info: a régi show_cover csak hiányban dönt", () => {
  assert.equal(card.resolveShowInfo({ show_cover: false }), false);
  assert.equal(card.resolveShowInfo({ show_cover: true }), true);
  assert.equal(
    card.resolveShowInfo({ show_cover: false, show_info: true }),
    true,
  );
  assert.equal(
    card.resolveShowInfo({ show_cover: true, show_info: false }),
    false,
  );
});

test("show_info: az editor a feloldott értéket írja, nem törli a régit üresen", () => {
  const config = card.editorConfig({
    show_cover: false,
  });

  assert.deepEqual(Object.keys(config), ["show_info"]);
  assert.equal(config.show_info, false);
});

test("show_info: az editor törli a régi show_cover kulcsot", () => {
  const config = card.editorConfig({
    show_cover: false,
    show_info: false,
  });

  /* A vm contextben keletkezett objektum prototípusa más realm-beli,
   * ezért mezőnként ellenőrizzük, nem deepEqual-lel. */
  assert.deepEqual(Object.keys(config), ["show_info"]);
  assert.equal(config.show_info, false);
});
