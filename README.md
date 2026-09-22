# Challenge League Power Rankings

Opponent-adjusted power rankings for the NCFC Youth **Challenge - Fall 2026** league,
built from the league's published schedule and results.

The league table answers "who has the most points?" This answers a different question:
**who has actually beaten somebody?** A one-goal win over the division leader counts for
more than a four-goal win over the team in last, and the ratings say so.

There are two pages. `index.html` opens on **U11 Red Boys** with **NCFCY Chelsea**
highlighted, and a picker switches to any of the league's 25 divisions. `team.html` is a
full season report for the one team the build is pointed at.

## What the league page shows

- **Power rank** for every team, next to its league-table rank, so the disagreements are visible.
- **A crest for every team**, in the colors of the club it is named for — Chelsea in Stamford
  Bridge blue, Newcastle in black and white stripes, Flamengo in red and black hoops. The page
  never says so; the colors just show up.
- **Where the model disagrees with the table** — the three teams the standings most misprice, each with the reason.
- **A résumé for every team** — each result with the opponent's power rank attached.
- **Strength of schedule** — the average power score of the opponents a team has actually played.
- **Projected margins** for upcoming fixtures, posted on the half goal.

## The team page

`team.html` answers a different question from the rankings. The league page asks who is
good; this one asks what happens to one team now. It covers whichever team
`FEATURED_LEAGUE_TEAM_ID` names, and the two pages link to each other.

- **Every game still on the schedule**, with the kickoff time, the field, and its address
  as a map link. A rescheduled game sits in kickoff order under the new date the league
  posted for it, flagged as moved, and a round the team genuinely sits out is named as a
  bye.
- **A scouting line on every remaining opponent** — their rank, record, rating, goals,
  strength of schedule, recent form, what else they still have to play, and the result if
  the two have already met.
- **Win/draw/loss odds** for each of those games, and the full distribution of final
  margins behind them.
- **Every result so far** measured against the margin the model would have projected,
  fitted *without* that game, so the projection never sees the result it is judged against.
- **A simulated finish**: the rest of the division played out 20,000 times, giving a
  finishing-position distribution for all ten teams, a final points spread, what it takes
  to win the division, and what a clean sweep of the remaining games is worth.
- **Which game matters most** — the chance of winning the division given a win, a draw or
  a loss in each remaining fixture, read straight off the same simulated seasons.

## How the odds are worked out

A projected margin says nothing on its own about how sure it is, so `scripts/projections.py`
measures the spread around it. Every game the league has played is re-predicted from a
Massey fit that leaves that game out, and the standard deviation of those misses is the
spread — currently about 2.3 goals across 395 games. Scored on games it has already been
fitted to the model looks about a goal sharper than it is, which is exactly why the
leave-one-out pass exists; `tests/test_projections.py` fails if that gap ever inverts.

A game is a draw when the margin lands on zero, so the win and loss tails start half a goal
either side of the projection. That is the whole model. Grouped by how likely a home win was
called, it comes out close to honest — the 60–80% calls win 73% of the time — and its Brier
score of 0.19 beats the 0.25 you get from quoting the league's home-win rate at every game
regardless of who is playing. The page shows that table so the claim can be checked rather
than taken.

The simulation draws one margin per remaining fixture from that spread, holding ratings
still so the model cannot learn from games it is inventing, and draws the losing side's
goals from the distribution this league has actually produced — a margin alone would settle
points and goal difference but not the goals-scored tie-break. Tables are ordered the
league's way: points, goal difference, goals for, goals against. The seed is fixed, so a
refresh that finds no new results produces the same odds rather than ones that wobble by
half a point twice a day.

## Crests and colors

Most teams in this league are named for a real club. `scripts/clubs.py` resolves the roster
name to that club and hands the page its kit: the colors, the pattern they go in (stripes,
hoops, halves, a sash, a sleeve), and a three-letter code. The page draws the shield from
those, so a division of ten teams arrives with ten different identities instead of ten grey
rows. 126 of the league's 219 teams currently resolve to a club.

The club itself is never named on the page. There is no "playing as Chelsea" line under a
team, and no competition label: a team named for a club turns up in that club's colors and
that is the whole of it. The `club` and `comp` fields exist so the table can tell two clubs
of the same name apart, not to be rendered.

Nothing is copied from a club. There is no badge artwork anywhere in the repository — what
renders is a kit assembled from colors, drawn as SVG in the browser.

Teams with no real club behind them (`Predators`, `WF United Blue`) still get a crest. If the
name contains a color, that is the kit; otherwise one is picked from a fixed palette by a hash
of the name, so a team keeps the same crest from one refresh to the next. Within a division,
two palette crests are never allowed to land on the same color.

Each team also gets two accent colors, the same hue pushed to a luminance that reads on a
white page and on a dark one. That is what the stripe down the side of a row is drawn in.
Without it, Fulham would be drawn in white and Juventus in black.

To fix a club or add one, edit the `CLUBS` table in `scripts/clubs.py` and rebuild — the key
is the team name lowercased with everything but letters and digits removed. The table is
covered by `tests/test_clubs.py`, which checks every entry is well formed, every accent is
readable in both themes, and every team in the shipped data comes out with a crest the page
can draw.

A handful of names are genuinely ambiguous and are deliberately left unresolved rather than
guessed at: `Racing` (Racing Louisville or Racing Club), `Clash`, `Herons`, `Brooklyn`,
`Canberra`, `Fleury`. `Sheffield` is read as Sheffield United.

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

### Projections are posted on the half goal

The gap between two Massey ratings is a projected margin, and that is what the "Next up"
calls come from. It is rounded to the nearest half goal, the way a betting line is: a
projection of 1.28 goes up as `Chelsea by 1.5`, and 2.2 as `Chelsea by 2`. Halves round up,
so 1.25 posts at 1.5. A game that rounds to zero is shown as too close to call.

Tenths of a goal would advertise precision three games of data cannot support. The step is
`MARGIN_STEP` in `scripts/ratings.py`; set it to `1.0` to post whole goals instead.

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

`scripts/build.py` writes three files, all committed so the pages work with no server:

- `index.html` — the league-wide rankings, data baked in
- `team.html` — the featured team's season report, same data baked in
- `data/rankings.json` — the computed figures on their own

Both pages share their design tokens (`templates/shared.css`) and their crest drawing
(`templates/crest.js`); the build inlines both, so a change reaches both pages and each
page still ships as a single file.

Names, crests and colors are presentation rather than results, so they are attached when the
page is rendered and stay out of `data/rankings.json`. A change to the club table reaches the
page on the next build with nothing refetched:

```sh
python3 scripts/build.py --offline
```

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

Change `FEATURED_LEAGUE_TEAM_ID` to follow a different team; the league page will open on
whichever division that team plays in, and `team.html` becomes that team's report. Change
all four for a different league.

## Keeping it current

`.github/workflows/refresh.yml` re-fetches results twice a day -- early morning Eastern
and mid-evening Eastern -- rebuilds both pages, commits the
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
