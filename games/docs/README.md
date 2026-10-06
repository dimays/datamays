# games

**The games moved to their own site, [unnecessaryobstacles.com](https://unnecessaryobstacles.com)**
(repo `dimays/unnecessary-obstacles`), with accounts, daily cases and
leaderboards. It shares nothing with this site — separate app, database and
logins.

What's left here:

| Path | What |
|---|---|
| `/games/` | Redirects (301) to unnecessaryobstacles.com |
| `/games/the-register/` | The Register as it was, with a "this game has moved" notice |

The old Register page stays because players' saved cases live in this site's
browser storage. The notice (`data-moved` on the page) tells them where the
game went and offers **Back up**, so they can **Restore** on the new site.
Once nobody needs it, the page can redirect too and this app can go.

The Register's files under `games/static/games/the-register/` are published
from its own project (`~/the-register/tools/publish-site.sh`); don't edit
them here.
