#!/usr/bin/env bash
# install-voix-fr.sh : installe ou met a jour le service vocal "voix-fr" (Parakeet + Pocket TTS + effet robot).
# A lancer sur le R750xa, shell de l'hote, utilisateur "et" (sudo demande pour /opt, /etc et systemd) :
#   bash voix-fr/install.sh   (depuis le dossier du depot clone)
# Rejouable : met a jour le code et les paquets, ne touche jamais a /etc/voix-fr/voix.yaml s'il existe.
# Ensuite : page d'essai http://192.168.30.121:8200/test

set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"   # dossier voix-fr du depot
APP=/opt/voix-fr
CONF=/etc/voix-fr
UTIL="$(id -un)"
export HF_HOME="${HF_HOME:-/data/cache-huggingface}"

command -v uv >/dev/null || { echo "uv introuvable" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg introuvable : sudo apt-get install -y ffmpeg" >&2; exit 1; }

echo "=== 1/5 Dossiers ==="
sudo mkdir -p "$APP/modeles" "$CONF"
sudo chown -R "$UTIL":"$UTIL" "$APP"
sudo chown "$UTIL":"$UTIL" "$CONF"

echo "=== 2/5 Code ==="
cp "$ICI"/app.py "$ICI"/robot_fx.py "$ICI"/normaliser_fr.py "$ICI"/test.html "$APP"/
if [ ! -f "$CONF/voix.yaml" ]; then
  cp "$ICI/voix.yaml" "$CONF/voix.yaml"
  echo "   config par defaut creee : $CONF/voix.yaml"
else
  echo "   config existante conservee : $CONF/voix.yaml"
fi

echo "=== 3/5 Environnement Python (CPU uniquement) ==="
[ -x "$APP/venv/bin/python" ] || uv venv --python 3.12 "$APP/venv"
uv pip install --python "$APP/venv/bin/python" --torch-backend cpu torch
uv pip install --python "$APP/venv/bin/python" pocket-tts "onnx-asr[cpu,hub]" \
    fastapi "uvicorn[standard]" python-multipart pyyaml numpy scipy huggingface_hub num2words

echo "=== 4/5 Modeles ==="
"$APP/venv/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("istupakov/parakeet-tdt-0.6b-v3-onnx",
                  local_dir="/opt/voix-fr/modeles/parakeet-tdt-0.6b-v3")
from pocket_tts import TTSModel
m = TTSModel.load_model(language="french"); m.get_state_for_audio_prompt("estelle")
print("modeles OK")
PY

echo "=== 5/5 Service systemd ==="
PORT=$(grep -E '^\s*port:' "$CONF/voix.yaml" | awk '{print $2}'); PORT=${PORT:-8200}
HOTE=$(grep -E '^\s*hote:' "$CONF/voix.yaml" | awk '{print $2}'); HOTE=${HOTE:-0.0.0.0}
sudo tee /etc/systemd/system/voix-fr.service >/dev/null <<UNIT
[Unit]
Description=voix-fr : transcription Parakeet + voix Pocket TTS (CPU)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$UTIL
WorkingDirectory=$APP
Environment=HF_HOME=$HF_HOME
Environment=CUDA_VISIBLE_DEVICES=
Environment=VOIX_FR_CONFIG=$CONF/voix.yaml
ExecStart=$APP/venv/bin/uvicorn app:app --host $HOTE --port $PORT --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable voix-fr
sudo systemctl restart voix-fr

echo -n "Demarrage"
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
    echo " : OK"
    echo "Page d'essai : http://$(hostname -I | awk '{print $1}'):$PORT/test"
    exit 0
  fi
  echo -n "."; sleep 2
done
echo " : pas de reponse apres 2 min. Journal :"
sudo journalctl -u voix-fr -n 40 --no-pager
exit 1
