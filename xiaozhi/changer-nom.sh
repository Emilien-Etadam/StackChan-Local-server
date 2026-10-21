#!/usr/bin/env bash
# changer-nom.sh : change le nom auquel le robot repond (filtre du nom, mots de reveil,
# prompt) dans la config existante, puis redemarre xiaozhi.
#
# A lancer DANS LA CONSOLE DU LXC xiaozhi, en root :
#   bash xiaozhi/changer-nom.sh Hector
#   bash xiaozhi/changer-nom.sh Hector victor "hey to"   (variantes entendues par la transcription)
# Une copie de la config est gardee a cote (.config.yaml.avant-<nom>).

set -euo pipefail
NOM="${1:-}"
[ -n "$NOM" ] || { echo "Usage : bash xiaozhi/changer-nom.sh <Nom>" >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo "A lancer en root dans le LXC" >&2; exit 1; }
CFG=/opt/xiaozhi/main/xiaozhi-server/data/.config.yaml
[ -f "$CFG" ] || { echo "Config introuvable : $CFG (lancer d'abord install.sh)" >&2; exit 1; }

cp -p "$CFG" "$CFG.avant-$NOM"
VARIANTES="${*:2}" NOM="$NOM" /opt/xiaozhi/venv/bin/python - "$CFG" "${@:2}" <<'FIN'
import json, os, re, sys
p = sys.argv[1]
nom = os.environ["NOM"].strip()
bas = nom.lower()
noms = [bas] + [v.strip().lower() for v in sys.argv[2:] if v.strip()]
t = open(p, encoding="utf-8").read()

# 1. filtre du nom : liste des noms acceptes
t, n1 = re.subn(r"(?m)^(  noms:).*$", lambda m: m.group(1) + " " + json.dumps(noms, ensure_ascii=False), t)
# 2. mots de reveil (bloc wakeup_words)
t, n2 = re.subn(r"(?m)^wakeup_words:\n(?:  - [^\n]*\n)+",
                lambda m: "wakeup_words:\n" + "".join(f"  - {json.dumps(w, ensure_ascii=False)}\n"
                                                    for w in (bas, "salut " + bas)), t)
# 3. prompt : « Tu t'appelles X. »
t, n3 = re.subn(r"Tu t['’]appelles [^.\n]+\.", lambda m: f"Tu t'appelles {nom}.", t)

open(p, "w", encoding="utf-8").write(t)
print(f"  noms : {'OK' if n1 else 'bloc filtre_nom absent'}")
print(f"  mots de reveil : {'OK' if n2 else 'bloc wakeup_words absent'}")
print(f"  prompt : {'OK' if n3 else 'phrase « Tu t appelles » absente, a corriger a la main'}")
FIN
chown xiaozhi:xiaozhi "$CFG"
chmod 600 "$CFG"
systemctl restart xiaozhi
echo "Nom change en « $NOM », xiaozhi redemarre. Copie de l'ancienne config : $CFG.avant-$NOM"
