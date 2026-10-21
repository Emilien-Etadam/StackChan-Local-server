#!/usr/bin/env bash
# activer-recherche.sh : donne au robot la recherche internet par le SearXNG local,
# puis redemarre xiaozhi.
#
# A lancer DANS LA CONSOLE DU LXC xiaozhi, en root :
#   bash xiaozhi/activer-recherche.sh                 (SearXNG en 192.168.30.122, port detecte)
#   bash xiaozhi/activer-recherche.sh http://hote:port
#   bash xiaozhi/activer-recherche.sh --off

set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "A lancer en root dans le LXC" >&2; exit 1; }
CFG=/opt/xiaozhi/main/xiaozhi-server/data/.config.yaml
[ -f "$CFG" ] || { echo "Config introuvable : $CFG" >&2; exit 1; }
URL="${1:-}"

if [ "$URL" != "--off" ]; then
  if [ -z "$URL" ]; then
    for p in 8080 8888 80; do
      if curl -sf -m 4 "http://192.168.30.122:$p/search?q=test&format=json" >/dev/null; then URL="http://192.168.30.122:$p"; break; fi
    done
    [ -n "$URL" ] || { echo "SearXNG introuvable en 192.168.30.122 (ports 8080, 8888, 80) avec le format json. Donner l'adresse : bash xiaozhi/activer-recherche.sh http://hote:port" >&2; exit 1; }
  fi
  code=$(curl -s -m 6 -o /dev/null -w "%{http_code}" "$URL/search?q=test&format=json")
  [ "$code" = 200 ] || { echo "SearXNG repond $code pour format=json : activer « json » dans search.formats de son settings.yml" >&2; exit 1; }
  echo "  SearXNG : $URL"
fi

cp -p "$CFG" "$CFG.avant-recherche"
URL="$URL" /opt/xiaozhi/venv/bin/python - "$CFG" <<'FIN'
import os, re, sys
p = sys.argv[1]
url = os.environ["URL"]
t = open(p, encoding="utf-8").read()
# 1. bloc plugins.recherche_web (reecrit a chaque fois)
t = re.sub(r"(?m)\n*^# \[voix-fr\] recherche internet[^\n]*\n", "\n", t)
t = re.sub(r"(?m)^plugins:\n  recherche_web:\n(?:    [^\n]*\n)*", "", t)
# 2. liste des fonctions du mode outils
m = re.search(r"(?m)^    functions:(.*)$", t)
if not m:
    sys.exit("ligne « functions: » du bloc Intent.function_call introuvable")
debut = m.group(1).split("#")[0].strip()
fonctions = [f.strip().strip("'\"") for f in debut.strip("[]").split(",") if f.strip()] if debut.startswith("[") else []
if debut and not debut.startswith("["):
    sys.exit("format de « functions: » inattendu, a modifier a la main")
fonctions = [f for f in fonctions if f != "recherche_web"]
if url != "--off":
    fonctions.append("recherche_web")
    if re.search(r"(?m)^plugins:", t):
        sys.exit("un bloc « plugins: » existe deja : ajouter recherche_web a la main")
    t = t.rstrip("\n") + f"""

# [voix-fr] recherche internet (SearXNG local)
plugins:
  recherche_web:
    url: {url}
    resultats: 5
    langue: fr
"""
commentaire = "   # les outils du robot arrivent tout seuls par MCP ; handle_exit_intent est ajoute d'office"
t = t[:m.start()] + "    functions: [" + ", ".join(fonctions) + "]" + commentaire + t[m.end():]
open(p, "w", encoding="utf-8").write(t)
print("  fonctions serveur :", fonctions or "aucune")
FIN
chown xiaozhi:xiaozhi "$CFG"
chmod 600 "$CFG"
systemctl restart xiaozhi
echo "xiaozhi redemarre. Ancienne config : $CFG.avant-recherche"
