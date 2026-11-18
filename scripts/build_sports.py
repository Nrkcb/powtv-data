#!/usr/bin/env python3
"""
Construit sports.json pour le Sport Hub de POWTV.

Tourne une fois par jour dans une GitHub Action du dépôt powtv-data, puis le
fichier est publié sur GitHub Pages. Les applications le téléchargent une fois
par jour : aucun appel à Supabase, aucune clé dans l'application.

Sources :
  - football-data.org (clé lue dans la variable FOOTBALL_DATA_KEY, un Secret
    du dépôt). Une seule requête pour tous les championnats.
  - Jolpica (API compatible Ergast) pour la Formule 1, sans clé.

Le fichier reste aussi léger que possible :
  - les équipes sont décrites une seule fois (table "t"), les matchs ne
    portent que leurs identifiants ;
  - les mots-clés sont déjà normalisés (minuscules, sans accents), l'app les
    compare tels quels aux titres du guide TV normalisés de la même façon.

Format (v = 1) :
{
  "v": 1,
  "g": <généré le, epoch secondes>,
  "c": {"PL": "Premier League", ...},
  "t": {"<id>": {"n": "<nom court>", "k": ["mot clé", ...]}, ...},
  "m": [{"i": <id>, "c": "PL", "s": <coup d'envoi epoch s>, "h": <id>, "a": <id>}, ...],
  "f": [{"i": "<id>", "s": <début epoch s>, "q": "R|Q|S|SQ", "n": "<nom du GP>", "k": [...]}, ...]
}

Sans dépendance : bibliothèque standard Python 3.9+.
"""

import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

# Championnats et coupes inclus dans l'offre gratuite de football-data.org.
COMPETITIONS = ["CL", "PL", "PD", "BL1", "SA", "FL1", "DED", "PPL", "EC", "WC"]

COMPETITION_NAMES = {
    "CL": "Champions League",
    "PL": "Premier League",
    "PD": "LaLiga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "DED": "Eredivisie",
    "PPL": "Liga Portugal",
    "EC": "Euro",
    "WC": "World Cup",
    "F1": "Formula 1",
}

# Fenêtre : la veille (pour le replay) jusqu'à J+7.
DAYS_BEFORE = 1
DAYS_AFTER = 7

# Statuts écartés : match qui n'aura pas lieu à l'heure prévue.
SKIP_STATUS = {"POSTPONED", "CANCELLED", "SUSPENDED", "AWARDED"}

# Mots retirés des noms officiels pour obtenir le nom « parlé ».
CLUB_TOKENS = {
    "fc", "afc", "cf", "sc", "ac", "as", "ssc", "sv", "vfb", "vfl", "tsg", "fk",
    "cd", "ud", "rc", "rcd", "sd", "ca", "club", "de", "futbol", "football",
    "calcio", "1", "04", "05", "1899", "1846", "1900", "1909", "1910", "1913",
    "bc", "ogc", "losc", "stade", "olympique", "sporting", "real", "us", "hsc",
    "fsv", "bsc", "sad", "cp", "sl", "e", "da", "do", "y", "balompie", "cfc",
}

# Mots trop courts ou trop communs pour identifier une équipe seule.
TOO_GENERIC = {
    "real", "city", "united", "sporting", "athletic", "atletico", "inter",
    "olympique", "stade", "club", "racing", "deportivo", "union", "borussia",
    "eintracht", "hertha", "fortuna", "dynamo", "lokomotiv", "national",
    # Villes qui ont plusieurs clubs : « madrid » seul ne désigne personne.
    "madrid", "milan", "milano", "manchester", "london", "glasgow", "lisboa",
    "lisbon", "paris", "munchen", "munich", "sevilla", "turin", "torino",
    "rome", "roma", "genova", "liverpool", "bristol", "sheffield", "istanbul",
}

# Noms usuels dans les guides TV européens (FR, EN, DE, ES, IT, PT, TR, NL).
# Clé = nom normalisé de football-data (name ou shortName), valeur = variantes.
ALIASES = {
    "paris saint germain": ["psg", "paris sg", "paris saint germain", "paris st germain"],
    "olympique de marseille": ["marseille", "om", "olympique de marseille"],
    "olympique lyonnais": ["lyon", "ol", "olympique lyonnais"],
    "as monaco": ["monaco"],
    "losc lille": ["lille", "losc"],
    "stade rennais": ["rennes", "stade rennais"],
    "ogc nice": ["nice", "ogc nice"],
    "rc lens": ["lens", "rc lens"],
    "fc bayern munchen": ["bayern", "bayern munich", "bayern munchen", "bayern munique", "bayern monaco"],
    "borussia dortmund": ["dortmund", "bvb", "borussia dortmund"],
    "bayer 04 leverkusen": ["leverkusen", "bayer leverkusen"],
    "rb leipzig": ["leipzig", "rb leipzig"],
    "borussia monchengladbach": ["gladbach", "monchengladbach", "borussia monchengladbach"],
    "eintracht frankfurt": ["frankfurt", "francfort", "eintracht frankfurt"],
    "vfb stuttgart": ["stuttgart"],
    "real madrid cf": ["real madrid"],
    "fc barcelona": ["barcelona", "barcelone", "barca", "barcelona fc"],
    "club atletico de madrid": ["atletico madrid", "atletico de madrid", "atleti"],
    "sevilla fc": ["sevilla", "seville", "seville fc"],
    "real sociedad de futbol": ["real sociedad"],
    "real betis balompie": ["betis", "real betis"],
    "villarreal cf": ["villarreal"],
    "athletic club": ["athletic bilbao", "bilbao", "athletic club"],
    "valencia cf": ["valencia", "valence"],
    "fc internazionale milano": ["inter milan", "internazionale", "inter milano", "inter de milan"],
    "ac milan": ["ac milan", "milan ac", "milan"],
    "juventus fc": ["juventus", "juve"],
    "ssc napoli": ["napoli", "naples"],
    "as roma": ["as roma", "roma"],
    "ss lazio": ["lazio"],
    "atalanta bc": ["atalanta"],
    "acf fiorentina": ["fiorentina"],
    "manchester united fc": ["manchester united", "man utd", "man united"],
    "manchester city fc": ["manchester city", "man city"],
    "liverpool fc": ["liverpool"],
    "everton fc": ["everton"],
    "arsenal fc": ["arsenal"],
    "chelsea fc": ["chelsea"],
    "tottenham hotspur fc": ["tottenham", "spurs"],
    "newcastle united fc": ["newcastle"],
    "aston villa fc": ["aston villa"],
    "west ham united fc": ["west ham"],
    "sport lisboa e benfica": ["benfica"],
    "fc porto": ["porto", "fc porto"],
    "sporting clube de portugal": ["sporting cp", "sporting lisbon", "sporting lisbonne", "sporting portugal"],
    "sc braga": ["braga"],
    "afc ajax": ["ajax", "ajax amsterdam"],
    "psv": ["psv", "psv eindhoven"],
    "feyenoord rotterdam": ["feyenoord"],
    "az": ["az alkmaar"],
    "galatasaray sk": ["galatasaray"],
    "fenerbahce sk": ["fenerbahce"],
    "besiktas jk": ["besiktas"],
    "celtic fc": ["celtic"],
    "rangers fc": ["rangers"],
    "club brugge kv": ["club brugge", "bruges", "club bruges"],
    "rsc anderlecht": ["anderlecht"],
    "fc red bull salzburg": ["salzburg", "salzbourg"],
    "gnk dinamo zagreb": ["dinamo zagreb"],
    "fk crvena zvezda": ["crvena zvezda", "red star belgrade", "etoile rouge"],
    "fc shakhtar donetsk": ["shakhtar", "chakhtar"],
}

# Équipes nationales (Euro, Coupe du monde) : nom dans les 7 langues de l'app.
NATIONS = {
    "france": ["france", "frankreich", "francia", "frankrijk", "fransa", "franca"],
    "germany": ["germany", "allemagne", "deutschland", "alemania", "duitsland", "almanya", "alemanha", "germania"],
    "spain": ["spain", "espagne", "spanien", "espana", "spanje", "ispanya", "espanha", "spagna"],
    "italy": ["italy", "italie", "italien", "italia", "italie", "italya"],
    "england": ["england", "angleterre", "inglaterra", "engeland", "ingiltere", "inghilterra"],
    "portugal": ["portugal", "portekiz", "portogallo"],
    "netherlands": ["netherlands", "pays bas", "niederlande", "paises bajos", "nederland", "hollanda", "holanda", "olanda"],
    "belgium": ["belgium", "belgique", "belgien", "belgica", "belgie", "belcika", "belgio"],
    "turkey": ["turkey", "turkiye", "turquie", "turkei", "turquia", "turkije", "turchia"],
    "switzerland": ["switzerland", "suisse", "schweiz", "suiza", "zwitserland", "isvicre", "suica", "svizzera"],
    "croatia": ["croatia", "croatie", "kroatien", "croacia", "kroatie", "hirvatistan", "croazia"],
    "brazil": ["brazil", "bresil", "brasilien", "brasil", "brazilie", "brezilya", "brasile"],
    "argentina": ["argentina", "argentine", "argentinien", "argentinie", "arjantin"],
    "morocco": ["morocco", "maroc", "marokko", "marruecos", "fas", "marrocos", "marocco"],
    "algeria": ["algeria", "algerie", "algerien", "argelia", "algerije", "cezayir"],
    "senegal": ["senegal"],
    "tunisia": ["tunisia", "tunisie", "tunesien", "tunez", "tunesie", "tunus"],
    "scotland": ["scotland", "ecosse", "schottland", "escocia", "schotland", "iskocya", "scozia"],
    "wales": ["wales", "pays de galles", "gales", "galler", "galles"],
    "austria": ["austria", "autriche", "osterreich", "oostenrijk", "avusturya"],
    "denmark": ["denmark", "danemark", "danemark", "dinamarca", "denemarken", "danimarka"],
    "poland": ["poland", "pologne", "polen", "polonia", "polonya", "polonia"],
    "usa": ["usa", "etats unis", "united states", "vereinigte staaten", "estados unidos", "verenigde staten", "abd", "stati uniti"],
    "mexico": ["mexico", "mexique", "mexiko", "meksika", "messico"],
}

# Pays des Grands Prix de F1 dans les 7 langues (le guide parle de « GP du Brésil »).
F1_COUNTRIES = {
    "australia": ["australie", "australien", "australie", "avustralya"],
    "china": ["chine", "china", "cin"],
    "japan": ["japon", "japan", "japao", "giappone", "japonya"],
    "bahrain": ["bahrein", "bahrain", "bahreyn"],
    "saudi arabia": ["arabie saoudite", "saudi arabien", "arabia saudi", "saoedi arabie", "suudi arabistan", "arabia saudita", "jeddah", "djeddah"],
    "usa": ["miami", "las vegas", "austin", "etats unis", "usa", "united states"],
    "italy": ["imola", "emilie romagne", "emilia romagna", "monza", "italie", "italien", "italia", "italya"],
    "monaco": ["monaco"],
    "spain": ["espagne", "spanien", "espana", "spanje", "ispanya", "espanha", "barcelone", "barcelona", "madrid"],
    "canada": ["canada", "kanada"],
    "austria": ["autriche", "osterreich", "austria", "oostenrijk", "avusturya"],
    "uk": ["grande bretagne", "silverstone", "british", "grossbritannien", "gran bretana", "groot brittannie", "ingiltere", "gra bretanha"],
    "belgium": ["belgique", "belgien", "belgica", "belgie", "belcika", "spa"],
    "hungary": ["hongrie", "ungarn", "hungria", "hongarije", "macaristan", "hungary"],
    "netherlands": ["pays bas", "niederlande", "paises bajos", "nederland", "hollanda", "zandvoort"],
    "azerbaijan": ["azerbaidjan", "aserbaidschan", "azerbaiyan", "azerbeidzjan", "azerbaycan", "bakou", "baku"],
    "singapore": ["singapour", "singapur", "singapore", "singapura"],
    "mexico": ["mexique", "mexiko", "mexico", "meksika"],
    "brazil": ["bresil", "brasilien", "brasil", "brazilie", "brezilya", "sao paulo", "interlagos"],
    "qatar": ["qatar", "katar", "catar"],
    "uae": ["abu dhabi", "abou dabi", "emirats", "abu dabi"],
}

F1_SESSIONS = [
    ("Qualifying", "Q"),
    ("Sprint", "S"),
    ("SprintQualifying", "SQ"),
    ("SprintShootout", "SQ"),
]


def norm(text):
    """Minuscules, sans accents, ponctuation → espaces. Même règle que l'app."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ß", "ss").replace("ı", "i").replace("ø", "o").replace("æ", "ae")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def http_json(url, headers=None, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "powtv-data/1.0", **(headers or {})})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            # 429 : l'offre gratuite autorise 10 requêtes par minute.
            time.sleep(15 if "429" in str(exc) else 5 * (attempt + 1))
    raise RuntimeError(f"échec {url} : {last}")


def to_epoch(date_str, time_str="00:00:00Z"):
    s = f"{date_str}T{time_str or '00:00:00Z'}".replace("Z", "+00:00")
    return int(dt.datetime.fromisoformat(s).timestamp())


def team_keywords(team):
    name = team.get("name") or ""
    short = team.get("shortName") or ""
    keys = []
    n_name, n_short = norm(name), norm(short)
    trimmed = re.sub(r"^(fc|afc|cf|sc) | (fc|afc|cf|sc)$", "", n_name).strip()
    for candidate in (n_name, n_short, trimmed):
        if candidate in ALIASES:
            keys += ALIASES[candidate]
        if candidate in NATIONS:
            keys += NATIONS[candidate]
    # Nom officiel sans les sigles de club : « Bayer 04 Leverkusen » → « bayer leverkusen ».
    stripped = " ".join(t for t in n_name.split() if t not in CLUB_TOKENS)
    for candidate in (n_short, stripped, n_name):
        if candidate and len(candidate) >= 4 and candidate not in TOO_GENERIC:
            keys.append(candidate)
    # Sans alias connu : premier mot distinctif (« wolverhampton wanderers »
    # → « wolverhampton »), comme on l'écrit dans un guide TV.
    words = [w for w in stripped.split() if len(w) >= 5 and w not in TOO_GENERIC]
    if words and not any(c in ALIASES or c in NATIONS for c in (n_name, n_short, trimmed)):
        keys.append(words[0])
    seen, out = set(), []
    for k in keys:
        k = norm(k)
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:8]


def fetch_football(today):
    key = os.environ.get("FOOTBALL_DATA_KEY", "").strip()
    if not key:
        print("FOOTBALL_DATA_KEY absent : pas de football.", file=sys.stderr)
        return {}, []
    date_from = (today - dt.timedelta(days=DAYS_BEFORE)).isoformat()
    # L'offre gratuite limite une requête à 10 jours.
    date_to = (today + dt.timedelta(days=DAYS_AFTER)).isoformat()
    url = (
        "https://api.football-data.org/v4/matches"
        f"?competitions={','.join(COMPETITIONS)}&dateFrom={date_from}&dateTo={date_to}"
    )
    data = http_json(url, headers={"X-Auth-Token": key})
    teams, matches = {}, []
    for m in data.get("matches", []):
        if m.get("status") in SKIP_STATUS:
            continue
        home, away = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        if not home.get("id") or not away.get("id"):
            continue  # phase finale dont les équipes ne sont pas encore connues
        for t in (home, away):
            tid = str(t["id"])
            if tid not in teams:
                teams[tid] = {"n": t.get("shortName") or t.get("name") or "?", "k": team_keywords(t)}
        matches.append({
            "i": m["id"],
            "c": (m.get("competition") or {}).get("code") or "?",
            "s": to_epoch(m["utcDate"][:10], m["utcDate"][11:]),
            "h": home["id"],
            "a": away["id"],
        })
    matches.sort(key=lambda x: x["s"])
    return teams, matches


def fetch_f1(today):
    data = http_json("https://api.jolpi.ca/ergast/f1/current/races.json?limit=40")
    races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    start = dt.datetime.combine(today - dt.timedelta(days=DAYS_BEFORE), dt.time(), dt.timezone.utc).timestamp()
    end = dt.datetime.combine(today + dt.timedelta(days=DAYS_AFTER + 1), dt.time(), dt.timezone.utc).timestamp()
    events = []
    for race in races:
        loc = (race.get("Circuit") or {}).get("Location") or {}
        country, locality = norm(loc.get("country")), norm(loc.get("locality"))
        keys = [k for k in (country, locality, norm(race.get("raceName", "").replace("Grand Prix", ""))) if k]
        for key, variants in F1_COUNTRIES.items():
            if key == country or key in keys or locality in variants:
                keys += variants
        seen, kws = set(), []
        for k in keys:
            if k and k not in seen:
                seen.add(k)
                kws.append(k)
        sessions = [(race, "R")] + [(race.get(f), code) for f, code in F1_SESSIONS if race.get(f)]
        for sess, code in sessions:
            if not sess.get("date"):
                continue
            s = to_epoch(sess["date"], sess.get("time"))
            if start <= s < end:
                events.append({
                    "i": f"{race.get('season')}-{race.get('round')}-{code}",
                    "s": s,
                    "q": code,
                    "n": race.get("raceName", "Grand Prix"),
                    "k": kws[:12],
                })
    events.sort(key=lambda x: x["s"])
    return events


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "public"
    os.makedirs(out_dir, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date()

    teams, matches = {}, []
    f1 = []
    try:
        teams, matches = fetch_football(today)
    except Exception as exc:  # une source en panne ne bloque pas l'autre
        print(f"football : {exc}", file=sys.stderr)
    try:
        f1 = fetch_f1(today)
    except Exception as exc:
        print(f"f1 : {exc}", file=sys.stderr)

    if not matches and not f1:
        # Mieux vaut garder le fichier de la veille que publier un fichier vide.
        print("Aucune donnée : publication annulée.", file=sys.stderr)
        sys.exit(1)

    used = {c["c"] for c in matches} | ({"F1"} if f1 else set())
    payload = {
        "v": 1,
        "g": int(time.time()),
        "c": {k: v for k, v in COMPETITION_NAMES.items() if k in used},
        "t": teams,
        "m": matches,
        "f": f1,
    }
    path = os.path.join(out_dir, "sports.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{path} : {len(matches)} matchs, {len(f1)} séances F1, {os.path.getsize(path)} octets")


if __name__ == "__main__":
    main()
