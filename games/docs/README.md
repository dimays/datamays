# games

The games hub and the games themselves. No models, no migrations, no database.

## What it does

| Path | What |
|---|---|
| `/games/` | The hub — one card per game, on the site's dark theme |
| `/games/<slug>/` | A game, rendered as its own full-screen page |

## The one thing worth knowing

**Games are declared in `catalog.py`, not in the database.** A game ships with
the deploy and nothing about it is user-generated, so a table would buy a
migration, an admin screen and a query per page load in exchange for nothing.
`Project` lives in the database because its copy gets edited without a deploy;
a game's does not.

Adding a game is three files and one entry:

```
games/templates/games/<slug>.html         the game itself
games/templates/games/thumbs/<slug>.html  the card's artwork
a Game(...) entry in catalog.py
```

A game too big for one template keeps its scripts and styles under
`games/static/games/<slug>/` and loads them from its page with `{% static %}`.

`games/tests.py` renders every entry in the catalog, so a template named with a
typo fails the suite rather than a visitor's click.

## Games do not extend `core/base.html`

Each game is a standalone document that owns the whole viewport and sets its
own palette — the Register is a leather-bound ledger on a dark desk, and
dropping it inside the site's navbar and footer would fight it. The route back to the site is a link the game
carries in its own header, styled to match the game.

The consequence: a game gets no navbar, no footer and no site CSS. It is
responsible for its own `<title>`, favicon and viewport meta. That is the
trade, and it is the right one for something that wants to feel like a place
rather than a page.

## The Register

A murder mystery solved by elimination: a register of 26,000 generated names,
a handful of clues, and exactly one name that no clue clears. Two modes (Cold
Case, all clues at once; The Inquiry, clues unlocked one at a time) and three
difficulties. Every case is generated in the browser from an eight-character
case number, so a number — or a share link, `#/open/<code>/<difficulty>/<mode>`
— gives anyone the identical case.

**The source of truth is not this repo.** The Register is its own project
(`~/the-register`), where it also runs as a desktop app with a local Node
server. Its `public/` folder is copied here by its publish script:

```bash
~/the-register/tools/publish-site.sh ~/code/datamays
```

That writes `games/static/games/the-register/`. Do not edit those files here;
edit them in the Register and publish again. The page in
`games/templates/games/the-register.html` stands in for the app's `index.html`
and sets `data-storage="browser"`, which switches the app from its local
server to IndexedDB (`js/store.js`). Nothing is sent to the site: cases and
saves live in the visitor's browser, and **Back up** / **Restore** on the
Register's home screen move them between browsers as a JSON file.

The static files are served by WhiteNoise. The app's ES modules import each
other by relative path, so they load the unhashed copies that
`collectstatic` keeps beside the hashed ones; only the page's entry points
(`app.js`, `styles.css`, the manifest) get hashed URLs.

## Tests

```bash
uv run python manage.py test games --settings=datamays.settings_test
```
