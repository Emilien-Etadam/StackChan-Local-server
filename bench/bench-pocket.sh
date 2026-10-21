#!/usr/bin/env bash
# bench-pocket.sh : duel de VITESSE Piper contre Kyutai Pocket TTS en francais, SUR CPU du R750xa.
# Produit aussi les fichiers .wav des deux moteurs pour l'ecoute.
#
# A lancer sur le R750xa, shell de l'hote, utilisateur "et" (pas de sudo) :
#   bash ~/bench-pocket.sh
#
# Installe tout dans ~/voix-bench/venv-pocket (PyTorch CPU uniquement, pas de CUDA).
# Voix Pocket "estelle" : poids publics, pas besoin de compte Hugging Face.
# Resultats : ~/voix-bench/resultats-pocket-<date>.txt
# Audio a ecouter : ~/voix-bench/ecoute/

set -euo pipefail

DIR="$HOME/voix-bench"
VENV="$DIR/venv-pocket"
export HF_HOME="${HF_HOME:-/data/cache-huggingface}"
export CUDA_VISIBLE_DEVICES=""          # interdit tout usage GPU
mkdir -p "$DIR/ecoute"

command -v uv >/dev/null 2>&1 || { echo "uv introuvable" >&2; exit 1; }

echo "=== Installation (PyTorch CPU, pocket-tts, piper-tts) ==="
[ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV"
echo "-> PyTorch CPU (environ 200 Mo, peut prendre quelques minutes)"
uv pip install --python "$VENV/bin/python" torch --index-url https://download.pytorch.org/whl/cpu
echo "-> pocket-tts, piper-tts"
uv pip install --python "$VENV/bin/python" "pocket-tts[quantize]" piper-tts huggingface_hub scipy

echo "=== Mesures (CPU uniquement) ==="
"$VENV/bin/python" -I - "$DIR" <<'PY' | tee "$DIR/resultats-pocket-$(date +%Y%m%d-%H%M).txt"
import os, sys, time, wave, platform
import numpy as np, scipy.io.wavfile

out = os.path.join(sys.argv[1], "ecoute")
PHRASES = {
    "courte":  "D'accord, je m'en occupe.",
    "moyenne": "Il fera quinze degrés demain à La Rochelle, avec un ciel nuageux le matin.",
    "longue":  ("Les enfants ont acheté des œufs frais au marché, puis ils sont allés "
                "voir les fils électriques que le fondeur avait installés à quinze heures."),
}
print(f"Machine : {platform.node()} | {time.strftime('%Y-%m-%d %H:%M')}")
print("Colonnes : 1er son = attente avant le premier morceau audio (mode flux),")
print("           total = attente pour la phrase entiere (ce que xiaozhi attend aujourd'hui),")
print("           x t.reel = duree audio / temps de calcul (doit rester > 1.5)\n")
print(f"{'moteur':<28}{'phrase':<9}{'audio':>7}{'1er son':>9}{'total':>8}{'x t.reel':>10}")

# ---------------- Piper (reference) ----------------
from huggingface_hub import hf_hub_download
from piper import PiperVoice
voix = "fr/fr_FR/siwis/medium/fr_FR-siwis-medium"
onnx = hf_hub_download("rhasspy/piper-voices", voix + ".onnx")
hf_hub_download("rhasspy/piper-voices", voix + ".onnx.json")
pv = PiperVoice.load(onnx)
for nom, txt in PHRASES.items():
    f = os.path.join(out, f"piper_{nom}.wav")
    temps = []
    for _ in range(3):
        t0 = time.perf_counter()
        with wave.open(f, "wb") as wf:
            pv.synthesize_wav(txt, wf)
        temps.append(time.perf_counter() - t0)
    with wave.open(f) as wf:
        d = wf.getnframes() / wf.getframerate()
    t = min(temps)
    print(f"{'piper siwis-medium':<28}{nom:<9}{d:>6.1f}s{'-':>9}{t:>7.2f}s{d/t:>9.1f}x")

# ---------------- Pocket TTS ----------------
from pocket_tts import TTSModel
for langue in ["french", "french_24l"]:
    for quant in [False, True]:
        etiquette = f"pocket {langue}{' int8' if quant else ''}"
        try:
            t0 = time.perf_counter()
            m = TTSModel.load_model(language=langue, quantize=quant)
            etat = m.get_state_for_audio_prompt("estelle")
            t_load = time.perf_counter() - t0
        except Exception as e:
            print(f"{etiquette:<28}ECHEC chargement : {e}")
            continue
        sr = m.sample_rate
        m.generate_audio(etat, "Bonjour.")            # chauffe
        for nom, txt in PHRASES.items():
            meilleurs = None
            for _ in range(2):
                morceaux, t0, premier = [], time.perf_counter(), None
                for c in m.generate_audio_stream(etat, txt):
                    if premier is None:
                        premier = time.perf_counter() - t0
                    morceaux.append(c)
                total = time.perf_counter() - t0
                if meilleurs is None or total < meilleurs[1]:
                    meilleurs = (premier, total, morceaux)
            premier, total, morceaux = meilleurs
            audio = np.concatenate([c.reshape(-1).numpy() for c in morceaux])
            d = len(audio) / sr
            scipy.io.wavfile.write(os.path.join(out, f"{etiquette.replace(' ', '_')}_{nom}.wav"), sr, audio)
            print(f"{etiquette:<28}{nom:<9}{d:>6.1f}s{premier:>8.2f}s{total:>7.2f}s{d/total:>9.1f}x")
        print(f"    (chargement modele + voix : {t_load:.1f} s)")
        del m

print(f"\nFichiers a ecouter : {out}")
PY

echo "=== Termine ==="
