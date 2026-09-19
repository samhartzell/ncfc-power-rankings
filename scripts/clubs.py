#!/usr/bin/env python3
"""Turn a league roster name into a visual identity.

Most teams in this league are named after a real club -- 'U11 (15) NCFCY
Chelsea' is Chelsea, 'NCFC Rowdies DCH' is the Tampa Bay Rowdies -- so the page
can carry each team's real colors instead of twenty-five pages of identical grey
rows.

Two things come out of here:

* ``parse`` splits the roster name into the parts worth showing separately --
  the team name, the club that runs it (NCFC Youth, TYSC, FWSC), the site code,
  and whether it is a girls team.
* ``identity`` resolves the team name to a crest: the real club it is named
  after, that club's competition, its kit colors, and the kit pattern those
  colors go in. Names with no real counterpart ('Predators', 'WF United Blue')
  still get a crest, built from a color word in the name when there is one and
  from a fixed palette otherwise.

The crests are drawn from these colors and patterns in the browser. No club
badge artwork is copied -- what the page renders is a kit, not a trademark.
"""
import colorsys
import hashlib
import re

# --- name parsing ---------------------------------------------------------

AGE_PREFIX = re.compile(r"^U\d+\s*\(\d+\)\s*")

# The clubs that field teams in this league. NCFCY and NCFC are the same club
# (the age group decides which spelling the league uses), and it runs most of
# the league, so its teams carry no tag on the page.
ORGS = {
    "NCFCY": ("NCFC", True),
    "NCFC": ("NCFC", True),
    "FWSC": ("FWSC", False),
    "TYSC": ("TYSC", False),
    "TFA": ("TFA", False),
    "USC": ("USC", False),
}

# Site codes NCFC Youth appends to teams from its satellite programs.
SITES = {"HSFV", "DCH"}


def parse(name):
    """Split a roster name into its display parts.

    'U11 (15) NCFCY Chelsea'      -> Chelsea, org NCFC (host), no site
    'U13 (13) NCFC Rowdies DCH'   -> Rowdies, org NCFC, site DCH
    'U12 (14) TYSC Finley Fury G' -> Finley Fury, org TYSC, girls
    """
    trimmed = AGE_PREFIX.sub("", name).strip()
    tokens = trimmed.split()

    org, host = "", True
    if tokens and tokens[0].upper() in ORGS:
        org, host = ORGS[tokens.pop(0).upper()]

    girls = False
    if tokens and tokens[-1].upper() == "G":
        tokens.pop()
        girls = True

    site = ""
    kept = []
    for token in tokens:
        if token.upper() in SITES:
            site = token.upper()
        else:
            kept.append(token)

    # 'Arsenal FC' and 'Arsenal' are the same team in different divisions;
    # drop the suffix so they read the same way.
    if len(kept) > 1 and kept[-1].upper() == "FC":
        kept.pop()

    display = " ".join(kept) or trimmed or name
    return {
        "display": display,
        "org": org,
        "host": host,
        "site": site,
        "girls": girls,
        "key": _key(display),
    }


def _key(display):
    return re.sub(r"[^a-z0-9]", "", display.lower())


# --- club table -----------------------------------------------------------
#
# colors are [field, trim, accent]; pattern says what to do with them.
# Patterns: solid, stripes, hoops, halves, diagonal, sash, sleeves, cross, band.


def _club(club, comp, pattern, colors, code):
    return {
        "club": club,
        "comp": comp,
        "pattern": pattern,
        "colors": list(colors),
        "code": code,
    }


CLUBS = {
    # --- England: Premier League ---
    "arsenal": _club("Arsenal", "Premier League", "sleeves", ["#EF0107", "#FFFFFF", "#023474"], "ARS"),
    "astonvilla": _club("Aston Villa", "Premier League", "sleeves", ["#670E36", "#95BFE5", "#FFFFFF"], "AVL"),
    "bournemouth": _club("AFC Bournemouth", "Premier League", "stripes", ["#DA291C", "#000000", "#FFFFFF"], "BOU"),
    "brentford": _club("Brentford", "Premier League", "stripes", ["#E30613", "#FFFFFF", "#000000"], "BRE"),
    "brighton": _club("Brighton & Hove Albion", "Premier League", "stripes", ["#0057B8", "#FFFFFF", "#000000"], "BHA"),
    "chelsea": _club("Chelsea", "Premier League", "solid", ["#034694", "#FFFFFF", "#DBA111"], "CHE"),
    "crystalpalace": _club("Crystal Palace", "Premier League", "stripes", ["#1B458F", "#C4122E", "#FFFFFF"], "CRY"),
    "everton": _club("Everton", "Premier League", "solid", ["#003399", "#FFFFFF", "#003399"], "EVE"),
    "fulham": _club("Fulham", "Premier League", "solid", ["#FFFFFF", "#000000", "#CC0000"], "FUL"),
    "manchestercity": _club("Manchester City", "Premier League", "solid", ["#6CABDD", "#FFFFFF", "#1C2C5B"], "MCI"),
    "manchesterunited": _club("Manchester United", "Premier League", "solid", ["#DA291C", "#000000", "#FBE122"], "MUN"),
    "newcastle": _club("Newcastle United", "Premier League", "stripes", ["#241F20", "#FFFFFF", "#41B6E6"], "NEW"),
    "forest": _club("Nottingham Forest", "Premier League", "solid", ["#DD0000", "#FFFFFF", "#000000"], "NFO"),
    "spurs": _club("Tottenham Hotspur", "Premier League", "solid", ["#FFFFFF", "#132257", "#132257"], "TOT"),
    "westham": _club("West Ham United", "Premier League", "sleeves", ["#7A263A", "#1BB1E7", "#FFFFFF"], "WHU"),
    "wolves": _club("Wolverhampton Wanderers", "Premier League", "solid", ["#FDB913", "#231F20", "#231F20"], "WOL"),
    # --- England: the divisions below it, where promotion moves clubs around
    # too often to name a tier ---
    "blackpool": _club("Blackpool", "EFL", "solid", ["#F68712", "#FFFFFF", "#000000"], "BLK"),
    "bristolcity": _club("Bristol City", "EFL", "solid", ["#E21C38", "#FFFFFF", "#000000"], "BRC"),
    "burnley": _club("Burnley", "EFL", "sleeves", ["#6C1D45", "#99D6EA", "#FFFFFF"], "BUR"),
    "cardiffcity": _club("Cardiff City", "EFL", "solid", ["#0070B5", "#FFFFFF", "#D11524"], "CDF"),
    "charlton": _club("Charlton Athletic", "EFL", "solid", ["#D4021D", "#FFFFFF", "#000000"], "CHA"),
    "coventry": _club("Coventry City", "EFL", "solid", ["#6DC2E8", "#FFFFFF", "#0B1F3F"], "COV"),
    "derbycounty": _club("Derby County", "EFL", "solid", ["#FFFFFF", "#000000", "#000000"], "DER"),
    "huddersfield": _club("Huddersfield Town", "EFL", "stripes", ["#0E63AD", "#FFFFFF", "#000000"], "HUD"),
    "ipswichtown": _club("Ipswich Town", "EFL", "solid", ["#3A64A3", "#FFFFFF", "#DE2C2C"], "IPS"),
    "leicestercity": _club("Leicester City", "EFL", "solid", ["#003090", "#FDBE11", "#FFFFFF"], "LEI"),
    "lincolncity": _club("Lincoln City", "EFL", "stripes", ["#DA291C", "#FFFFFF", "#000000"], "LIN"),
    "lutontown": _club("Luton Town", "EFL", "solid", ["#F78F1E", "#002D62", "#FFFFFF"], "LUT"),
    "mansfieldtown": _club("Mansfield Town", "EFL", "solid", ["#FFC20E", "#00205B", "#00205B"], "MNS"),
    "millwall": _club("Millwall", "EFL", "solid", ["#001C58", "#FFFFFF", "#FFFFFF"], "MLW"),
    "northampton": _club("Northampton Town", "EFL", "solid", ["#7C2529", "#FFFFFF", "#FFFFFF"], "NTH"),
    "norwich": _club("Norwich City", "EFL", "solid", ["#FFF200", "#00A650", "#00A650"], "NOR"),
    "portsmouth": _club("Portsmouth", "EFL", "solid", ["#001489", "#FFFFFF", "#D2122E"], "PTS"),
    "reading": _club("Reading", "EFL", "hoops", ["#004494", "#FFFFFF", "#E4002B"], "RDG"),
    # 'Sheffield' on its own is ambiguous; read as the red-and-white half.
    "sheffield": _club("Sheffield United", "EFL", "stripes", ["#EE2737", "#FFFFFF", "#000000"], "SHU"),
    "southampton": _club("Southampton", "EFL", "stripes", ["#D71920", "#FFFFFF", "#130C0E"], "SOU"),
    "stokecity": _club("Stoke City", "EFL", "stripes", ["#E03A3E", "#FFFFFF", "#1B1B1B"], "STK"),
    "sunderland": _club("Sunderland", "EFL", "stripes", ["#EB172B", "#FFFFFF", "#000000"], "SUN"),
    "swansea": _club("Swansea City", "EFL", "solid", ["#FFFFFF", "#000000", "#000000"], "SWA"),
    "watford": _club("Watford", "EFL", "solid", ["#FBEE23", "#000000", "#ED2127"], "WAT"),
    "westbrom": _club("West Bromwich Albion", "EFL", "stripes", ["#122F67", "#FFFFFF", "#FFFFFF"], "WBA"),
    "wrexham": _club("Wrexham", "EFL", "solid", ["#D2122E", "#FFFFFF", "#FFFFFF"], "WRX"),
    # --- Scotland ---
    "celtic": _club("Celtic", "Scottish Premiership", "hoops", ["#018749", "#FFFFFF", "#FFD700"], "CEL"),
    # --- Spain ---
    "barcelona": _club("FC Barcelona", "La Liga", "stripes", ["#004D98", "#A50044", "#EDBB00"], "BAR"),
    "madrid": _club("Real Madrid", "La Liga", "solid", ["#FFFFFF", "#00529F", "#FEBE10"], "RMA"),
    "realmadrid": _club("Real Madrid", "La Liga", "solid", ["#FFFFFF", "#00529F", "#FEBE10"], "RMA"),
    "atletico": _club("Atlético Madrid", "La Liga", "stripes", ["#CB3524", "#FFFFFF", "#272E61"], "ATM"),
    "valencia": _club("Valencia", "La Liga", "solid", ["#FFFFFF", "#000000", "#F4A11E"], "VAL"),
    # --- Portugal ---
    "sporting": _club("Sporting CP", "Primeira Liga", "hoops", ["#008057", "#FFFFFF", "#FFFFFF"], "SCP"),
    # --- Italy ---
    "acmilan": _club("AC Milan", "Serie A", "stripes", ["#FB090B", "#000000", "#FFFFFF"], "MIL"),
    "milan": _club("AC Milan", "Serie A", "stripes", ["#FB090B", "#000000", "#FFFFFF"], "MIL"),
    "bologna": _club("Bologna", "Serie A", "stripes", ["#9F1B32", "#1A2F48", "#FFFFFF"], "BOL"),
    "como": _club("Como", "Serie A", "solid", ["#004E9E", "#FFFFFF", "#FFFFFF"], "COM"),
    "empoli": _club("Empoli", "Serie A", "solid", ["#00579C", "#FFFFFF", "#FFFFFF"], "EMP"),
    "fiorentina": _club("Fiorentina", "Serie A", "solid", ["#582C83", "#FFFFFF", "#FFFFFF"], "FIO"),
    "juventus": _club("Juventus", "Serie A", "stripes", ["#000000", "#FFFFFF", "#FFFFFF"], "JUV"),
    "napoli": _club("Napoli", "Serie A", "solid", ["#12A0D7", "#FFFFFF", "#003D7C"], "NAP"),
    "parma": _club("Parma", "Serie A", "cross", ["#FFFFFF", "#000000", "#FFD100"], "PAR"),
    "roma": _club("Roma", "Serie A", "solid", ["#8E1F2F", "#F0BC42", "#F0BC42"], "ROM"),
    "sassuolo": _club("Sassuolo", "Serie A", "stripes", ["#00A752", "#000000", "#FFFFFF"], "SAS"),
    # --- Germany ---
    "bayern": _club("Bayern Munich", "Bundesliga", "solid", ["#DC052D", "#FFFFFF", "#0066B2"], "FCB"),
    "dortmund": _club("Borussia Dortmund", "Bundesliga", "solid", ["#FDE100", "#000000", "#000000"], "BVB"),
    "hoffenheim": _club("Hoffenheim", "Bundesliga", "solid", ["#1C63B7", "#FFFFFF", "#FFFFFF"], "TSG"),
    # --- France ---
    "lyon": _club("Olympique Lyonnais", "Ligue 1", "solid", ["#FFFFFF", "#122A6A", "#DA291C"], "OL"),
    "marseille": _club("Olympique de Marseille", "Ligue 1", "solid", ["#FFFFFF", "#2FAEE0", "#2FAEE0"], "OM"),
    "monaco": _club("AS Monaco", "Ligue 1", "diagonal", ["#E63329", "#FFFFFF", "#E63329"], "ASM"),
    # --- Brazil ---
    "bahia": _club("EC Bahia", "Brasileirão", "hoops", ["#0A54A0", "#E30613", "#FFFFFF"], "BAH"),
    "botafogo": _club("Botafogo", "Brasileirão", "stripes", ["#000000", "#FFFFFF", "#FFFFFF"], "BOT"),
    "corinthians": _club("Corinthians", "Brasileirão", "solid", ["#FFFFFF", "#000000", "#000000"], "COR"),
    "cruzeiro": _club("Cruzeiro", "Brasileirão", "solid", ["#0B5BA9", "#FFFFFF", "#FFFFFF"], "CRU"),
    "flamengo": _club("Flamengo", "Brasileirão", "hoops", ["#C52613", "#000000", "#FFFFFF"], "FLA"),
    "fluminense": _club("Fluminense", "Brasileirão", "stripes", ["#8C1D40", "#006B54", "#FFFFFF"], "FLU"),
    "fortaleza": _club("Fortaleza", "Brasileirão", "stripes", ["#0A2C6B", "#E30613", "#FFFFFF"], "FOR"),
    "internacional": _club("Internacional", "Brasileirão", "solid", ["#E5050F", "#FFFFFF", "#FFFFFF"], "INT"),
    "palmeiras": _club("Palmeiras", "Brasileirão", "solid", ["#006437", "#FFFFFF", "#FFFFFF"], "PAL"),
    "remo": _club("Clube do Remo", "Brazil", "solid", ["#10327E", "#FFFFFF", "#FFFFFF"], "REM"),
    "santos": _club("Santos", "Brasileirão", "solid", ["#FFFFFF", "#000000", "#000000"], "SAN"),
    "saopaolo": _club("São Paulo", "Brasileirão", "hoops", ["#FFFFFF", "#E30613", "#000000"], "SAO"),
    "saopaulo": _club("São Paulo", "Brasileirão", "hoops", ["#FFFFFF", "#E30613", "#000000"], "SAO"),
    # --- Mexico ---
    "atlas": _club("Atlas", "Liga MX", "stripes", ["#000000", "#E30613", "#FFFFFF"], "ATS"),
    "chivas": _club("Chivas Guadalajara", "Liga MX", "stripes", ["#CE1126", "#FFFFFF", "#0B2B5B"], "CHV"),
    "pumas": _club("Pumas UNAM", "Liga MX", "solid", ["#00224B", "#F5B731", "#F5B731"], "PUM"),
    # --- MLS ---
    "crew": _club("Columbus Crew", "MLS", "solid", ["#FFF200", "#000000", "#000000"], "CLB"),
    "dynamo": _club("Houston Dynamo", "MLS", "solid", ["#F4811F", "#101820", "#101820"], "HOU"),
    "earthquakes": _club("San Jose Earthquakes", "MLS", "solid", ["#0067B1", "#000000", "#000000"], "SJ"),
    "fire": _club("Chicago Fire", "MLS", "solid", ["#D40000", "#141B4D", "#FFFFFF"], "CHI"),
    "galaxy": _club("LA Galaxy", "MLS", "solid", ["#00245D", "#FFFFFF", "#F5B32B"], "LA"),
    "intermiami": _club("Inter Miami", "MLS", "solid", ["#F7B5CD", "#000000", "#000000"], "MIA"),
    "rapids": _club("Colorado Rapids", "MLS", "solid", ["#862633", "#9CC2E5", "#FFFFFF"], "COL"),
    "redbulls": _club("New York Red Bulls", "MLS", "solid", ["#FFFFFF", "#E32219", "#002D62"], "RBNY"),
    "revolution": _club("New England Revolution", "MLS", "solid", ["#0A2240", "#CE0E2D", "#FFFFFF"], "NE"),
    "sounders": _club("Seattle Sounders", "MLS", "solid", ["#5D9741", "#005596", "#FFFFFF"], "SEA"),
    "timbers": _club("Portland Timbers", "MLS", "solid", ["#004812", "#D69A00", "#D69A00"], "PTL"),
    "whitecaps": _club("Vancouver Whitecaps", "MLS", "solid", ["#00245E", "#9DC2E7", "#FFFFFF"], "VAN"),
    # --- NWSL and its predecessors ---
    "angelcity": _club("Angel City", "NWSL", "solid", ["#000000", "#F4B6C7", "#C9A227"], "ACFC"),
    "breakers": _club("Boston Breakers", "NWSL", "solid", ["#0057A0", "#FFFFFF", "#FFFFFF"], "BOS"),
    "courage": _club("North Carolina Courage", "NWSL", "solid", ["#00205B", "#7BAFD4", "#FFFFFF"], "NC"),
    "current": _club("Kansas City Current", "NWSL", "solid", ["#008C95", "#C8102E", "#FFFFFF"], "KC"),
    "dash": _club("Houston Dash", "NWSL", "solid", ["#F4811F", "#101820", "#FFFFFF"], "HOU"),
    "freedom": _club("Washington Freedom", "WUSA", "solid", ["#0C2340", "#C8102E", "#FFFFFF"], "WAS"),
    "gothamcity": _club("Gotham FC", "NWSL", "solid", ["#000000", "#00B2A9", "#FFFFFF"], "GFC"),
    "pride": _club("Orlando Pride", "NWSL", "solid", ["#633492", "#FFFFFF", "#FFFFFF"], "ORL"),
    "redstars": _club("Chicago Red Stars", "NWSL", "solid", ["#0C2340", "#C8102E", "#FFFFFF"], "CRS"),
    "reign": _club("Seattle Reign", "NWSL", "solid", ["#00447C", "#8A8D8F", "#FFFFFF"], "RGN"),
    "spirit": _club("Washington Spirit", "NWSL", "solid", ["#0B1B3F", "#C8102E", "#FFFFFF"], "WAS"),
    "thorns": _club("Portland Thorns", "NWSL", "solid", ["#8A1538", "#000000", "#FFFFFF"], "POR"),
    "wave": _club("San Diego Wave", "NWSL", "solid", ["#0C2340", "#00A3E0", "#FFFFFF"], "SD"),
    # --- USL and NASL ---
    "railhawks": _club("Carolina RailHawks", "NASL", "solid", ["#C8102E", "#002855", "#FFFFFF"], "RHK"),
    "riverhounds": _club("Pittsburgh Riverhounds", "USL", "solid", ["#FFB81C", "#000000", "#000000"], "PIT"),
    "rowdies": _club("Tampa Bay Rowdies", "USL", "solid", ["#00843D", "#FFD100", "#FFD100"], "TBR"),
    # --- Australia ---
    "matildas": _club("Matildas", "Australia", "solid", ["#FFB81C", "#00843D", "#00843D"], "AUS"),
    "sydney": _club("Sydney FC", "A-League", "solid", ["#00205B", "#7EC8E3", "#FFFFFF"], "SYD"),
}

# Roster names that point at a club under a different word.
ALIASES = {
    "city": "manchestercity",
    "villa": "astonvilla",
    "blackpoolfc": "blackpool",
    "gotham": "gothamcity",
    "interMiami": "intermiami",
    "manchestercityfc": "manchestercity",
    "realmadridfc": "madrid",
    "redbullsfc": "redbulls",
}


# --- crests for teams with no real club behind them -----------------------

COLOR_WORDS = {
    "red": ["#C8102E", "#FFFFFF", "#FFFFFF"],
    "blue": ["#1A4F9C", "#FFFFFF", "#FFFFFF"],
    "navy": ["#0C2340", "#FFFFFF", "#FFFFFF"],
    "black": ["#1B1B1B", "#FFFFFF", "#FFFFFF"],
    "white": ["#FFFFFF", "#1B1B1B", "#1B1B1B"],
    "gold": ["#C9A227", "#1B1B1B", "#FFFFFF"],
    "silver": ["#AEB6BF", "#1B1B1B", "#FFFFFF"],
    "bronze": ["#A3702A", "#FFFFFF", "#FFFFFF"],
    "teal": ["#0E8C8C", "#FFFFFF", "#FFFFFF"],
    "green": ["#0F7A45", "#FFFFFF", "#FFFFFF"],
    "purple": ["#5B2B82", "#FFFFFF", "#FFFFFF"],
    "orange": ["#E06A1B", "#1B1B1B", "#FFFFFF"],
    "sky": ["#4BA3DD", "#0C2340", "#FFFFFF"],
}

# Used when nothing in the name says anything about color. Picked by a hash of
# the name, so a team keeps the same crest from one refresh to the next.
FALLBACK = [
    ["#2F5D8C", "#FFFFFF", "#FFFFFF"],
    ["#1F7A6B", "#FFFFFF", "#FFFFFF"],
    ["#8C3B2F", "#FFFFFF", "#FFFFFF"],
    ["#5B4B8A", "#FFFFFF", "#FFFFFF"],
    ["#2C6E49", "#FFFFFF", "#FFFFFF"],
    ["#A66A1E", "#1B1B1B", "#FFFFFF"],
    ["#33566E", "#FFFFFF", "#FFFFFF"],
    ["#7A2E4A", "#FFFFFF", "#FFFFFF"],
    ["#1D6FA3", "#FFFFFF", "#FFFFFF"],
    ["#4E7A22", "#FFFFFF", "#FFFFFF"],
    ["#93531C", "#1B1B1B", "#FFFFFF"],
    ["#6A3A70", "#FFFFFF", "#FFFFFF"],
]

STOPWORDS = {"fc", "the", "of", "and"}


def monogram(display):
    """Three letters for the front of the shield."""
    words = [w for w in re.findall(r"[A-Za-z]+", display) if w.lower() not in STOPWORDS]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:3].upper()
    if len(words) == 2:
        return (words[0][0] + words[1][:2]).upper()
    return "".join(w[0] for w in words)[:3].upper()


def identity(display):
    """Resolve a parsed team name to a crest.

    Returns the real club when the name is one, and a generated kit when it is
    not. ``real`` says which of the two happened, so the page can show the club
    line only where there is a club to show.
    """
    key = _key(display)
    key = ALIASES.get(key, key)
    entry = CLUBS.get(key)
    if entry:
        found = dict(entry)
        found["real"] = True
        found["source"] = "club"
        found["accent"] = accents(found["colors"])
        return found

    colors, source = None, "palette"
    for word in re.findall(r"[a-z]+", display.lower()):
        if word in COLOR_WORDS:
            colors, source = list(COLOR_WORDS[word]), "name"
            break
    if colors is None:
        colors = list(FALLBACK[_seed(key, 0) % len(FALLBACK)])

    return {
        "club": None,
        "comp": None,
        "pattern": "band" if _seed(key, 1) % 3 == 0 else "solid",
        "colors": colors,
        "code": monogram(display),
        "real": False,
        "source": source,
        "accent": accents(colors),
    }


def _seed(key, index):
    return hashlib.sha1(key.encode()).digest()[index]


# --- accent colors --------------------------------------------------------
#
# The crest can use a club's colors as they are. Everything else on the page --
# the stripe down a row, the tint behind the featured card -- cannot: white is
# invisible on a white page and black is invisible on a dark one. So each team
# also gets two accents, the same hue pushed into a range that reads on each
# background.


def _luminance(hex_color):
    r, g, b = _rgb(hex_color)

    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r, g, b):
    return "#{:02X}{:02X}{:02X}".format(*(round(c * 255) for c in (r, g, b)))


def _relight(hex_color, low, high):
    """Move a color until its luminance lands in [low, high], keeping its hue.

    Lightness and luminance are not the same thing -- Norwich yellow at half
    lightness is still bright enough to disappear on a white page, and navy at
    half lightness still reads as black on a dark one. So the search is run on
    luminance itself, which is what the eye is actually judging.
    """
    here = _luminance(hex_color)
    if low <= here <= high:
        return hex_color.upper()

    target = high if here > high else low
    r, g, b = _rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)

    lo, hi = (0.0, l) if here > high else (l, 1.0)
    for _ in range(24):  # luminance rises with lightness, so bisection is safe
        mid = (lo + hi) / 2
        candidate = _hex(*colorsys.hls_to_rgb(h, mid, s))
        if _luminance(candidate) < target:
            lo = mid
        else:
            hi = mid
    return _hex(*colorsys.hls_to_rgb(h, (lo + hi) / 2, s))


def _neutralize(hex_color):
    """Strip the last trace of hue off a near-grey.

    Newcastle's black has a red cast in it. Left alone, a 3px accent drawn from
    it reads as maroon; the club is black and white.
    """
    r, g, b = _rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.12:
        return _hex(*colorsys.hls_to_rgb(h, l, 0.0))
    return hex_color.upper()


def _washed_out(hex_color):
    """True for white and the near-greys -- a color that cannot carry a page.

    Bright but saturated colors (Dortmund yellow, Coventry sky) are left alone;
    they are the club's identity and they survive being darkened.
    """
    r, g, b = _rgb(hex_color)
    _, _, s = colorsys.rgb_to_hls(r, g, b)
    return s < 0.25 and _luminance(hex_color) > 0.5


def accents(colors):
    """Pick the color that carries a team's identity, in both themes.

    A club whose first color is white or near-white (Real Madrid, Fulham) is
    read by its second: the page would otherwise draw it in invisible ink.
    """
    base = colors[0]
    if _washed_out(base):
        for other in colors[1:]:
            if not _washed_out(other):
                base = other
                break
    base = _neutralize(base)
    return {
        "light": _relight(base, 0.0, 0.34),
        "dark": _relight(base, 0.26, 0.72),
    }


# --- what the page gets ---------------------------------------------------


def describe(name):
    """Everything the page needs to draw one team."""
    parsed = parse(name)
    crest = identity(parsed["display"])
    parsed["identity"] = crest
    return parsed


def spread_palette(teams):
    """Keep two invented kits in one division from landing on the same color.

    Only the kits drawn from the palette move. A club's real colors and a kit
    taken from a color in the team's own name ('WF United Red') are what they
    are, even when two of them are close.
    """
    taken = {t["identity"]["colors"][0] for t in teams
             if t["identity"].get("source") != "palette"}
    for team in sorted(teams, key=lambda t: t["name"]):
        crest = team["identity"]
        if crest.get("source") != "palette":
            continue
        start = _seed(team["key"], 0) % len(FALLBACK)
        for offset in range(len(FALLBACK)):
            colors = FALLBACK[(start + offset) % len(FALLBACK)]
            if colors[0] not in taken:
                break
        crest["colors"] = list(colors)
        crest["accent"] = accents(colors)
        taken.add(colors[0])
    return teams


def decorate(payload):
    """Attach display parts and crests to every team in a built payload.

    Runs at render time rather than fetch time: these are presentation, not
    results, so they stay out of data/rankings.json and a change here shows up
    on the next build with no refetch.
    """
    for division in payload.get("divisions", []):
        for team in division.get("teams", []):
            described = describe(team["name"])
            team["short"] = described["display"]
            team["org"] = described["org"]
            team["host"] = described["host"]
            team["site"] = described["site"]
            team["girls"] = described["girls"]
            team["key"] = described["key"]
            team["identity"] = described["identity"]
        spread_palette(division.get("teams", []))
        names = {t["id"]: t["short"] for t in division.get("teams", [])}
        for team in division.get("teams", []):
            for game in team.get("resume", []):
                game["opponent"] = names.get(game["opponent_id"], game["opponent"])
        for fixture in division.get("upcoming", []):
            fixture["home"] = names.get(fixture["home_id"], fixture["home"])
            fixture["away"] = names.get(fixture["away_id"], fixture["away"])
            fixture["favorite"] = names.get(fixture["favorite_id"], fixture["favorite"])
    return payload
