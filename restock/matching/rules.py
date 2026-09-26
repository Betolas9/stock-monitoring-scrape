"""Keyword rules used to classify store listings.

Every regex runs on text.norm() output: lowercase, no accents, and any
punctuation collapsed to single spaces ("Build & Battle" → "build and battle",
"OP-13" → "op 13", "SV08.5" → "sv08 5").
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- TCGs

TCGS: dict[str, str] = {
    "pokemon":    "Pokémon",
    "onepiece":   "One Piece",
    "mtg":        "Magic: The Gathering",
    "lorcana":    "Disney Lorcana",
    "yugioh":     "Yu-Gi-Oh!",
    "digimon":    "Digimon",
    "dbs":        "Dragon Ball Super",
    "riftbound":  "Riftbound",
    "swu":        "Star Wars: Unlimited",
    "fab":        "Flesh and Blood",
    "gundam":     "Gundam Card Game",
    "unionarena": "Union Arena",
    "weiss":      "Weiss Schwarz",
    "sorcery":    "Sorcery",
    "palworld":   "Palworld",
}

TCG_PATTERNS: list[tuple[str, re.Pattern]] = [
    (k, re.compile(p)) for k, p in [
        ("pokemon",    r"\bpokemon\b|\bpkmn\b|\bptcg\b|\bpokeball\b|\bpoke ball\b"),
        ("onepiece",   r"\bone piece\b|\boptcg\b"),
        ("mtg",        r"\bmagic the gathering\b|\bmtg\b|\bmagic\b"),
        ("lorcana",    r"\blorcana\b"),
        ("yugioh",     r"\byu ?gi ?oh\b|\bygo\b"),
        ("digimon",    r"\bdigimon\b"),
        ("dbs",        r"\bdragon ball\b|\bdbs\b|\bfusion world\b"),
        ("riftbound",  r"\briftbound\b|\bleague of legends\b"),
        ("swu",        r"\bstar wars unlimited\b"),
        ("fab",        r"\bflesh and blood\b|\bflesh blood\b"),
        ("gundam",     r"\bgundam card game\b|\bgundam tcg\b|\bgcg\b"),
        ("unionarena", r"\bunion arena\b"),
        ("weiss",      r"\bweiss schwarz\b"),
        ("sorcery",    r"\bsorcery contested realm\b|\bsorcery tcg\b"),
        ("palworld",   r"\bpalworld\b"),
    ]
]

# Product-type words that only exist in one game
TCG_IMPLIED_BY_TYPE: list[tuple[str, re.Pattern]] = [
    ("pokemon", re.compile(r"\belite trainer box\b|\betb\b|\bbuild and battle\b|\bpoke ball tin\b"
                           r"|\bex (special |premium |super premium )?collections?\b|\bex (box|tin)\b"
                           r"|\bleague battle deck\b|\bbattle academy\b|\bcaixa (de )?treinador (de )?elite\b")),
    ("mtg",     re.compile(r"\bplay boosters?\b|\bcollector boosters?\b|\bcommander deck\b|\bset boosters?\b")),
    ("onepiece", re.compile(r"\b(op|eb|prb) ?\d{2}\b")),
    ("dbs",     re.compile(r"\bfb ?\d{2}\b")),
]

# --------------------------------------------------------------------------- types

# (key, label, regex, unique)
# unique=True: a set normally has exactly one product of this type, so all
# listings with the same set+type+language are the same product. Non-unique
# types (tins, collections, blisters…) also need the leftover name words
# (e.g. the featured Pokémon) to tell products apart.
TYPES: list[tuple[str, str, str, bool]] = [
    ("case", "Case",
     r"\b(booster box|booster display|display|etb|elite trainer box|booster bundle)e?s? case\b"
     r"|\bsealed case\b|\bbooster case\b|\bcase of \d+\b|\bcaixa de \d+ displays?\b", True),
    ("collector-booster-box", "Collector Booster Box",
     r"\bcollector booster (box|display)\b|\bcollector display\b|\bcollector box\b", True),
    ("booster-bundle", "Booster Bundle",
     r"\bbooster bundle\b|\bbundle (de|of) (6 )?boosters?\b|\b6 packs? bundle\b|\bgift bundle\b|\bbundle\b", True),
    ("etb", "Elite Trainer Box",
     r"\belite trainer box(es)?\b|\betb\b|\belite trainer\b|\bcaixa (de )?treinador (de )?elite\b", True),
    ("booster-box", "Booster Box",
     r"\b(play |draft |set )?booster (box|display)\b|\bdisplay\b|\bcaixa de boosters?\b"
     r"|\bbox de boosters?\b|\b(36|24|30|18) (booster )?(packs|boosters|saquetas)\b|\bcaixa completa\b", True),
    ("build-battle", "Build & Battle", r"\bbuild and battle\b|\bbuild battle\b", False),
    ("upc", "Ultra Premium Collection", r"\bultra premium collection\b|\bupc\b", False),
    ("sleeved-booster", "Sleeved Booster", r"\bsleeved boosters?\b", True),
    ("mini-tin", "Mini Tin", r"\bmini (tin|lata)s?\b", False),
    ("tin", "Tin", r"\btins?\b|\blatas?\b", False),
    ("blister", "Blister",
     r"\bblisters?\b|\b(2|3|two|three) (booster )?packs?\b|\bcheck ?lane\b|\btripack\b|\b3pk\b", False),
    ("deck", "Deck", r"\bdecks?\b|\bbaralhos?\b", False),
    ("collection", "Collection",
     r"\bcollections?\b|\bcolecao\b|\bcoleccion\b|\bpremium\b|\bbox set\b|\bex box\b|\bspecial (set|box)\b"
     r"|\bgift box\b|\bchest\b|\bbau\b|\bbinder\b|\bportfolio\b|\bsurprise box\b|\bmystery box\b"
     r"|\bcelebration box\b|\bcalendar\b|\bcalendario\b|\badvent\b|\btech sticker\b|\bscene box\b"
     r"|\bsecret lair\b|\bstarter kit\b|\bbeginner box\b|\bpre ?rift kit\b|\bprerelease (kit|pack)\b|\bjumpstart\b"
     r"|\bcoffrets?\b|\bcoffre\b|\btrove\b|\billumineer\b", False),
    ("booster-pack", "Booster Pack",
     r"\bboosters?( packs?)?\b|\bsaquetas?\b|\bpacks?\b|\bpacotes?\b|\benvelopes?\b", True),
]
TYPE_PATTERNS = [(k, re.compile(p)) for k, _l, p, _u in TYPES]
TYPE_LABELS = {k: l for k, l, _p, _u in TYPES}
TYPE_LABELS["other"] = "Other"
UNIQUE_TYPES = {k for k, _l, _p, u in TYPES if u}

# Variant flags that split otherwise-unique types
UNIQUE_VARIANTS: list[tuple[str, str, re.Pattern]] = [
    ("pokemon-center", "Pokémon Center", re.compile(r"\bpokemon center\b|\bpc exclusive\b|\bpc etb\b")),
    ("enhanced", "Enhanced", re.compile(r"\benhanced\b")),
    ("half", "Half", re.compile(r"\bhalf\b")),
    ("mini", "Mini", re.compile(r"\bmini\b")),
]

# --------------------------------------------------------------------------- languages

LANGS: dict[str, str] = {
    "en": "English", "jp": "Japanese", "cn": "Chinese", "kr": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
}

LANG_PATTERNS: list[tuple[str, re.Pattern]] = [
    (k, re.compile(p)) for k, p in [
        ("jp", r"\bjapanese\b|\bjapones(a)?\b|\bjapon\b|\bjapao\b|\bjap\b|\bjp\b|\bjpn\b|\bjapan\b"),
        ("cn", r"\bchinese\b|\bchines(a)?\b|\bcn\b|\bchn\b|\bs chinese\b|\bt chinese\b"),
        ("kr", r"\bkorean\b|\bcoreano\b|\bcoreana\b|\bkr\b|\bkor\b"),
        ("fr", r"\bfrench\b|\bfrances(a)?\b|\bfrancais\b|\bfr\b"),
        ("de", r"\bgerman\b|\balemao\b|\balema\b|\bdeutsch\b"),
        ("es", r"\bspanish\b|\bespanhol\b|\bespanol\b|\bcastellano\b"),
        ("it", r"\bitalian\b|\bitaliano\b"),
        ("pt", r"\bportugues(a)?\b|\bportuguese\b|\bpt br\b|\bptbr\b"),
        ("en", r"\benglish\b|\bingles(a)?\b|\beng\b|\ben\b"),
    ]
]

# --------------------------------------------------------------------------- kinds

# Card-number patterns run on fold()-ed (not norm()-ed) text, to keep the "/"
SINGLE_RAW = re.compile(
    r"\b\d{1,3}\s?/\s?\d{2,3}\b"                           # 199/165
    r"|#\d{1,3}\b"                                          # Holo #014
    r"|\([a-z]{2,4}\s\d{1,3}\)"                             # (SVI 167)
    r"|\b(op|eb|st|prb)\d{2}-\d{3}\b"                       # OP05-119
)
SINGLE_NORM = re.compile(
    r"\bpsa ?\d+\b|\bcgc\b|\bbgs\b|\bgraded\b|\bsingles?\b|\bcartas? (avulsas?|soltas?)\b"
    r"|\bnear mint\b|\breverse holo\b|\bfull art\b|\balt art\b|\bsecret rare\b|\bhyper rare\b"
    r"|\b(special )?illustration rare\b|\bultra rare\b|\bholo rare\b|\bdouble rare\b|\bpromo cards?\b"
    r"|\breverse hol+o\b"
)

# Merchandise that shares the TCG's name but isn't a card product
MERCH = re.compile(
    r"\bplush(es)?\b|\bpeluches?\b|\bfunko\b|\bpop vinyl\b|\bvinyl figure\b|\bfigures?\b|\bfiguras?\b"
    r"|\bfigurine\b|\bt shirt\b|\btshirt\b|\bcamisola\b|\bcaneca\b|\bmug\b|\bpuzzle\b|\blego\b|\bmochila\b"
    r"|\bbackpack\b|\bkeychain\b|\bporta chaves\b|\bmodel kit\b|\bstatue\b|\bestatua\b|\bnendoroid\b"
    r"|\bamiibo\b|\bvideojogo\b|\bnintendo switch\b|\bmanga\b|\blivro\b|\bbattle spinner\b|\bsquishmallow\b"
)
# … unless the name also clearly says it's a card product
MERCH_UNLESS = re.compile(
    r"\bfigure collection\b|\bcollection box\b|\bboosters?\b|\btcg\b|\btrading card\b|\belite trainer\b"
)
# Box/pack "breaks" (a seller opens product live for you) are a service
SERVICE = re.compile(r"\bbreaks?\b|\bslots?\b|\brandom team\b")

SINGLE_META = re.compile(r"\bsingles?\b|\bsingle cards?\b|\bcartas? (soltas|avulsas|individuais)\b")

ACCESSORY = re.compile(
    r"\bsleeves?\b|\bplaymats?\b|\btapetes?\b|\btoploaders?\b|\bdeck ?box(es)?\b|\bdeckbox\b|\bdados\b"
    r"|\bdice\b|\bstorage box\b|\bbinder\b|\bportfolio\b|\balbum\b|\bpasta\b|\bprotetor(es)?\b"
    r"|\bprotectors?\b|\bcard saver\b|\bmagnetic\b|\bone touch\b|\bdragon shield\b|\bultra pro\b"
    r"|\bultimate guard\b|\bgamegenic\b|\bkatana sleeves\b|\bperfect fit\b|\bcapas\b"
)
ACCESSORY_UNLESS = re.compile(r"\bcollection\b|\bcolecao\b|\bboosters?\b|\betb\b|\belite trainer\b|\bbundle\b")

PREORDER = re.compile(
    r"\bpre ?venda\b|\bprevenda\b|\bpre ?order\b|\bpreorder\b|\bpre ?encomenda\b|\bpre ?reserva\b"
    r"|\breserva\b|\bpre ?sale\b|\bpresale\b"
)

# Pokémon era names that also appear in front of the actual set name
# ("Mega Evolution: Perfect Order ETB") — stripped before looking for a set,
# unless nothing else matches (the ME01 set itself is called "Mega Evolution").
SERIES_PHRASES = [
    "mega evolution", "scarlet and violet", "scarlet violet", "sword and shield", "sword shield",
    "escarlate e violeta", "espada e escudo", "sun and moon",
]

# Words dropped when computing a product's distinguishing leftover words
STOPWORDS = set("""
a o os as e and the of de do da dos das em no na com with for para por vs
pokemon tcg trading card cards game games jogo jogos carta cartas cartes
one piece magic gathering mtg lorcana yugioh yu gi oh digimon dragon ball riftbound
en eng english ingles inglesa pt versao version edition edicao lingua language idioma
jp jap japanese japones japonesa cn chinese chines kr korean coreano fr french de german es it
league battle new novo nova pre venda prevenda order preorder encomenda reserva sale presale sealed selado selada
oficial official original exclusive exclusivo exclusiva limited
box caixa pack packs set sets product produto item unidade unidades un 1un triple tripack pk
ex gx vmax vstar tera
""".split())
