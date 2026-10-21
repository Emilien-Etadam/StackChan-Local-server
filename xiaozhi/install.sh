#!/usr/bin/env bash
# install-xiaozhi.sh : installe ou met a jour xiaozhi-esp32-server pour le robot StackChan,
# branche sur voix-fr (Parakeet + Pocket TTS) et llama-swap (alias "chat") du R750xa.
#
# A lancer DANS LA CONSOLE DU LXC xiaozhi (Debian 13), en root. PAS sur l'hyperviseur Proxmox.
#   bash xiaozhi/install.sh   (depuis le dossier du depot clone)
# Rejouable : ne touche jamais a la config existante (/opt/xiaozhi/main/xiaozhi-server/data/.config.yaml).

set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"   # dossier xiaozhi du depot
VERSION=f614489d814aa70f6703b647fecd347c1af8b62f      # commit du 20/10/2026, verifie avec les correctifs
DEPOT=https://github.com/xinnan-tech/xiaozhi-esp32-server.git
BASE=/opt/xiaozhi
SRV=$BASE/main/xiaozhi-server
R750=192.168.30.121
# Python 3.10 installe sous /opt (et non dans /root) pour que le compte de service "xiaozhi" puisse l'executer
export UV_PYTHON_INSTALL_DIR=$BASE/python

[ "$(id -u)" = 0 ] || { echo "A lancer en root dans le LXC" >&2; exit 1; }
[ -d /etc/pve ] && { echo "Tu es sur l'hyperviseur Proxmox : lance ce script dans la console du LXC" >&2; exit 1; }

echo "=== 1/7 Paquets systeme et fuseau horaire ==="
apt-get update -qq
apt-get install -y -qq git curl ca-certificates ffmpeg libopus0 tzdata >/dev/null
ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime && echo Europe/Paris > /etc/timezone
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
id xiaozhi >/dev/null 2>&1 || useradd --system --home "$BASE" --shell /usr/sbin/nologin xiaozhi

echo "=== 2/7 Verification des services du R750xa ==="
curl -sf -m 5 "http://$R750:8200/health" >/dev/null && echo "  voix-fr : OK" || { echo "  voix-fr injoignable sur $R750:8200" >&2; exit 1; }
curl -s -m 5 -o /dev/null -w "  llama-swap : HTTP %{http_code} (401 = joignable, cle verifiee a l etape 6)\n" "http://$R750:8090/v1/models"

echo "=== 3/7 Code xiaozhi (version figee) ==="
if [ ! -d "$BASE/.git" ]; then
  git init -q "$BASE" && git -c safe.directory="$BASE" -C "$BASE" remote add origin "$DEPOT"
fi
if [ "$(git -c safe.directory="$BASE" -C "$BASE" rev-parse HEAD 2>/dev/null)" != "$VERSION" ]; then
  echo "  telechargement (environ 200 Mo, une seule fois)..."
  git -c safe.directory="$BASE" -C "$BASE" fetch --depth 1 origin "$VERSION"
else
  echo "  deja a la bonne version"
fi
git -c safe.directory="$BASE" -C "$BASE" checkout -q -f "$VERSION"

echo "=== 4/7 Correctifs francais ==="
cp "$ICI/correctifs.py" "$BASE/correctifs.py"
cp "$ICI/agent-base-prompt-fr.txt" "$SRV/agent-base-prompt-fr.txt"
cp "$ICI"/voixfr_filtre_nom.py "$ICI"/voixfr_outils_robot.py "$ICI"/voixfr_regard.py "$SRV/core/utils/"
cp "$ICI"/voixfr_recherche_web.py "$ICI"/voixfr_memoire.py "$ICI"/voixfr_zimbra.py "$SRV/plugins_func/functions/"
cp "$ICI/completer-config.py" "$BASE/completer-config.py"

echo "=== 5/7 Environnement Python 3.10 (PyTorch CPU) ==="
# venv cree par une version precedente du script avec un Python sous /root : a refaire
if [ -L "$BASE/venv/bin/python" ] && readlink -f "$BASE/venv/bin/python" | grep -q "^/root/"; then rm -rf "$BASE/venv"; fi
[ -x "$BASE/venv/bin/python" ] || uv venv -q --python 3.10 "$BASE/venv"
uv pip install --python "$BASE/venv/bin/python" --torch-backend cpu -r "$SRV/requirements.txt"
uv pip install --python "$BASE/venv/bin/python" "opencv-python-headless<4.12" "caldav>=1.4,<2"   # [voix-fr] visage (regard) ; 4.12+ exige numpy 2
# detecteur de visage YuNet (OpenCV Zoo, 230 Ko) ; a defaut, le detecteur Haar livre avec OpenCV
YUNET="$SRV/models/face_detection_yunet_2023mar.onnx"
[ "$(stat -c %s "$YUNET" 2>/dev/null || echo 0)" -gt 100000 ] || curl -fsSL -o "$YUNET" https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
  || true
# un pointeur Git LFS (quelques octets) n'est pas le modele : on le retire
if [ "$(stat -c %s "$YUNET" 2>/dev/null || echo 0)" -lt 100000 ]; then rm -f "$YUNET"; echo "  (YuNet non telecharge : detecteur Haar d'OpenCV utilise)"; fi
"$BASE/venv/bin/python" "$BASE/correctifs.py" "$SRV"

echo "=== 6/7 Configuration ==="
mkdir -p "$SRV/data" "$SRV/tmp"
if [ ! -f "$SRV/data/.config.yaml" ]; then
  IP=$(hostname -I | awk '{print $1}')
  CLE=""
  while [ -z "$CLE" ]; do read -r -s -p "  Cle API llama-swap (non vide) : " CLE; echo; done
  cp "$ICI/config-modele.yaml" "$SRV/data/.config.yaml"
  # remplacement sans sed : la cle peut contenir des caracteres speciaux
  CLE="$CLE" IP="$IP" "$BASE/venv/bin/python" - "$SRV/data/.config.yaml" <<'FIN_REMPL'
import json, os, sys
p = sys.argv[1]; t = open(p, encoding="utf-8").read()
t = t.replace("__IP__", os.environ["IP"]).replace("__CLE_LLAMA_SWAP__", json.dumps(os.environ["CLE"]))
open(p, "w", encoding="utf-8").write(t)
FIN_REMPL
  chmod 600 "$SRV/data/.config.yaml"
  echo "  config creee : $SRV/data/.config.yaml"
  code=$(curl -s -m 5 -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CLE" "http://$R750:8090/v1/models")
  [ "$code" = 200 ] && echo "  cle llama-swap : OK" || echo "  ATTENTION : llama-swap repond $code avec cette cle"
else
  echo "  config existante conservee : $SRV/data/.config.yaml"
fi
# nouvelles fonctions : leurs reglages sont ajoutes s'ils manquent (rien d'existant n'est modifie)
cp -p "$SRV/data/.config.yaml" "$SRV/data/.config.yaml.avant-maj"
"$BASE/venv/bin/python" "$BASE/completer-config.py" "$SRV/data/.config.yaml"
chown -R xiaozhi:xiaozhi "$BASE"

echo "=== 7/7 Service systemd ==="
cat > /etc/systemd/system/xiaozhi.service <<UNIT
[Unit]
Description=xiaozhi-esp32-server (robot StackChan)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=xiaozhi
WorkingDirectory=$SRV
ExecStart=$BASE/venv/bin/python app.py
StandardInput=null
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q xiaozhi
systemctl restart xiaozhi

echo -n "Demarrage"
for i in $(seq 1 60); do
  if ss -ltn | grep -q ':8000 '; then
    IP=$(hostname -I | awk '{print $1}')
    echo " : OK"
    echo
    echo "Dans la page de reglages du robot, onglet Conversation :"
    echo "  Fournisseur : XiaoZhi"
    echo "  URL du serveur XiaoZhi : ws://$IP:8000/xiaozhi/v1/"
    echo "Journal en direct : journalctl -u xiaozhi -f"
    exit 0
  fi
  echo -n "."; sleep 2
done
echo " : le port 8000 n'ecoute pas apres 2 min. Journal :"
journalctl -u xiaozhi -n 50 --no-pager
exit 1
