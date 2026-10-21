"""normaliser_fr.py : met en toutes lettres les nombres d'un texte francais avant la synthese vocale.

Pocket TTS n'a aucune conversion des chiffres : « 15 » doit lui arriver sous la forme « quinze ».
Les regles sont appliquees dans l'ordre, du plus specifique (heures, euros...) au plus general (entier).
"""
import re
from num2words import num2words

ESP = "[   ]"          # espace, insecable, fine insecable


def n(x: str) -> str:
    return num2words(int(x), lang="fr")


def n_fem(x: str) -> str:
    """« une » au lieu de « un » pour les noms feminins (heure)."""
    m = n(x)
    return re.sub(r"\bun$", "une", m)


def decimal(entier: str, frac: str) -> str:
    zeros = len(frac) - len(frac.lstrip("0"))
    reste = frac.lstrip("0")
    mots = ["zéro"] * zeros + ([n(reste)] if reste else [])
    return f"{n(entier)} virgule {' '.join(mots)}" if mots else n(entier)


def nombre(txt: str) -> str:
    """Entier ou decimal ecrit avec virgule ou point."""
    m = re.fullmatch(r"(-?)(\d+)(?:[,.](\d+))?", txt)
    signe = "moins " if m.group(1) else ""
    return signe + (decimal(m.group(2), m.group(3)) if m.group(3) else n(m.group(2)))


def pluriel(qte: str, mot: str) -> str:
    return mot if re.fullmatch(r"-?[01]([,.]0*)?", qte) else mot + "s"


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def date(j: str, m: str, a: str | None) -> str | None:
    j, m = int(j), int(m)
    if not (1 <= j <= 31 and 1 <= m <= 12):
        return None
    txt = ("premier" if j == 1 else n(str(j))) + " " + MOIS[m - 1]
    if a:
        a = int(a) + (2000 if len(a) == 2 else 0)
        txt += " " + n(str(a))
    return txt


def date_ou_brut(m, j, mo, a):
    r = date(j, mo, a)
    return r if r else m.group(0)


REGLES = [
    # dates : 21/10/2026  21-10-26  21.10.2026  21/10  et ISO 2026-10-21
    (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
     lambda m: date_ou_brut(m, m.group(3), m.group(2), m.group(1))),
    (r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b",
     lambda m: date_ou_brut(m, m.group(1), m.group(2), m.group(3))),
    (r"\b(\d{1,2})/(\d{1,2})\b(?!/)",
     lambda m: date_ou_brut(m, m.group(1), m.group(2), None)),
    # telephone 06 12 34 56 78 -> zero six, douze, ...
    (r"\b0(\d)(?:[ .]?(\d{2})){4}\b",
     lambda m: "zéro " + ", ".join([n(m.group(0)[1])] + [n(p) for p in re.findall(r"\d{2}", re.sub(r"\D", "", m.group(0))[2:])])),
    # 1 200 / 12 500 000  -> 1200 / 12500000 (espaces des milliers)
    (rf"\b\d{{1,3}}(?:{ESP}\d{{3}})+\b(?![,.]\d)", lambda m: re.sub(ESP, "", m.group(0))),
    # 15h30, 15 h 30, 15:30, 8h
    (r"\b([01]?\d|2[0-3])\s?(?:h|:)\s?([0-5]\d)\b",
     lambda m: f"{n_fem(m.group(1))} {'heure' if int(m.group(1)) <= 1 else 'heures'} {n(m.group(2)) if m.group(2) != '00' else ''}".strip()),
    (r"\b([01]?\d|2[0-3])\s?h\b",
     lambda m: f"{n_fem(m.group(1))} {'heure' if int(m.group(1)) <= 1 else 'heures'}"),
    # 12,50 €  12 €  12€50
    (r"(\d+)(?:[,.](\d{1,2}))?\s?€(\d{2})?",
     lambda m: f"{n(m.group(1))} {pluriel(m.group(1), 'euro')}"
               + (f" {n(m.group(2) or m.group(3))}" if (m.group(2) or m.group(3)) and int(m.group(2) or m.group(3)) else "")),
    # 25 %  3,5 %
    (r"(-?\d+(?:[,.]\d+)?)\s?%", lambda m: f"{nombre(m.group(1))} pour cent"),
    # 20 °C  -3°
    (r"(-?\d+(?:[,.]\d+)?)\s?°(?:\s?C\b)?", lambda m: f"{nombre(m.group(1))} {pluriel(m.group(1), 'degré')}"),
    # unites courantes apres un nombre
    (r"(\d+(?:[,.]\d+)?)\s?(km|kg|cm|mm|ml|cl|kW|W|g)\b",
     lambda m: f"{nombre(m.group(1))} " + pluriel(m.group(1), {"km": "kilomètre", "kg": "kilo", "cm": "centimètre",
                "mm": "millimètre", "ml": "millilitre", "cl": "centilitre", "kW": "kilowatt",
                "W": "watt", "g": "gramme"}[m.group(2)])),
    # ordinaux : 1er 1re 1ère 2e 2ème 3eme 2nd 2nde
    (r"\b1(?:er)\b", lambda m: "premier"),
    (r"\b1(?:re|ère)\b", lambda m: "première"),
    (r"\b2(?:nd)\b", lambda m: "second"),
    (r"\b2(?:nde)\b", lambda m: "seconde"),
    (r"\b(\d+)(?:e|ème|eme)\b", lambda m: num2words(int(m.group(1)), to="ordinal", lang="fr")),
    # decimaux et negatifs isoles, puis entiers
    (r"(?<![\w.,])-(\d+(?:[,.]\d+)?)\b", lambda m: "moins " + nombre(m.group(1))),
    (r"\b(\d+)[,.](\d+)\b", lambda m: decimal(m.group(1), m.group(2))),
    (r"\d+", lambda m: n(m.group(0))),
]
REGLES = [(re.compile(p), f) for p, f in REGLES]


# emojis, pictogrammes et selecteurs de variante : la voix les lirait mal ou ferait une pause
EMOJIS = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0E\uFE0F\u200D\u20E3]+")


def normaliser(texte: str) -> str:
    texte = EMOJIS.sub(" ", texte)
    for motif, remplacement in REGLES:
        texte = motif.sub(remplacement, texte)
    return re.sub(r"\s{2,}", " ", texte).strip()


if __name__ == "__main__":
    import sys
    print(normaliser(" ".join(sys.argv[1:])))
