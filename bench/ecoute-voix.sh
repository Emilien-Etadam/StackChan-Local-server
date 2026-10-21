#!/usr/bin/env bash
# ecoute-voix.sh : fait dire la meme phrase a chaque voix Pocket TTS (modele francais)
# pour choisir la voix du robot a l'oreille.
#
# A lancer sur le R750xa, shell de l'hote, utilisateur "et", APRES bench-pocket.sh :
#   bash ~/ecoute-voix.sh            -> les 14 voix masculines
#   bash ~/ecoute-voix.sh toutes     -> les 27 voix
#
# Fichiers : ~/voix-bench/ecoute/voix/<nom>.wav

set -euo pipefail

DIR="$HOME/voix-bench"
VENV="$DIR/venv-pocket"
export HF_HOME="${HF_HOME:-/data/cache-huggingface}"
export CUDA_VISIBLE_DEVICES=""
[ -x "$VENV/bin/python" ] || { echo "Lance d'abord bench-pocket.sh (il cree $VENV)" >&2; exit 1; }
mkdir -p "$DIR/ecoute/voix"

"$VENV/bin/python" -I - "$DIR/ecoute/voix" "${1:-hommes}" <<'PY'
import os, sys, time
import numpy as np, scipy.io.wavfile
from pocket_tts import TTSModel

out, choix = sys.argv[1], sys.argv[2]
HOMMES = ["charles", "jean", "javert", "marius", "paul", "george", "michael",
          "bill_boerst", "peter_yearsley", "stuart_bell", "juergen", "giovanni",
          "rafael", "daan"]
FEMMES = ["estelle", "alba", "anna", "azelma", "caro_davy", "cosette", "eponine",
          "eve", "fantine", "jane", "lola", "mary", "vera"]
voix = HOMMES + FEMMES if choix == "toutes" else HOMMES

PHRASE = ("Bonjour. Les enfants ont acheté des œufs frais au marché, "
          "puis ils sont allés voir le fondeur à quinze heures. Tu veux que je te le rappelle ?")

m = TTSModel.load_model(language="french")
sr = m.sample_rate
print(f"{'voix':<16}{'audio':>7}{'calcul':>8}")
for nom in voix:
    try:
        etat = m.get_state_for_audio_prompt(nom)
        t0 = time.perf_counter()
        audio = m.generate_audio(etat, PHRASE).reshape(-1).numpy()
        t = time.perf_counter() - t0
        scipy.io.wavfile.write(os.path.join(out, f"{nom}.wav"), sr, audio)
        print(f"{nom:<16}{len(audio)/sr:>6.1f}s{t:>7.1f}s")
    except Exception as e:
        print(f"{nom:<16}ECHEC : {e}")
print(f"\nFichiers : {out}")
PY
