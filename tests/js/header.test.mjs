import assert from "node:assert/strict";
import { test } from "node:test";

import { loadCard } from "./card-module.mjs";

const card = loadCard();

const LOGO = "/api/brands/integration/tilos_player/logo.png";

/*
 * A vm contextben keletkezett objektumok prototípusa más realm-beli,
 * ezért a mezőket külön ellenőrizzük.
 */
test("élő fejléc: playing + stream.tilos.hu → logó és szöveg", () => {
  const info = card.liveHeaderInfo(
    {
      state: "playing",
      attributes: {
        media_content_id: "https://stream.tilos.hu/tilos",
        media_artist: "Kowalsky",
        media_title: "Somewhere",
      },
    },
    LOGO,
  );

  assert.equal(info.image, LOGO);
  assert.equal(info.text, "Kowalsky – Somewhere");
});

test("élő fejléc: nem playing → null", () => {
  assert.equal(
    card.liveHeaderInfo(
      {
        state: "paused",
        attributes: {
          media_content_id: "https://stream.tilos.hu/tilos",
          media_title: "x",
        },
      },
      LOGO,
    ),
    null,
  );
});

test("élő fejléc: nem Tilos tartalom → null", () => {
  assert.equal(
    card.liveHeaderInfo(
      {
        state: "playing",
        attributes: {
          media_content_id: "https://example.com/stream.mp3",
          media_artist: "A",
          media_title: "B",
        },
      },
      LOGO,
    ),
    null,
  );
});

test("élő fejléc: nincs állapot vagy nincs lejátszó → null", () => {
  assert.equal(card.liveHeaderInfo(null, LOGO), null);
  assert.equal(
    card.liveHeaderInfo({ state: "playing", attributes: {} }, LOGO),
    null,
  );
});

test("élő fejléc: tartalom-id formafüggetlen", () => {
  const info = card.liveHeaderInfo(
    {
      state: "playing",
      attributes: {
        media_content_id: "http://Stream.Tilos.hu/tilos.mp3?token=1",
        media_title: "Cím",
      },
    },
    LOGO,
  );

  assert.equal(info.text, "Cím");
});

test("élő szöveg: csak előadó / csak cím / egyik sincs", () => {
  assert.equal(card.liveHeaderText("Kowalsky", ""), "Kowalsky");
  assert.equal(card.liveHeaderText("", "Somewhere"), "Somewhere");
  assert.equal(card.liveHeaderText("  ", null), "");
});

test("élő fejléc: nincs szöveg → null (marad a sima logó)", () => {
  assert.equal(
    card.liveHeaderInfo(
      {
        state: "playing",
        attributes: {
          media_content_id: "https://stream.tilos.hu/tilos",
        },
      },
      LOGO,
    ),
    null,
  );
});
