#!/usr/bin/env bash
# bench-voix.sh : mesure la vitesse de la voix française SUR CPU du R750xa
# (transcription faster-whisper + synthèse Piper), sans toucher aux GPU.
#
# A lancer sur le R750xa, shell de l'hote, utilisateur "et" (pas besoin de sudo) :
#   bash ~/bench-voix.sh                 -> phrase de test synthetisee par Piper
#   bash ~/bench-voix.sh mon_audio.wav   -> ta propre voix (wav, n'importe quel format)
#
# Tout est installe dans ~/voix-bench (rejouable, supprimable d'un rm -rf).
# Resultats ecrits dans ~/voix-bench/resultats-<date>.txt

set -euo pipefail

DIR="$HOME/voix-bench"
VENV="$DIR/venv"
AUDIO_PERSO="${1:-}"
export HF_HOME="${HF_HOME:-/data/cache-huggingface}"
export CUDA_VISIBLE_DEVICES=""          # interdit tout usage GPU
mkdir -p "$DIR"

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg manquant : sudo apt-get install -y ffmpeg" >&2; exit 1; }

echo "=== 1/3 Environnement Python (uv, Python 3.12) ==="
if ! command -v uv >/dev/null 2>&1; then
  echo "uv introuvable. Installe-le : curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  uv venv --python 3.12 "$VENV"
fi
uv pip install --python "$VENV/bin/python" -q faster-whisper piper-tts huggingface_hub

echo "=== 2/3 Mesures (CPU uniquement) ==="
"$VENV/bin/python" -I - "$DIR" "$AUDIO_PERSO" <<'PY' | tee "$DIR/resultats-$(date +%Y%m%d-%H%M).txt"
import os, sys, time, wave, difflib, subprocess, platform
from huggingface_hub import hf_hub_download

out_dir, audio_perso = sys.argv[1], sys.argv[2]
PHRASE = ("Bonjour, peux-tu me dire quelle température il fera demain à La Rochelle, "
          "et me rappeler d'appeler le fondeur à quinze heures ?")

def wer(ref, hyp):
    norm = lambda s: "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in s).split()
    r, h = norm(ref), norm(hyp)
    sm = difflib.SequenceMatcher(a=r, b=h)
    err = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")
    return err / max(len(r), 1)

print(f"Machine : {platform.node()}  |  coeurs logiques : {os.cpu_count()}")
print(f"Date    : {time.strftime('%Y-%m-%d %H:%M')}\n")

# ---------- Synthese Piper (fr_FR) ----------
from piper import PiperVoice
voix = "fr/fr_FR/siwis/medium/fr_FR-siwis-medium"
onnx = hf_hub_download("rhasspy/piper-voices", voix + ".onnx")
hf_hub_download("rhasspy/piper-voices", voix + ".onnx.json")
t0 = time.perf_counter(); pv = PiperVoice.load(onnx); t_load = time.perf_counter() - t0

wav_piper = os.path.join(out_dir, "phrase_piper.wav")
temps = []
for _ in range(3):
    t0 = time.perf_counter()
    with wave.open(wav_piper, "wb") as wf:
        pv.synthesize_wav(PHRASE, wf)
    temps.append(time.perf_counter() - t0)
with wave.open(wav_piper) as wf:
    duree_piper = wf.getnframes() / wf.getframerate()
print("--- Synthese vocale Piper fr_FR-siwis-medium (CPU) ---")
print(f"chargement {t_load:.2f} s | synthese {min(temps):.2f} s pour {duree_piper:.1f} s d'audio"
      f" (x{duree_piper/min(temps):.0f} temps reel)\n")

# ---------- Audio a transcrire ----------
if audio_perso:
    src = os.path.join(out_dir, "audio_perso_16k.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_perso,
                    "-ac", "1", "-ar", "16000", src], check=True)
    ref = None
    print(f"Audio teste : {audio_perso} (ta voix, pas de texte de reference)\n")
else:
    src, ref = wav_piper, PHRASE
    print("Audio teste : phrase synthetisee par Piper (plus propre qu'une vraie voix)\n")
# Decodage par ffmpeg en tableau float32 16 kHz : on contourne PyAV, dont les
# versions recentes cassent faster-whisper (argument metadata_errors retire).
import numpy as np
pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", src, "-f", "f32le",
                      "-ac", "1", "-ar", "16000", "-"], check=True, capture_output=True).stdout
audio = np.frombuffer(pcm, dtype=np.float32)
duree = len(audio) / 16000

# ---------- Transcription faster-whisper int8 ----------
from faster_whisper import WhisperModel
print(f"--- Transcription faster-whisper int8 (CPU), audio de {duree:.1f} s ---")
print(f"{'modele':<16}{'threads':>8}{'charg.':>9}{'transcr.':>10}{'x t.reel':>10}{'WER':>7}")
for nom in ["small", "medium", "large-v3-turbo"]:
    for threads in [16, 32]:
        t0 = time.perf_counter()
        m = WhisperModel(nom, device="cpu", compute_type="int8", cpu_threads=threads)
        t_load = time.perf_counter() - t0
        res = []
        for _ in range(2):                      # 1er passage = chauffe, on garde le 2e
            t0 = time.perf_counter()
            segs, _ = m.transcribe(audio, language="fr", beam_size=1, vad_filter=False)
            texte = " ".join(s.text.strip() for s in segs)
            res.append(time.perf_counter() - t0)
        t = res[-1]
        w = f"{wer(ref, texte)*100:5.1f}%" if ref else "   -"
        print(f"{nom:<16}{threads:>8}{t_load:>8.1f}s{t:>9.2f}s{duree/t:>9.1f}x{w:>7}")
        if threads == 32:
            print(f"    -> \"{texte}\"")
        del m
print("\nLecture : 'transcr.' = temps d'attente apres la fin de ta phrase. Cible < 1 s.")
PY

echo "=== 3/3 Termine. Resultats dans $DIR ==="
