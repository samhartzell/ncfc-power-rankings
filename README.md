# Challenge League Power Rankings

Opponent-adjusted power rankings for the NCFC Youth **Challenge - Fall 2026** league,
built from the league's published schedule and results.

The league table answers "who has the most points?" This answers a different question:
**who has actually beaten somebody?** A one-goal win over the division leader counts for
more than a four-goal win over the team in last, and the ratings say so.

The page opens on **U11 Red Boys** with **NCFCY Chelsea** highlighted, and a picker
switches to any of the league's 25 divisions.

## What it shows

- **Power rank** for every team, next to its league-table rank, so the disagreements are visible.
- **Where the model disagrees with the table** — the three teams the standings most misprice, each with the reason.
- **A résumé for every team** — each result with the opponent's power rank attached.
- **Strength of schedule** — the average power score of the opponents a team has actually played.
- **Projected margins** for upcoming fixtures.

## How the ranking works

Each team gets two independent ratings, then they are blended into a 0–100 **Power score**
where 50 is an average team in that division.

**Colley** uses only wins and losses. Every team starts at .500 and its rating is pulled
toward the average rating of the opponents it faced, so beating a good team moves you more
than beating a bad one. It is self-regularizing, which matters when teams have played three
games.

**Massey** uses goal margin, so a 4–0 win counts for more than a 1–0 win over the same
opponent. It is solved across the whole division at once, so a margin is judged against the
opponent who conceded it. A ridge term pulls every team toward average; its influence fades
automatically as games accumulate.

The blend is 60% Massey / 40% Colley. Margin carries more signal than win-loss in a short
season, but win-loss is what the table rewards, so neither dominates. Both weights and the
ridge term are constants at the top of `scripts/ratings.py`.

### Blowouts are capped, because the league caps them

This league records a maximum of **4 goals per team per game** for Goals For / Goals Against,
and caps each game's **differential at 4**. Those are two separate caps — a 6–2 win is 4–2 for
GF/GA but +4 for GD. Both are applied here, so beating a weak team 9–0 is worth exactly the
same as beating them 4–0.

That reading of the rules is not a guess. `tests/test_ratings.py` replays a real division and
asserts that the recomputed W–L–T, GF, GA, GD and points match the league's own published
standings row for row, for all ten teams.

### What it deliberately does not do

- **No home-field adjustment.** These are club fields with short travel, and a sample this
  small could not separate a real home effect from noise.
- **No roster knowledge.** The model does not know who was missing, who is playing up, or
  what the weather did.
- **No cross-division comparison.** Teams only play inside their own division, so a power
  score is meaningful only against the other teams on the same page.

Early in a season the order moves around. Treat gaps of a point or two as noise.

## Running it

No dependencies — standard-library Python 3 only.

```sh
python3 scripts/build.py              # fetch live results, recompute, rebuild the page
python3 scripts/build.py --offline    # rebuild the page from the saved data/rankings.json
python3 -m unittest discover -s tests # run the checks
```

`scripts/build.py` writes two files, both committed so the page works with no server:

- `index.html` — the whole site, data baked in
- `data/rankings.json` — the computed figures on their own

Open `index.html` directly in a browser; it needs nothing else.

## Pointing it at a different team or league

The three identifiers at the top of `scripts/build.py` come straight out of the public
league URL:

```
https://playmetricssports.com/g/leagues/1321-2470-07598d11/teams/64255/team_view.html
                                        ^^^^ ^^^^ ^^^^^^^^        ^^^^^
                                        gb   league  key          team
```

```python
GOVERNING_BODY_ID = 1321
LEAGUE_ID = 2470
LEAGUE_KEY = "07598d11"
FEATURED_LEAGUE_TEAM_ID = 64255   # the team the page opens on
```

Change `FEATURED_LEAGUE_TEAM_ID` to follow a different team; the page will open on whichever
division that team plays in. Change all four for a different league.

## Keeping it current

`.github/workflows/refresh.yml` re-fetches results every morning, rebuilds, commits the
change only if something moved, and publishes to GitHub Pages. It can also be run on demand
from the Actions tab.

Publishing needs GitHub Pages switched on once, under **Settings → Pages → Source: GitHub
Actions**. Creating a Pages site takes more permission than the Actions token carries, so
the workflow cannot do it for you. Until it is on, the workflow still refreshes the data and
leaves a notice on the run saying the page was not published; once it is on, every run
publishes.

If the commit step ever fails with a permissions error, check **Settings → Actions → General
→ Workflow permissions: Read and write**.

## Where the data comes from

The PlayMetrics site is a single-page app backed by a JSON API at
`api.gb.playmetrics.com/external/lss/`. That API sends no CORS headers, so a browser on
another domain cannot call it — which is why the data is fetched at build time and baked
into the page rather than loaded live in the reader's browser.

Only public league data is read: schedules, scores and standings. No credentials, no
rosters, no player information.
