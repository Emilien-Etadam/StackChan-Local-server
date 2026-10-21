"""[voix-fr] Filtre du nom du robot : xiaozhi ne repond que si la phrase contient le nom
du robot, ou si elle arrive peu apres une reponse (suite de conversation).

Reglages dans data/.config.yaml :
filtre_nom:
  actif: true
  noms: ["stack chan", "stackchan"]   # variantes acceptees (comparaison approximative)
  suite_s: 20                         # secondes sans nom apres la fin d'une reponse
  tolerance: 0.83                     # 1.0 = son exact
  locuteurs: ["Emilien"]              # facultatif : seules ces voix sont ecoutees
                                      # (noms du bloc voiceprint.speakers de xiaozhi)
"""
import re
import time
import unicodedata
from difflib import SequenceMatcher


def _plat(texte):
    """minuscules, sans accents, lettres et chiffres seulement"""
    t = unicodedata.normalize("NFD", texte.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def _phon(s):
    """Cle phonetique grossiere : la transcription de « Stack-chan » varie
    (Stack Shine, Tak Shane, Tak schön, Stac tchan...), on compare le son."""
    s = re.sub(r"[^a-z]", "", s)
    s = re.sub(r"^s(?=t)", "", s)              # stack -> tack
    s = re.sub(r"t(?=ch|sh)", "", s)           # tchan -> chan
    s = re.sub(r"sch|sh|ch", "x", s)           # chan / shan / schon -> xan
    s = re.sub(r"ck|q|c|k|g", "k", s)          # tack / tac / tak -> tak
    s = re.sub(r"[aeiouy]+", "a", s)           # voyelles confondues
    s = re.sub(r"h", "", s)
    s = re.sub(r"a$", "", s) if len(s) > 4 else s   # shine / shane : e final
    return re.sub(r"(.)\1+", r"\1", s)


def contient_nom(texte, noms, tolerance=0.83):
    mots = _plat(texte).split()
    cibles = [_phon(_plat(n)) for n in noms]
    for i in range(len(mots)):
        for n in (1, 2, 3):
            if i + n > len(mots):
                break
            bloc = _phon("".join(mots[i:i + n]))
            for c in cibles:
                # meme debut (« ta... ») et au plus un son different
                if c and bloc[:2] == c[:2] and SequenceMatcher(None, bloc, c).ratio() >= tolerance:
                    return True
    return False


def accepte(conn, texte, locuteur=None):
    cfg = conn.config.get("filtre_nom") or {}
    if not cfg.get("actif", False):
        return True
    # voix autorisees (reconnaissance du locuteur par voix-fr) : avant tout le reste
    voix = [v.lower() for v in (cfg.get("locuteurs") or [])]
    if voix and (locuteur or "").lower() not in voix:
        return False
    maintenant = time.time()
    noms = cfg.get("noms") or ["stack chan"]
    if contient_nom(texte, noms, float(cfg.get("tolerance", 0.83))):
        conn.voixfr_dernier_echange = maintenant
        return True
    # pendant que le robot parle, seule une phrase avec son nom peut l'interrompre
    if getattr(conn, "client_is_speaking", False):
        return False
    # suite de conversation : peu apres la fin de la derniere reponse du robot
    repere = max(getattr(conn, "voixfr_dernier_echange", 0.0),
                 getattr(conn, "voixfr_fin_parole", 0.0))
    if repere and maintenant - repere < float(cfg.get("suite_s", 20)):
        conn.voixfr_dernier_echange = maintenant
        return True
    return False
