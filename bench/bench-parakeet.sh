#!/usr/bin/env bash
# bench-parakeet.sh : mesure Parakeet TDT 0.6B v3 (francais inclus) SUR CPU du R750xa,
# via onnx-asr (MIT, onnxruntime). Meme phrase que bench-voix.sh pour comparer a Whisper.
#
# A lancer sur le R750xa, shell de l'hote, utilisateur "et", APRES bench-voix.sh :
#   bash ~/bench-parakeet.sh                 -> phrase Piper de bench-voix.sh
#   bash ~/bench-parakeet.sh mon_audio.wav   -> ta propre voix

set -euo pipefail

DIR="$HOME/voix-bench"
VENV="$DIR/venv"
AUDIO="${1:-$DIR/phrase_piper.wav}"
export HF_HOME="${HF_HOME:-/data/cache-huggingface}"
export CUDA_VISIBLE_DEVICES=""          # interdit tout usage GPU

[ -x "$VENV/bin/python" ] || { echo "Lance d'abord bench-voix.sh (il cree $VENV)" >&2; exit 1; }
[ -f "$AUDIO" ] || { echo "Audio introuvable : $AUDIO" >&2; exit 1; }

echo "=== Installation onnx-asr ==="
uv pip install --python "$VENV/bin/python" -q "onnx-asr[cpu,hub]"

echo "=== Mesures (CPU uniquement) ==="
"$VENV/bin/python" -I - "$AUDIO" <<'PY' | tee "$DIR/resultats-parakeet-$(date +%Y%m%d-%H%M).txt"
import sys, time, subprocess, difflib
import numpy as np, onnxruntime as ort, onnx_asr

audio_path = sys.argv[1]
REF = ("Bonjour, peux-tu me dire quelle température il fera demain à La Rochelle, "
       "et me rappeler d'appeler le fondeur à quinze heures ?")
ref = REF if audio_path.endswith("phrase_piper.wav") else None

def wer(r, h):
    norm = lambda s: "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in s).split()
    r, h = norm(r), norm(h)
    sm = difflib.SequenceMatcher(a=r, b=h)
    return sum(max(i2-i1, j2-j1) for op,i1,i2,j1,j2 in sm.get_opcodes() if op != "equal") / max(len(r),1)

pcm = subprocess.run(["ffmpeg","-loglevel","error","-i",audio_path,"-f","f32le","-ac","1","-ar","16000","-"],
                     check=True, capture_output=True).stdout
audio = np.frombuffer(pcm, dtype=np.float32)
duree = len(audio) / 16000
print(f"Audio : {audio_path} ({duree:.1f} s)\n")

# Copie reelle des fichiers dans un dossier dedie : onnxruntime refuse les
# poids externes servis par les liens symboliques du cache Hugging Face.
import os
from huggingface_hub import snapshot_download
MODELE = snapshot_download("istupakov/parakeet-tdt-0.6b-v3-onnx",
                           local_dir=os.path.expanduser("~/voix-bench/parakeet-tdt-0.6b-v3"))
print(f"{'modele':<30}{'threads':>8}{'charg.':>9}{'transcr.':>10}{'x t.reel':>10}{'WER':>7}")

for quant in [None, "int8"]:
    for threads in [8, 16]:
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        t0 = time.perf_counter()
        m = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", MODELE, quantization=quant,
                                sess_options=so, providers=["CPUExecutionProvider"])
        t_load = time.perf_counter() - t0
        res = []
        for _ in range(3):                       # 1er passage = chauffe
            t0 = time.perf_counter()
            texte = m.recognize(audio, sample_rate=16000)
            res.append(time.perf_counter() - t0)
        t = min(res[1:])
        nom = "parakeet-tdt-0.6b-v3 " + (quant or "fp32")
        w = f"{wer(ref, texte)*100:5.1f}%" if ref else "   -"
        print(f"{nom:<30}{threads:>8}{t_load:>8.1f}s{t:>9.2f}s{duree/t:>9.1f}x{w:>7}")
        if threads == 16:
            print(f"    -> \"{texte}\"")
        del m
print("\nRappel Whisper small int8 16 threads : 1.17 s, WER 4.3 %")
PY
