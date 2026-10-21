"""correctifs.py : adapte xiaozhi-esp32-server au francais et a un LLM local.
Chaque correctif verifie que le code d'origine est bien celui attendu ; sinon il s'arrete
sans rien modifier (cas d'une nouvelle version de xiaozhi a reverifier).
Usage : python correctifs.py /opt/xiaozhi/main/xiaozhi-server
"""
import sys
from pathlib import Path

RACINE = Path(sys.argv[1])
CORRECTIFS = [
    # 1. Coupure des phrases aussi sur le point, les deux-points et les points de suspension
    #    ASCII, sans couper un nombre (3.5 / 3,5 / 15:30) ni s'arreter sur un chiffre en cours d'arrivee.
    ("core/providers/tts/base.py", [
        ('''            "；",
            ";",
            "：",
        )
        self.first_sentence_punctuations = (''',
         '''            "；",
            ";",
            "：",
            ".",
            ":",
            "…",
        )
        self.first_sentence_punctuations = ('''),
        ('''            "；",
            ";",
            "：",
        )
        self.tts_stop_request = False''',
         '''            "；",
            ";",
            "：",
            ".",
            ":",
            "…",
        )
        self.tts_stop_request = False'''),
        ('''        for i, ch in enumerate(current_text):
            if ch in punctuations_to_use:
                last_seen[ch] = i''',
         '''        for i, ch in enumerate(current_text):
            if ch in punctuations_to_use:
                # [voix-fr] ne pas couper un nombre : 3.5  3,5  15:30 (ni un chiffre encore incomplet)
                if (ch in ".,:" and i > 0 and current_text[i - 1].isdigit()
                        and (i + 1 >= len(current_text) or current_text[i + 1].isdigit())):
                    continue
                last_seen[ch] = i'''),
    ]),
    # 2. Parametres supplementaires envoyes au LLM (ex. couper la reflexion de Qwen)
    ("core/providers/llm/openai/openai.py", [
        ('''        self.model_name = config.get("model_name")''',
         '''        self.model_name = config.get("model_name")
        self.extra_body = config.get("extra_body") or {}  # [voix-fr]'''),
        ('''        """根据域名自动禁用思考模式"""''',
         '''        """根据域名自动禁用思考模式"""
        if self.extra_body:  # [voix-fr]
            request_params.setdefault("extra_body", {}).update(self.extra_body)'''),
    ]),
    # 3. Jours de la semaine en francais dans le contexte donne au LLM
    ("core/utils/current_time.py", [
        ('''    "Monday": "星期一",
    "Tuesday": "星期二", 
    "Wednesday": "星期三",
    "Thursday": "星期四",
    "Friday": "星期五",
    "Saturday": "星期六",
    "Sunday": "星期日",''',
         '''    "Monday": "lundi",
    "Tuesday": "mardi",
    "Wednesday": "mercredi",
    "Thursday": "jeudi",
    "Friday": "vendredi",
    "Saturday": "samedi",
    "Sunday": "dimanche",'''),
    ]),
    # 4. Exemples injectes en mode outils, outil direct_answer et outils systeme :
    #    du chinois au francais (le modele imitait ces exemples et repondait en chinois).
    ("core/connection.py", [
        ('"description": "当用户的请求不匹配其他任何工具时，可用此选项直接回复。将回复内容写在response参数里。",',
         '"description": "Utilise cet outil pour répondre directement quand la demande ne correspond à aucun autre outil. Écris ta réponse complète, en français, dans le paramètre response.",  # [voix-fr]'),
        ('"description": "你回复用户的完整内容",',
         '"description": "Ta réponse complète à l\'utilisateur, en français",'),
        ('content="给我讲个故事吧"', 'content="Raconte-moi une histoire"'),
        ('\'{"response": "好呀，你想听什么类型的呀？童话、冒险还是搞笑的？选一个我给你开讲~"}\'',
         '\'{"response": "Avec plaisir ! Plutôt conte, aventure ou histoire drôle ?"}\''),
        ('content="已直接回复"', 'content="Réponse envoyée"'),
        ('content="拜拜"', 'content="Au revoir"'),
        ('\'{"say_goodbye": "再见，下次再聊~"}\'', '\'{"say_goodbye": "Au revoir, à bientôt !"}\''),
        ('content="退出意图已处理"', 'content="Fin de conversation traitée"'),
        ('role="assistant", content="再见，下次再聊~"', 'role="assistant", content="Au revoir, à bientôt !"'),
        # 5b. heure de fin de chaque reponse du robot (fenetre de suite du filtre de nom)
        ('''    def clearSpeakStatus(self):
        self.client_is_speaking = False''',
         '''    def clearSpeakStatus(self):
        self.client_is_speaking = False
        self.voixfr_fin_parole = time.time()  # [voix-fr]'''),
    ]),
    # 5. Filtre du nom : le robot ne repond qu'aux phrases contenant son nom
    #    (ou juste apres une reponse). Reglages filtre_nom dans .config.yaml.
    ("core/providers/asr/base.py", [
        ('''                enqueue_asr_report(conn, enhanced_text, audio_snapshot)
                # 使用自定义模块进行上报
                await startToChat(conn, enhanced_text)''',
         '''                enqueue_asr_report(conn, enhanced_text, audio_snapshot)
                from core.utils.voixfr_filtre_nom import accepte  # [voix-fr]
                if not accepte(conn, content_for_length_check):
                    logger.bind(tag=TAG).info(f"[voix-fr] ignore, nom du robot absent : {content_for_length_check}")
                    return
                await startToChat(conn, enhanced_text)'''),
    ]),
    # 6. Outils publies par le robot : descriptions japonaises traduites, outils
    #    inutilisables en francais masques (voir voixfr_outils_robot.py).
    ("core/providers/tools/device_mcp/mcp_handler.py", [
        ('''                    new_tool = {
                        "name": name,
                        "description": description,
                        "inputSchema": input_schema,
                    }''',
         '''                    from core.utils.voixfr_outils_robot import adapter  # [voix-fr]
                    adapte = adapter(name, description, input_schema)
                    if adapte is None:
                        logger.bind(tag=TAG).info(f"[voix-fr] outil du robot masque : {name}")
                        continue
                    description, input_schema = adapte
                    new_tool = {
                        "name": name,
                        "description": description,
                        "inputSchema": input_schema,
                    }'''),
    ]),
    ("plugins_func/functions/handle_exit_intent.py", [
        ('"description": "当用户想结束对话或需要退出系统时调用",',
         '"description": "À appeler quand l\'utilisateur veut terminer la conversation (au revoir, bonne nuit, c\'est tout).",  # [voix-fr]'),
        ('"description": "和用户友好结束对话的告别语",',
         '"description": "Phrase d\'au revoir chaleureuse, en français",'),
        ('say_goodbye = "再见，祝您生活愉快！"', 'say_goodbye = "Au revoir, à bientôt !"'),
    ]),
    # get_lunar (calendrier lunaire chinois) n'est plus impose a chaque conversation
    ("core/providers/tools/server_plugins/plugin_executor.py", [
        ('necessary_functions = ["handle_exit_intent", "get_lunar"]',
         'necessary_functions = ["handle_exit_intent"]  # [voix-fr] get_lunar retire'),
    ]),
]

erreurs = []
plan = []
for fichier, remplacements in CORRECTIFS:
    p = RACINE / fichier
    txt = p.read_text(encoding="utf-8")
    if "[voix-fr]" in txt or ('"lundi"' in txt and "current_time" in fichier):
        print(f"  deja corrige : {fichier}")
        continue
    for avant, apres in remplacements:
        if txt.count(avant) != 1:
            erreurs.append(f"{fichier} : bloc attendu introuvable ou ambigu :\n{avant[:120]}...")
        txt = txt.replace(avant, apres, 1)
    plan.append((p, txt))

if erreurs:
    print("ECHEC, aucun fichier modifie. Le code de xiaozhi a change :")
    print("\n".join(erreurs))
    sys.exit(1)
for p, txt in plan:
    p.write_text(txt, encoding="utf-8")
    print(f"  corrige : {p.relative_to(RACINE)}")
