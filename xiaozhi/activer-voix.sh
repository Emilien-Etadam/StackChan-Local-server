#!/usr/bin/env bash
# activer-voix.sh : le robot n'ecoute plus que la voix inscrite (reconnaissance du
# locuteur faite par voix-fr sur le R750xa), puis redemarre xiaozhi.
#
# A lancer DANS LA CONSOLE DU LXC xiaozhi, en root :
#   bash xiaozhi/activer-voix.sh Emilien
# Ensuite : page http://192.168.30.121:8200/test, section « Ma voix », pour inscrire ta voix.
# Tant qu'aucune voix n'est inscrite, tout le monde passe (sinon le robot serait sourd).
# Pour revenir en arriere : bash xiaozhi/activer-voix.sh --off

set -euo pipefail
NOM="${1:-}"
[ -n "$NOM" ] || { echo "Usage : bash xiaozhi/activer-voix.sh <Prenom> | --off" >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo "A lancer en root dans le LXC" >&2; exit 1; }
CFG=/opt/xiaozhi/main/xiaozhi-server/data/.config.yaml
VOIXFR=http://192.168.30.121:8200
[ -f "$CFG" ] || { echo "Config introuvable : $CFG" >&2; exit 1; }
if [ "$NOM" != "--off" ]; then
  curl -sf -m 5 "$VOIXFR/voiceprint/health" >/dev/null \
    || { echo "voix-fr ne propose pas encore la reconnaissance de voix : sur le R750xa, git pull puis bash voix-fr/install.sh" >&2; exit 1; }
fi

cp -p "$CFG" "$CFG.avant-voix"
NOM="$NOM" VOIXFR="$VOIXFR" /opt/xiaozhi/venv/bin/python - "$CFG" <<'FIN'
import json, os, re, sys
p = sys.argv[1]
nom = os.environ["NOM"].strip()
t = open(p, encoding="utf-8").read()
# retire un bloc voiceprint existant et la ligne locuteurs (on les reecrit)
t = re.sub(r"(?m)\n*^# \[voix-fr\] reconnaissance du locuteur[^\n]*\n", "\n", t)
t = re.sub(r"(?m)^voiceprint:\n(?:[ ]+[^\n]*\n)*", "", t)
t = re.sub(r"(?m)^  locuteurs:[^\n]*\n(?:  [ ]+#[^\n]*\n)*", "", t)
if nom != "--off":
    ident = re.sub(r"[^a-z0-9_-]", "", nom.lower()) or "moi"
    t = t.rstrip("\n") + f"""

# [voix-fr] reconnaissance du locuteur (voix-fr, page /test section « Ma voix »)
voiceprint:
  url: {os.environ["VOIXFR"]}/voiceprint/health?key=voix-fr
  speakers:
    - {json.dumps(f"{ident},{nom},proprietaire du robot", ensure_ascii=False)}
  similarity_threshold: 0.5
"""
    if not re.search(r"(?m)^filtre_nom:", t):
        sys.exit("bloc filtre_nom absent : lancer d'abord install.sh et ajouter le filtre du nom")
    t = re.sub(r"(?m)^(filtre_nom:\n)", lambda m: m.group(1) + f"  locuteurs: {json.dumps([nom], ensure_ascii=False)}\n", t)
    print(f"  voix ecoutee : {nom} (identifiant « {ident} » sur la page /test)")
else:
    print("  reconnaissance de la voix desactivee")
open(p, "w", encoding="utf-8").write(t)
FIN
chown xiaozhi:xiaozhi "$CFG"
chmod 600 "$CFG"
systemctl restart xiaozhi
echo "xiaozhi redemarre. Ancienne config : $CFG.avant-voix"
