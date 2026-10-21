"""completer-config.py : ajoute a une config xiaozhi existante les reglages des nouvelles
fonctions, sans toucher a ce qui est deja regle. Appele par install.sh a chaque passage.

  - bloc regard (le robot tourne la tete vers toi)
  - plugins.memoire (notes du robot sur voix-fr) et plugins.zimbra (a remplir)
  - fonctions serveur : memoire, agenda et mails (et recherche_web si configuree)
Usage : python completer-config.py /opt/xiaozhi/main/xiaozhi-server/data/.config.yaml
"""
import re
import sys

import yaml

p = sys.argv[1]
t = open(p, encoding="utf-8").read()
cfg = yaml.safe_load(t) or {}
ajouts = []

if "regard" not in cfg:
    t = t.rstrip("\n") + """

# [voix-fr] le robot tourne la tete vers la personne qui lui parle (photo a chaque phrase)
regard:
  actif: true
  port: 80
  champ_h: 62
  champ_v: 48
  sens_yaw: 1       # -1 si la tete tourne du mauvais cote
  sens_pitch: 1     # -1 si elle monte au lieu de descendre
"""
    ajouts.append("regard")

plugins = cfg.get("plugins") or {}
blocs = []
if "memoire" not in plugins:
    blocs.append("""  memoire:
    url: http://192.168.30.121:8200       # voix-fr (page /memoire)
""")
    ajouts.append("plugins.memoire")
if "zimbra" not in plugins:
    blocs.append("""  zimbra:                                # a remplir : agenda et mails (aucun envoi)
    serveur: ""                          # ex. mail.etadam.com
    compte: ""                           # ex. emilien@etadam.com
    mot_de_passe: ""
    calendrier: ""                       # vide = premier agenda du compte
    brouillons: Drafts
    fuseau: Europe/Paris
""")
    ajouts.append("plugins.zimbra")
if blocs:
    if re.search(r"(?m)^plugins:\s*$", t):
        t = re.sub(r"(?m)^plugins:\s*\n", lambda m: m.group(0) + "".join(blocs), t, count=1)
    else:
        t = t.rstrip("\n") + "\n\n# [voix-fr] fonctions du serveur\nplugins:\n" + "".join(blocs)

voulues = ["retenir", "se_souvenir", "oublier", "agenda_lire", "agenda_ajouter", "mails_lire", "mail_brouillon"]
if "recherche_web" in plugins:
    voulues.append("recherche_web")
m = re.search(r"(?m)^    functions:(.*)$", t)
if m:
    tete = m.group(1).split("#")[0].strip()
    if tete.startswith("["):
        actuelles = [f.strip().strip("'\"") for f in tete.strip("[]").split(",") if f.strip()]
        manquantes = [f for f in voulues if f not in actuelles]
        if manquantes:
            reste = m.group(1)[m.group(1).find("#"):] if "#" in m.group(1) else ""
            t = t[:m.start()] + "    functions: [" + ", ".join(actuelles + manquantes) + "]" + (
                "   " + reste if reste else "") + t[m.end():]
            ajouts.append("fonctions " + ", ".join(manquantes))
    else:
        print("  (liste « functions » ecrite sur plusieurs lignes : fonctions a ajouter a la main :", ", ".join(voulues), ")")

yaml.safe_load(t)          # la config doit rester lisible, sinon on n'ecrit rien
open(p, "w", encoding="utf-8").write(t)
print("  ajouts a la config :", ", ".join(ajouts) if ajouts else "aucun (deja a jour)")
