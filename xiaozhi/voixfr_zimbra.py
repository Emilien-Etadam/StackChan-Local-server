"""[voix-fr] Agenda et mails Zimbra pour le robot : lire l'agenda, ajouter un rendez-vous,
lire les mails, preparer une reponse dans les Brouillons. AUCUN envoi de mail : ce module
ne contient pas de code d'envoi (pas de SMTP), la reponse attend dans Brouillons.

Reglage dans data/.config.yaml (a remplir sur le LXC, jamais dans le depot) :
plugins:
  zimbra:
    serveur: mail.exemple.fr          # nom du serveur Zimbra (HTTPS 443 et IMAPS 993)
    compte: moi@exemple.fr
    mot_de_passe: "..."
    calendrier: ""                    # vide = premier agenda du compte
    brouillons: Drafts                # dossier IMAP des brouillons
    fuseau: Europe/Paris
"""
import asyncio
import datetime as dt
import email
import imaplib
import re
import time
from email.message import EmailMessage
from email.policy import default as politique
from email.utils import getaddresses, make_msgid, parseaddr
from zoneinfo import ZoneInfo

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
logger = setup_logging()


def _cfg(conn):
    c = conn.config.get("plugins", {}).get("zimbra") or {}
    if not (c.get("serveur") and c.get("compte") and c.get("mot_de_passe")):
        return None
    return c


def _fn(nom, description, proprietes, requis):
    return {"type": "function", "function": {"name": nom, "description": description,
            "parameters": {"type": "object", "properties": proprietes, "required": requis}}}


def _non_configure():
    return ActionResponse(Action.REQLLM, "L'agenda et les mails ne sont pas encore configurés sur le serveur.", None)


# ---------------------------------------------------------------- agenda (CalDAV)
def _agenda(c):
    import caldav
    url = c.get("url_dav") or f"https://{c['serveur']}/dav/"     # url_dav : autre adresse CalDAV si besoin
    client = caldav.DAVClient(url=url, username=c["compte"], password=c["mot_de_passe"])
    agendas = client.principal().calendars()
    if not agendas:
        raise RuntimeError("aucun agenda sur ce compte")
    nom = (c.get("calendrier") or "").strip().lower()
    if nom:
        for a in agendas:
            if (a.name or "").lower() == nom or str(a.url).rstrip("/").lower().endswith("/" + nom):
                return a
    return agendas[0]


def _quand(v, tz):
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=tz)).astimezone(tz)
    return dt.datetime.combine(v, dt.time(0), tz)    # journee entiere


def lire_agenda(c, jours):
    tz = ZoneInfo(c.get("fuseau", "Europe/Paris"))
    debut = dt.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    fin = debut + dt.timedelta(days=max(1, min(int(jours), 31)))
    evts = []
    for e in _agenda(c).search(start=debut, end=fin, event=True, expand=True):
        v = e.vobject_instance.vevent
        d = _quand(v.dtstart.value, tz)
        journee = not isinstance(v.dtstart.value, dt.datetime)
        evts.append((d, journee, str(getattr(v, "summary", None).value if hasattr(v, "summary") else "(sans titre)"),
                     str(v.location.value) if hasattr(v, "location") else ""))
    evts.sort(key=lambda x: x[0])
    return evts


def ajouter_rdv(c, titre, debut, duree_min, lieu):
    tz = ZoneInfo(c.get("fuseau", "Europe/Paris"))
    d = dt.datetime.fromisoformat(debut)
    d = d if d.tzinfo else d.replace(tzinfo=tz)
    f = d + dt.timedelta(minutes=max(5, int(duree_min)))
    _agenda(c).save_event(ics_evenement(titre, d, f, lieu))
    return d, f


def _echap(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_evenement(titre, d, f, lieu=""):
    """iCalendar ecrit a la main (heures en UTC) : pas de dependance a la version d'icalendar."""
    utc = lambda x: x.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//voix-fr//robot//FR", "BEGIN:VEVENT",
              f"UID:{make_msgid(domain='voix-fr')[1:-1]}", f"DTSTAMP:{utc(dt.datetime.now(dt.timezone.utc))}",
              f"DTSTART:{utc(d)}", f"DTEND:{utc(f)}", f"SUMMARY:{_echap(titre)}"]
    if lieu:
        lignes.append(f"LOCATION:{_echap(lieu)}")
    lignes += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lignes) + "\r\n"


@register_function("agenda_lire", _fn(
    "agenda_lire",
    "Lit les rendez-vous de l'agenda à partir d'aujourd'hui. jours : 1 = aujourd'hui, 2 = aujourd'hui et demain, "
    "7 = la semaine.",
    {"jours": {"type": "integer", "description": "nombre de jours à lire (1 à 31)"}}, []), ToolType.SYSTEM_CTL)
async def agenda_lire(conn, jours: int = 1):
    c = _cfg(conn)
    if not c:
        return _non_configure()
    try:
        evts = await asyncio.to_thread(lire_agenda, c, jours or 1)
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] agenda : {e}")
        return ActionResponse(Action.REQLLM, "L'agenda est inaccessible.", None)
    if not evts:
        return ActionResponse(Action.REQLLM, "Aucun rendez-vous sur cette période.", None)
    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    lignes = []
    for d, journee, titre, lieu in evts:
        quand = f"{jours_fr[d.weekday()]} {d.day}/{d.month}" + ("" if journee else f" à {d:%H:%M}")
        lignes.append(f"- {quand} : {titre}" + (f" ({lieu})" if lieu else ""))
    return ActionResponse(Action.REQLLM, "Rendez-vous :\n" + "\n".join(lignes), None)


@register_function("agenda_ajouter", _fn(
    "agenda_ajouter",
    "Ajoute un rendez-vous dans l'agenda. Avant d'appeler, assure-toi d'avoir le titre, le jour et l'heure ; "
    "après, répète le rendez-vous créé en une phrase.",
    {"titre": {"type": "string"},
     "debut": {"type": "string", "description": "date et heure locales au format AAAA-MM-JJTHH:MM"},
     "duree_min": {"type": "integer", "description": "durée en minutes (60 par défaut)"},
     "lieu": {"type": "string", "description": "facultatif"}},
    ["titre", "debut"]), ToolType.SYSTEM_CTL)
async def agenda_ajouter(conn, titre: str = "", debut: str = "", duree_min: int = 60, lieu: str = ""):
    c = _cfg(conn)
    if not c:
        return _non_configure()
    try:
        d, f = await asyncio.to_thread(ajouter_rdv, c, titre, debut, duree_min or 60, lieu)
    except ValueError:
        return ActionResponse(Action.REQLLM, f"Date incompréhensible : {debut}.", None)
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] agenda : {e}")
        return ActionResponse(Action.REQLLM, "Impossible d'ajouter le rendez-vous.", None)
    logger.bind(tag=TAG).info(f"[voix-fr] agenda : ajoute « {titre} » {d.isoformat()}")
    return ActionResponse(Action.REQLLM, f"Rendez-vous ajouté : {titre}, le {d:%d/%m à %H:%M}, jusqu'à {f:%H:%M}.", None)


# ---------------------------------------------------------------- mails (IMAP)
def _imap(c):
    m = imaplib.IMAP4_SSL(c["serveur"], int(c.get("port_imap", 993)))
    m.login(c["compte"], c["mot_de_passe"])
    return m


def _texte(msg, maxi=1500):
    corps = msg.get_body(preferencelist=("plain", "html"))
    if corps is None:
        return ""
    t = corps.get_content()
    if corps.get_content_subtype() == "html":
        t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
        t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"(?m)^>.*$", "", t)              # citations des messages precedents
    return re.sub(r"\s+", " ", t).strip()[:maxi]


def lire_mails(c, combien, non_lus):
    m = _imap(c)
    try:
        m.select("INBOX", readonly=True)        # lecture seule : rien n'est marque lu
        typ, data = m.uid("search", None, "UNSEEN" if non_lus else "ALL")
        uids = data[0].split()[-max(1, min(int(combien), 10)):]
        out = []
        for uid in reversed(uids):
            typ, d = m.uid("fetch", uid, "(RFC822.SIZE BODY.PEEK[HEADER])")
            entete = email.message_from_bytes(d[0][1], policy=politique)
            taille = int(re.search(rb"RFC822\.SIZE (\d+)", d[0][0]).group(1))
            texte = ""
            if taille < 2_000_000:
                typ, d2 = m.uid("fetch", uid, "(BODY.PEEK[])")
                texte = _texte(email.message_from_bytes(d2[0][1], policy=politique))
            out.append({"uid": uid.decode(), "de": str(entete.get("From", "")), "objet": str(entete.get("Subject", "")),
                        "date": str(entete.get("Date", "")), "texte": texte})
        return out
    finally:
        m.logout()


def preparer_reponse(c, uid, texte):
    """Construit la reponse et la depose dans Brouillons. N'envoie rien."""
    m = _imap(c)
    try:
        m.select("INBOX", readonly=True)
        typ, d = m.uid("fetch", uid.encode(), "(BODY.PEEK[])")
        if not d or d[0] is None:
            raise LookupError("mail introuvable")
        orig = email.message_from_bytes(d[0][1], policy=politique)
        rep = construire_reponse(c["compte"], orig, texte)
        dossier = c.get("brouillons", "Drafts")
        typ, r = m.append(dossier, r"(\Draft \Seen)", imaplib.Time2Internaldate(time.time()), rep.as_bytes())
        if typ != "OK":
            raise RuntimeError(f"depot dans {dossier} refuse : {r}")
        return rep["To"], rep["Subject"]
    finally:
        m.logout()


def construire_reponse(compte, orig, texte):
    rep = EmailMessage()
    rep["From"] = compte
    rep["To"] = orig.get("Reply-To") or orig.get("From", "")
    objet = str(orig.get("Subject", ""))
    rep["Subject"] = objet if re.match(r"(?i)^(re|tr|fw|fwd)\s*:", objet) else f"Re: {objet}"
    if orig.get("Message-ID"):
        rep["In-Reply-To"] = orig["Message-ID"]
        rep["References"] = (str(orig.get("References", "")) + " " + orig["Message-ID"]).strip()
    rep["Message-ID"] = make_msgid(domain=compte.split("@")[-1])
    rep["Date"] = email.utils.formatdate(localtime=True)
    cite = "\n".join("> " + l for l in _texte(orig, 4000).split(". "))
    rep.set_content(f"{texte}\n\n{orig.get('Date', '')}, {parseaddr(str(orig.get('From', '')))[1]} a écrit :\n{cite}\n")
    return rep


@register_function("mails_lire", _fn(
    "mails_lire",
    "Lit les derniers mails reçus (expéditeur, objet, début du texte), sans les marquer comme lus. "
    "Résume-les en une phrase chacun et donne leur numéro.",
    {"combien": {"type": "integer", "description": "nombre de mails (1 à 10, 5 par défaut)"},
     "non_lus": {"type": "boolean", "description": "seulement les non lus (oui par défaut)"}}, []), ToolType.SYSTEM_CTL)
async def mails_lire(conn, combien: int = 5, non_lus: bool = True):
    c = _cfg(conn)
    if not c:
        return _non_configure()
    try:
        mails = await asyncio.to_thread(lire_mails, c, combien or 5, non_lus is not False)
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] mails : {e}")
        return ActionResponse(Action.REQLLM, "La boîte mail est inaccessible.", None)
    if not mails:
        return ActionResponse(Action.REQLLM, "Aucun mail" + (" non lu." if non_lus is not False else "."), None)
    conn.voixfr_mails = {i: x["uid"] for i, x in enumerate(mails, 1)}
    lignes = []
    for i, x in enumerate(mails, 1):
        nom = getaddresses([x["de"]])[0][0] or getaddresses([x["de"]])[0][1]
        lignes.append(f"Mail {i} : de {nom}, objet « {x['objet']} », {x['date'][:22]}.\n   {x['texte'][:600]}")
    return ActionResponse(Action.REQLLM, "\n".join(lignes), None)


@register_function("mail_brouillon", _fn(
    "mail_brouillon",
    "Prépare une réponse à un mail lu avec mails_lire et la range dans les Brouillons, SANS l'envoyer : "
    "l'utilisateur la relira et l'enverra lui-même. Rédige une réponse complète et polie, en français.",
    {"numero": {"type": "integer", "description": "numéro du mail donné par mails_lire"},
     "texte": {"type": "string", "description": "texte complet de la réponse"}},
    ["numero", "texte"]), ToolType.SYSTEM_CTL)
async def mail_brouillon(conn, numero: int = 0, texte: str = ""):
    c = _cfg(conn)
    if not c:
        return _non_configure()
    uid = (getattr(conn, "voixfr_mails", None) or {}).get(int(numero or 0))
    if not uid:
        return ActionResponse(Action.REQLLM, "Je ne sais pas de quel mail il s'agit : lis d'abord les mails.", None)
    try:
        dest, objet = await asyncio.to_thread(preparer_reponse, c, uid, texte)
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] brouillon : {e}")
        return ActionResponse(Action.REQLLM, "Impossible de préparer le brouillon.", None)
    logger.bind(tag=TAG).info(f"[voix-fr] brouillon pret pour {dest} : {objet}")
    return ActionResponse(Action.REQLLM, f"Brouillon rangé dans Brouillons, à {dest}, objet « {objet} ». Rien n'a été envoyé.", None)
