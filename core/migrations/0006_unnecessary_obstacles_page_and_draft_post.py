"""The Unnecessary Obstacles project page, and a draft write-up about building it.

Projects and posts are normally written in the admin. These two arrive in a
migration so they could be reviewed in a pull request like any other
change, and go live with the deploy that ships the fields they use. After
that they're ordinary rows: edit them in the admin. This migration never
runs again, so changing the text below changes nothing.

- The project is public and featured.
- The post is a draft (no published_at). It has notes in bold brackets for
  David to settle; publish it from the admin's "Publish selected posts"
  once they're gone. The project's "Read the full write-up" button appears
  on its own when the post is published.

Neither is created if its slug is already taken, and the reverse does
nothing, so unapplying can't delete what's been edited since.
"""

import markdown
from django.db import migrations

UO = "https://unnecessaryobstacles.com"

PROJECT_SLUG = "unnecessary-obstacles"
POST_SLUG = "building-unnecessary-obstacles-with-claude-code"

SHORT_DESCRIPTION = (
    "A free site of 25 browser games I built for my family: card games with our "
    "house rules, daily logic puzzles and brainteasers, and party games for video "
    "calls. No ads, no sign-up."
)

OVERVIEW = f"""\
[Unnecessary Obstacles]({UO}/) is a free site of 25 games that run in your browser. There's nothing to install and there are no ads. You don't need an account to play: signing up only adds things like leaderboards, ratings and a record of your games.

The name comes from the philosopher Bernard Suits, who called playing a game "the voluntary attempt to overcome unnecessary obstacles."

It's for my family first: we play it together from different houses, and they playtest every game. After that, it's for anyone who wants a quick puzzle with their coffee, or a game night with people who live far away.

<figure>
  <img src="/static/img/projects/unnecessary-obstacles/shelf.webp" alt="The Unnecessary Obstacles home page: the Bernard Suits quote, a card for today's dailies, filters for cards, puzzles, brainteasers and board and party games, and the first row of card games: Contract Rummy, Euchre, Sixty-Six and Michigan Rummy." width="1600" height="1000" loading="lazy" />
  <figcaption>The shelf: every game on one page, sorted into families.</figcaption>
</figure>

The games come in three families.

### Card games, with our house rules

[Contract Rummy]({UO}/games/contract-rummy/) and [Euchre]({UO}/games/euchre/) play the way my family plays them, house rules included. Michigan Rummy, Sixty-Six and Bullshit sit beside them, along with four kinds of solitaire. Start a table and send friends the link: they join without signing up. Any empty seat can go to a bot.

### Daily logic puzzles and brainteasers

Pencil puzzles like [Hashi]({UO}/games/hashi/), Star Battle, Fillomino and Griddles (pictures you fill in by the numbers) each get a new puzzle every day, and so does Chess Puzzles. The day's dailies are all on one page, with your streaks, and there are endless puzzles once the daily's done. The brainteasers come in a box and play as often as you like: The Register asks you to find one killer among thousands of names, Chicago Traffic is a sliding traffic jam, and Codebreaker is guess-the-code with colored pegs.

### Board and party games

Some of these are made for a video call. [Bowl]({UO}/games/bowl/) takes up to 20 people in two teams, over three rounds: describe it, then two words, then charades. Fictionary works in one room or on a call, and Alphabet Roulette and Get In Line take up to 12. There are board games too, like Michigan Rails, which is about claiming train routes across Michigan.

Have a look at [the whole shelf of free browser games]({UO}/), or filter it to games you can play alone or with others.
"""

MOTIVATION = """\
It started with card games. My family plays Contract Rummy and Euchre with house rules of our own, and I wanted us to be able to play together when we can't sit at the same table.

The first game was a puzzle, though. The Register went up as a page on this site in early October 2026, and two days later it moved to a site of its own, with room for more. Contract Rummy, built to our rules, came next. The family's other favorites followed: more card games, daily pencil puzzles, and the board and party games we play when we're together.

The games that used to live here at /games now forward to the new site.
"""

HOW_ITS_BUILT = f"""\
It's one Django 6 project with about a dozen small apps, a Postgres database, and a single Heroku Basic dyno. It runs as an ASGI app, so a card table can hold a live connection open without tying up a worker.

**Two kinds of game.** Solo games and puzzles are plain JavaScript that runs in your browser and keeps your progress there. They only talk to the server to fetch the day's puzzle and to post a solve. Multiplayer games run on the server instead. Their rules are Python, a table's whole state is one JSON column, bots move on the server, and each browser is sent only what its own seat may see. Nobody can read another player's hand in the browser's developer tools, because it was never sent.

**Live tables.** A table's page keeps one request open, and the server writes a new snapshot down it whenever something changes (server-sent events). When a move is saved, Postgres `NOTIFY` tells every worker process, so players connected to different workers see it at the same time.

**Referees.** A posted solve is checked on the server before it reaches a leaderboard. For The Register, the server rebuilds the case with the game's own JavaScript engine, under Node, and accepts the solve only if the accused person really is the killer.

**A guide that checks itself.** [The technical guide]({UO}/guide/) explains how every system works, in plain words, for a curious junior developer. Its code samples and numbers aren't pasted in: each page pulls them from the source as it's drawn. Every chapter lists the files it explains and is stamped with a hash of them. When one of those files changes, a check fails until someone rereads the chapter and stamps it again, so the words can't quietly fall behind the code. [How the guide stays true]({UO}/guide/this-guide/) explains the mechanism.

<figure>
  <img src="/static/img/projects/unnecessary-obstacles/guide.webp" alt="The technical guide's chapter on the table service: a contents list down the left, a plain-language introduction, and a code sample from tables/apps.py pulled live from the source, labeled with its file and line numbers." width="1600" height="1000" loading="lazy" />
  <figcaption>A chapter of the technical guide. The code sample is drawn from the source, with its file and lines.</figcaption>
</figure>

**Measured, not guessed.** To find out how many people one small dyno can hold, I load-tested a production-like copy. The first limits it hit were database connections and memory, not CPU. A small connection pool per worker, and running one Node referee at a time, fixed both. With the pool, 480 watchers at 40 busy tables lost no updates.

**Found in search.** Each game has a plain search title and description, a preview card for links, and structured data that says it's a free game you play in the browser.
"""

CHALLENGES = """\
**Keeping secrets in a browser game.** A card game where the browser knows every hand is a card game anyone can cheat at. Running every multiplayer game on the server is more work per game, but the browser only ever holds what its player is allowed to see.

**Cheating at puzzles.** The referees stop casual cheating, like posting a time for a case you never solved. They can't stop someone determined who reads the game's code. That's an accepted limit, and the guide says so.

**25 games that feel like one site.** Every game has its own look, but they share one design language: the same words for the same things, one table kit for every multiplayer game, and one way of saying it's your move.

**One small server.** A single Basic dyno keeps the cost low, and it shapes the code: connections come from a pool, the heavy Node checks take turns, and puzzles are checked ahead of time so posting a score doesn't keep you waiting.

**Docs that drift.** A guide this detailed would be out of date within a week if keeping it current depended on memory. Making the check part of the tests is what keeps it true.
"""

LESSONS = """\
**Real players find what tests can't.** My family's playtest rounds catch the things no test asks about: a tap that lands on the wrong thing on a phone, a moment where nobody's sure whose turn it is.

**Write the rules down where the work happens.** The repository's guide for contributors, its decision records and the guide check do more for consistency than anything I could keep in my head.

**Measure before upgrading.** The load test pointed at two settings, not a bigger plan.

Most of the code was written with Claude Code, Anthropic's coding agent, while I decided what to build, reviewed it and played it.
"""

POST_TITLE = "Building Unnecessary Obstacles with Claude Code"

POST_SUMMARY = (
    "How I built a site of 25 free browser games for my family in about three weeks, "
    "mostly by directing Claude Code: what a working day looked like, what worked, "
    "what didn't, and what I'd tell someone trying it."
)

POST_CONTENT = f"""\
**[Draft. Notes in bold brackets are for David: confirm or change each one, then delete it before publishing.]**

[Unnecessary Obstacles]({UO}/) is a site of 25 free browser games I made for my family: our card games with our house rules, daily logic puzzles, and party games for video calls. Three weeks ago it was a single puzzle on this site. **[Confirm the framing: The Register went up here on October 4, 2026, and the new site's first commit is October 6.]**

I typed very little of the code. I built it with Claude Code, Anthropic's coding agent, which works inside the repository: it reads the code, edits files, runs the tests and commits. Of the 858 commits so far, 752 list Claude as a co-author. Along the way the repo has merged 67 pull requests and written down 49 architecture decisions.

That doesn't mean it built itself. Here's what the work looked like, including the parts that didn't go smoothly.

## Who does what

My part is deciding what to build, reviewing it and playing it. Claude's part is everything in between: reading the code, planning the change, writing it, testing it and opening a pull request.

The deciding turned out to matter more than I expected. Early on I asked Claude to pitch some original multiplayer games. They were fine on paper, but they felt a little bland, and none of them were games anyone in my family was asking to play. What works is the other way around: I name a game we already love, explain how we play it, and Claude builds that. **[Confirm you're happy sharing this.]**

## Many hands, separate desks

For a bigger round of work, Claude Code splits the job into pieces and hands each to a subagent: another Claude session with its own instructions. Each subagent works in its own git worktree, a separate checkout of the repo on its own branch, so two of them never edit the same files at once. When they're done, the pieces are merged into one branch, the checks run, and a pull request comes to me.

I read the pull request, play the change on my phone and laptop, and merge it. Merging deploys. **[Confirm how you review: on which devices, and whether you read every diff.]**

## One day of it

Here's what shipped on one day, October 25, 2026. Each item was its own pull request. **[Confirm the date, and that "one day" is fair: the playtest notes came in the day before.]**

**A playtest round.** My family had played everything and sent notes. The biggest one: they loved the moment in Contract Rummy where your hand is dealt and the game shows you what to do, and they wanted that everywhere they had to act. Now every game has "Your move" cues: a short prompt the first time you need to do something, and a gentle highlight if you sit idle. The same round let you choose which way to move in Auction House, let you type your own yes-or-no questions in Last One Standing (the game matches them to a question it can answer), cleaned up some Griddles pictures that didn't read well, and reviewed the wording across the whole site.

**A phone bug.** On my iPhone, tapping anywhere at a card table just opened the game log. A tap area meant to make a small button easier to hit had been measured from the wrong box, so it covered the whole table. The fix was small. The more useful part was a new check that presses every control at its middle and corners, at every screen size, and fails if something answers from outside its own box. That bug can't come back quietly.

**A plain-language rewrite of the technical guide.** [The technical guide]({UO}/guide/) explains every system on the site from the code, across 37 files. The first version was accurate but wordy, with the rhythm you learn to spot in AI-written text. We wrote style rules into the guide's README (short sentences, everyday words, no throat-clearing) and rewrote every chapter against them. It came out about 18% shorter.

**Search.** Each game got a title and description in the words people search with, plus a sitemap, a robots.txt, a 1200×630 preview card for links, and structured data that says it's a free game in the browser.

**A load test.** Claude stood up a production-like copy and sent traffic at it until something broke. The first things to break weren't the CPU: Postgres ran out of connections at about 50 pages at once, or at three 20-person tables, and each Node referee check used 250 to 330 MB of a 512 MB dyno. A small connection pool per worker and one referee check at a time fixed both, and 480 watchers at 40 busy tables then lost no updates. **[Confirm whether you plan to move to a 1 GB dyno: the test found the app can still go slightly over 512 MB during a referee check.]**

## What makes it work

**Rules in the repo, not in my head.** Every agent reads the repo's AGENTS.md first. It has numbered rules, like "every change that alters behavior updates the technical guide in the same pull request." When something goes wrong, the fix usually adds a rule or a check, so it can't go wrong the same way twice. The phone bug is an example.

**Decisions written down.** The architecture decision records say why things are the way they are. A fresh session can read why the server holds every hand of cards, instead of "simplifying" it so the browser does.

**A guide that keeps up.** Because the guide pulls its code samples from the source and a check fails when a chapter falls behind, the documentation stays honest without anyone remembering to update it. It's also how a new session learns the codebase.

**Real players.** Tests prove the code does what we said it should. My family finds out whether we said the right thing.

## What doesn't

**It sounds just as sure when it's wrong.** Agent output reads as finished whether it is or not. The phone bug shipped, and passed the checks we had. Reviewing has to mean playing the thing, not just reading the diff.

**Flaky tests under load.** With several agents running test suites at once on one laptop, a timing-sensitive test sometimes fails. It's a real cost: a red check you have to rerun and think about. **[Confirm you want this in.]**

**The writing voice.** Left alone, the prose drifts toward a recognizable cadence: "it's worth noting," lists of three, grand framing. It took written style rules to get plain writing back. This post was drafted with Claude too, and edited by me. **[Confirm or rewrite this line once you've edited it.]**

**Usage limits.** Several agents working at once go through usage quickly. I've learned to keep batches small and shippable, and to pick models deliberately. **[Confirm you want to mention this.]**

**Review is the bottleneck, and it should be.** Claude can write changes faster than I can play them. The pace I can review at is the pace the site should move at.

## If you want to try it

- Start with an AGENTS.md (or CLAUDE.md) that says how you want things done, and grow it every time something goes wrong.
- Turn every repeated mistake into a check.
- Decide what to build yourself.
- Keep pull requests small enough that you'll really review them.
- Put it in front of real people early.

## Have a look

[Play the games on Unnecessary Obstacles]({UO}/): try [Contract Rummy with friends or bots]({UO}/games/contract-rummy/), or [today's Hashi bridges puzzle]({UO}/games/hashi/). If you're curious how it works, [how the guide stays true]({UO}/guide/this-guide/) is a good place to start.
"""


def render(text):
    # Historical models don't have Post.save() or Project.save(), which is
    # where the HTML is normally rendered, so it's done here.
    return markdown.markdown(text, extensions=["fenced_code", "codehilite", "tables", "toc"])


def add_page_and_draft(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    Post = apps.get_model("core", "Post")
    Tag = apps.get_model("core", "Tag")

    if not Project.objects.filter(slug=PROJECT_SLUG).exists():
        Project.objects.create(
            title="Unnecessary Obstacles",
            slug=PROJECT_SLUG,
            short_description=SHORT_DESCRIPTION,
            overview=OVERVIEW,
            overview_html=render(OVERVIEW),
            motivation=MOTIVATION,
            motivation_html=render(MOTIVATION),
            expected_outcome="",
            expected_outcome_html="",
            how_its_built=HOW_ITS_BUILT,
            how_its_built_html=render(HOW_ITS_BUILT),
            challenges=CHALLENGES,
            challenges_html=render(CHALLENGES),
            lessons_learned=LESSONS,
            lessons_learned_html=render(LESSONS),
            image_url=f"{UO}/static/img/og/site.png",
            image_alt=(
                "The Unnecessary Obstacles preview card: playing cards, a Star Battle puzzle, "
                "a page of suspects' names and a word card, beside the line \"Card games, daily "
                "puzzles, brainteasers and party games. Free, in your browser.\""
            ),
            tech_stack="Django, Python, Postgres, JavaScript, Server-sent events, Node, Heroku",
            live_url=f"{UO}/",
            # The repository is private, so there's no source link.
            repo_url="",
            blog_post_slug=POST_SLUG,
            status="in_production",
            priority=1,
            is_public=True,
            is_featured=True,
        )

    if not Post.objects.filter(slug=POST_SLUG).exists():
        post = Post.objects.create(
            title=POST_TITLE,
            slug=POST_SLUG,
            summary=POST_SUMMARY,
            content=POST_CONTENT,
            content_html=render(POST_CONTENT),
            image_url=f"{UO}/static/img/og/site.png",
            image_alt="The Unnecessary Obstacles preview card: playing cards, a Star Battle puzzle, a page of suspects' names and a word card.",
            published_at=None,
        )
        for slug, name in (("devlogs", "Devlogs"), ("project-write-ups", "Project Write-Ups")):
            tag, _ = Tag.objects.get_or_create(slug=slug, defaults={"name": name})
            post.tags.add(tag)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_project_overview_how_its_built_images"),
    ]

    operations = [
        migrations.RunPython(add_page_and_draft, migrations.RunPython.noop),
    ]
