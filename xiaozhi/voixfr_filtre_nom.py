"""[voix-fr] Filtre du nom du robot : xiaozhi ne repond que si la phrase contient le nom
du robot, ou si elle arrive peu apres une reponse (suite de conversation).

Reglages dans data/.config.yaml :
filtre_nom:
  actif: true
  noms: ["stack chan", "stackchan"]   # variantes acceptees (comparaison approximative)
  suite_s: 20                         # secondes sans nom apres la fin d'une reponse
  tolerance: 0.75                     # 1.0 = orthographe exacte
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


def contient_nom(texte, noms, tolerance=0.75):
    mots = _plat(texte).split()
    cibles = [_plat(n).replace(" ", "") for n in noms]
    for i in range(len(mots)):
        for n in (1, 2, 3):
            if i + n > len(mots):
                break
            bloc = "".join(mots[i:i + n])
            for c in cibles:
                if c and SequenceMatcher(None, bloc, c).ratio() >= tolerance:
                    return True
    return False


def accepte(conn, texte):
    cfg = conn.config.get("filtre_nom") or {}
    if not cfg.get("actif", False):
        return True
    maintenant = time.time()
    noms = cfg.get("noms") or ["stack chan"]
    if contient_nom(texte, noms, float(cfg.get("tolerance", 0.75))):
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
