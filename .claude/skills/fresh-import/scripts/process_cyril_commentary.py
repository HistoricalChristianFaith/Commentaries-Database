#!/usr/bin/env python3
"""Import Cyril of Alexandria's Commentary on the Gospel of Luke (R. Payne Smith's 1859
translation from the Syriac, supplemented from the Greek catenae, as transcribed by Roger Pearse)
into the Commentaries-Database, one piece at a time, by driving a headless ``claude`` agent.

A per-father copy of process_berengaudus_commentary.py (see ../SKILL.md, "Other fathers"): the
same two-prompt flow, splitting, logs and --check. What differs is the source layout:

    Writings-Database/Cyril of Alexandria/Commentary on the Gospel of Luke.html

    <h1>..</h1><i>source note</i>               (the preamble)
    <h2>Preface to the online edition</h2>      (Pearse's: stripped, see WORKS["strip"])
    <h2>Translator's Introduction</h2>          (Payne Smith's: stripped)
    <h2>SERMON XL.</h2>                         (a sermon, or a group of catena fragments)
    7:36-50. <i>lemma</i><br><br>               (a verse label and the Gospel lemma)
    homily ...<br><br>
    7:41. <i>lemma</i><br><br> ...              (in the catena parts: one label per fragment)

``load_work`` cuts every <h2> group into one section per verse label, as Berengaudus's does per
bold lemma, so that the rest -- pieces, prompts, --check, the audit and import_checks.py -- works
unchanged. A section's heading is the label normalised ("7:36-50", "19:45-20:8"); its html
keeps the label (the agent sees it as a hint), its body drops it (the label is Payne Smith's
reference, not Cyril's text). Text under an <h2> before its first label (a sermon that only
continues the previous one's passage, or catena fragments without a label) is a non-verse
section headed by the <h2> text.

    python3 process_cyril_commentary.py Luke --dry-run
    python3 process_cyril_commentary.py Luke --split-only
    python3 process_cyril_commentary.py Luke Part002_Ch02.html
    python3 process_cyril_commentary.py Luke --start-after Part002_Ch02.html
    python3 process_cyril_commentary.py Luke --check
"""

import argparse
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from urllib.parse import quote

# --- Paths --------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# These scripts live in <Commentaries-Database>/.claude/skills/fresh-import/scripts.
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
# The claude agent runs here so the Commentaries-Database CLAUDE.md conventions apply
# and its relative `<Father>/<Book Verse>.toml` writes land in the right tree.
PROJECT_DIR = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
BOOK_NAMES_PATH = os.path.join(PROJECT_DIR, "book_names.json")
# The Writings-Database checkout: $WRITINGS_DB, else a sibling of the Commentaries-Database.
WRITINGS_DIR = os.environ.get("WRITINGS_DB") or os.path.join(
    os.path.dirname(PROJECT_DIR), "Writings-Database")
# Units and run logs go here (gitignored), not next to the scripts.
WORK_DIR = os.path.join(SKILL_DIR, "work")
# KJV lookup for the agent, run from PROJECT_DIR.
KJV_LOOKUP = 'python3 .claude/skills/fresh-import/scripts/kjv_lookup.py "<Book> <C>:<V>"'

FATHER = "Cyril of Alexandria"

# A chapter with more html than this is cut into near-equal parts at <h2> boundaries.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "Luke": {
        "html": "Cyril of Alexandria/Commentary on the Gospel of Luke.html",
        "book": "Luke",
        "source_title": "Commentary on the Gospel of Luke",
        "strip": [
            # Pearse's preface and Payne Smith's title page and preface: not Cyril's text.
            r"(?s)<h2>Preface to the online edition</h2>.*?(?=<h2>COMMENTARY OF S\. CYRIL,</h2>)",
            # The work's title page (its two <h2> lines and the bold lines between them): keep
            # the first <h2> so the opening catena fragments (1:2 ...) have a group of their own.
            r"(?s)(?<=<h2>COMMENTARY OF S\. CYRIL,</h2>\n).*?------------------<br><br>\n",
            # Payne Smith's notes of where a stretch comes from ("[From Mai.]", "[From the
            # Syriac MS. 12,165.]", "From the Syriac, MS. 12,154."), as a paragraph of their own
            # or opening one.
            r"\[From [^\]]{0,40}\](?:\s*<br><br>\n?|\s*)",
            r"(?m)^From the Syriac[.,] MS\. ?[\d,]+\.?<br><br>\n",
            # His and Pearse's notes on lost and recovered text.
            r"\[<i>Sermon 98 restarts here</i>\]",
            r"(?:<i>\. </i>)?\[<i>The Syriac recommences</i>\]<i> </i>",
            # (Sermon CXXVII: its label "19:1-10." heads only this note; the fragments that
            # follow carry their own labels, 19:2 and 19:5.)
            r"19:1-10\. \[<i>The first half of this Sermon has not survived[^\]]*\]<br><br>\n",
            r"(?s)\[The rest of this \(96th\) Exposition.*?-- translator</i>\]<br><br>\n",
            r"(?s)\[<i>Here the Syriac finally stops.*?</i>\]<br><br>\n",
            # Lacunae standing as a paragraph of their own ("* * * * *", once with "[the
            # remainder is lost]" between the stars).
            r"(?m)^(?:[ *]|&nbsp;|\[the remainder is lost\])*\*(?:[ *]|&nbsp;)*<br><br>\n",
            # Rubrics of the Syriac manuscripts heading a sermon ("THIS HOMILY IS FIT TO BE READ
            # IN A TIME OF STRUGGLE ...", "THE SAME SUBJECT CONTINUED.") and the scribe's
            # closing "PRAISE GOD.".
            r"<b>(?:THIS (?:HOMILY|EXPOSITION)|This Exposition|THE SAME SUBJECT|UPON THE SAME)"
            r"[^<]*(?:<i> </i>[^<]*)?</b>\s*<br><br>\n",
            r"<i>(?:The same subject continued\.|THE\s+SAME\s+SUBJECT\s+CONTINUED\.)</i><br><br>\n",
            r"PRAISE GOD\.<br><br>\n",
            # The scribe's colophon closing the first volume of the Syriac, after Sermon LXXX.
            r"(?s)<i>Here ends the first portion of the Explanation.*?Amen and Amen\.</i><br><br>\n",
        ],
        "notes": (
            "The translator's labels mostly give the right KJV verses, but check each against the "
            "wording (three wrong ones have been corrected in the source: \"4:22\", \"10:23-24\" and "
            "\"11:52-12:3\"). \"Luke ii. 1.\" is 2:1. A range crossing chapters is written "
            "like \"Luke 21_37-22_6\". Cyril passes over many verses; that is fine.\n\n"
            "THE TWO KINDS OF TEXT. (1) Catena fragments (most of chapters 1-6, and e.g. 17:1-14, "
            "19:2, 19:5, 23:44 to the end): a label with a short lemma (\"4:3. And the devil said "
            "unto him.\"), then a short comment; each is usually ONE block under its verse. (2) "
            "Sermons (most of the work): the <h2> \"SERMON XL.\", then a label and a lemma quoting "
            "the whole passage (often ten verses or more), then a long homily. A homily usually "
            "opens with an exordium (a Scripture text or a word to the hearers, e.g. \"ALL ye "
            "people, clap your hands, and praise God\"), reaches the passage, and works through it, "
            "quoting each verse as it comes to it; it ends with a doxology (\"by Whom and with Whom "
            "to God the Father be praise and dominion, with the Holy Spirit, for ever and ever, "
            "Amen.\"). The exordium stays with the lemma at the start of the first block; the "
            "doxology stays at the end of the last block. Split the homily by verse where it really "
            "moves on, but don't chop it into tiny fragments: use a range when a stretch treats "
            "several verses as one argument, or tells the whole story before expounding it.\n\n"
            "EVERY LABEL STARTS ITS OWN BLOCK: each section's first block starts exactly at the "
            "section start, with the lemma whole and uncut; never join the end of one section to "
            "the next one's lemma, even when both are the same verse (the two \"1:79\" fragments, "
            "the two \"2:7\" ones, the four \"11:2\" sermons each make their own blocks, one after "
            "the other in the same file). Some lemmas have no label: in the \"13:6-9\" section "
            "(Sermon XCVI and the catena text that replaces the lost sermons XCVII-XCVIII), after "
            "the fig-tree (which the sermon introduces by the slaughter of the Galilaeans, 13:1-5) "
            "the text goes on to the woman bowed together (\"Behold there was a woman, who had a "
            "spirit of infirmity eighteen years.\", 13:11), the ruler of the synagogue (13:14-17) and "
            "the mustard seed and the leaven (\"It is like a grain of mustard seed.\", 13:19-21): "
            "file each part under its own verses. Likewise \"Love your enemies.\" inside Sermon XXIX "
            "(the first \"6:24\" section) begins the comment on 6:27. Sermons III and IV have only a "
            "label and no lemma (\"cc. 2:21-24.\", \"cc.2:25-35.\"): their first block starts with the "
            "sermon's first words (\"VERY numerous indeed is the assembly\"). Sermon XXIX begins "
            "mid-sentence after a gap in the manuscript (\"* * * * * * * * receive those things that "
            "will lead you unto life eternal.\"): keep the stars, as printed, at the start of its "
            "first block. Sermon XXXIII's lemma is in quotation marks, not italics (\"And why, "
            "saith He, beholdest thou the mote that is in thy brother's eye\"): it is still the "
            "lemma.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the verse(s) "
            "its COMMENTARY addresses. So when a lemma quotes several verses but the comment after "
            "it addresses only the first of them, file that block (lemma included, uncut) under that "
            "verse alone; when the comment begins on a later verse (or on an earlier one, as Sermon "
            "XCVI begins on 13:1-5), start the range there. The lemma's span never widens a block's "
            "range.\n\n"
            "SECTIONS WITHOUT A LABEL. Five sermons only continue the previous sermon's passage, "
            "with no label or lemma of their own: \"SERMON CXII.\" continues the rich man and "
            "Lazarus (16:19-31), \"SERMON CXXIII.\" the rich ruler (18:18-27), \"SERMON CXXIX.\" the "
            "pounds (19:11-27), \"SERMON CXXXIII.\" the question of Christ's authority (20:1-8) and "
            "\"SERMON CXLVII.\" the agony on the Mount of Olives (22:39-46). Each opens with an "
            "exordium: file it, as the first block of that sermon, with the comment that follows it, "
            "under the verse(s) that comment addresses; then go on verse by verse as usual. Five "
            "groups of catena fragments have no label either; they come from sermons on the "
            "neighbouring passages, so file each under the Luke verse(s) its comment applies to, as "
            "blocks of their own: \"FROM SERMON XXI.\" (the strong man's house, applied to Levi's "
            "call, 5:27-28) and \"FROM THE SAME SERMON.\" (the lost sheep, ending \"they find fault "
            "with them to the disciples; for listen,\", which leads into the 5:30 lemma that "
            "follows), \"FROM SERMON XXII.\" (\"And no man puts now wine into old skins.\", 5:37), "
            "\"FROM SERMON XXIII.\" (Hosea's \"I require mercy, and not sacrifice\", opening the "
            "sermon on the sabbath healing of 6:6-11) and \"FROM SERMON XXV.\" (the Apostle's \"Be "
            "ye like unto me, as I also am unto Christ.\", opening the sermon on 6:17-19). Their "
            "quotations of other books (the strong man and the lost sheep are in Matthew's "
            "wording, Matthew 12:29 and 18:12-13; Hosea 6:6; 1 Corinthians 11:1) may also be "
            "cross-filed where Cyril genuinely expounds them, as the CROSS-BOOK rule says.\n\n"
            "Keep everything verbatim: the translator's dashes written as four hyphens (\"earnest "
            "the hearer:----for we see the Church full:----but\"), \"&c.\" (as the \"&\" character), "
            "the straight double and single quotation marks as printed, the few Greek words "
            "(ἐπιούσιος), the translator's own words in square brackets inside the text (\"[the "
            "bread signifies]\", \"[at the passover]\", and the longer bracketed passages he supplied "
            "from the catenae in Sermons XCI and CXXVI), the stars marking a gap inside a "
            "paragraph (\"* * *\"), and the misprints of the printed text (\"whore He says\", \"And no "
            "man puts now wine\"): copy them as printed, don't correct them. The pieces have had the "
            "footnote markers removed, and also the translator's notes of where each stretch comes "
            "from (\"[From Mai.]\", \"[From the Syriac MS. 12,165.]\"), his notes on lost text, the "
            "Syriac manuscripts' rubrics (\"THIS HOMILY IS FIT TO BE READ ...\", \"THE SAME SUBJECT "
            "CONTINUED.\"), the scribe's colophons and lines of stars standing alone: the full "
            "source html still has them, but none of them is imported. The <h2> sermon headings, "
            "with their titles (\"SERMON L. Fit to be read at a time of persecution.\"), are not "
            "imported either. Cyril quotes the Psalms and the prophets without chapter numbers: "
            "find any cross-reference by matching the wording against the KJV.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on the Gospel of Luke\" blocks in the files you write to (e.g. a block from "
            "the piece before yours under the same verse, or a cross-reference). Those are NOT old "
            "imports or duplicates: leave them exactly as they are and append yours after them. "
            "Many Luke files already hold \"Catena Aurea by Aquinas\" blocks (Aquinas's catena, "
            "which often quotes this same commentary of Cyril's in another wording) and one holds "
            "a letter: they stay first, untouched -- don't remove, merge or \"deduplicate\" them.\n\n"
            "There is no prologue: the work begins with the fragment on 1:2 (\"Who from the "
            "beginning were eyewitnesses and ministers of the Word.\"), and there is no Cyril "
            "\"Luke 1_1\" file. Nothing in the pieces is to be skipped as a closing note: the work "
            "ends with the fragment on 24:45, whose last words are \"by Whom and with Whom to God "
            "the Father be glory and power with the Spirit for ever and ever. Amen.\"; import it to "
            "its end."
        ),
    },
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing Cyril of Alexandria source_urls ("file=Cyril%2520of%2520Alexandria%2F...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"cyril_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
CHAPTER_RE = re.compile(r"^(\d+):\d")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn\d+" id="r\d+">\d+</a></sup>')
NOTES_SECTION_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">.*?</section>\s*', re.S)


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


# A verse label opening a paragraph: Payne Smith's reference to the lemma that follows, in the
# forms the text has: "7:36-50.", "1:53", "3: 15-17.", "cc. 2:21-24.", "21:37-22:6.",
# "19:45-48; 20:1-8.", "22:39-42,45,46.", "23:1-5, 18, 19.", "11:52 ... 12:1-3.", "Luke ii. 1.",
# "(6:24)". It must be followed by the lemma (italics, a quotation mark or a bracket) or end its
# paragraph (the "cc." labels of Sermons III and IV stand alone).
LABEL_RE = re.compile(
    r"(?:cc\.\s*)?"
    r"(?P<lab>\(\d+:\d+\)|Luke [ivxl]+\. \d+|\d+:\s*\d+(?:\s*(?:-|,|;|\.\.\.)\s*(?:\d+:)?\s*\d+)*)"
    r"\s*\.?\s*(?:<sup>\s*</sup>\s*)?\.?\s*(?=<i>|&quot;|\[|<br>|\*)")
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}


def label_heading(lab):
    """Normalise a verse label to a heading: '3: 15-17' -> '3:15-17', 'Luke ii. 1' -> '2:1',
    '19:45-48; 20:1-8' -> '19:45-20:8', '11:52 ... 12:1-3' -> '11:52-12:3',
    '23:1-5, 18, 19' -> '23:1-5,18,19'."""
    lab = lab.strip("()")
    m = re.fullmatch(r"Luke ([ivxl]+)\. (\d+)", lab)
    if m:
        return f"{ROMAN[m[1]]}:{m[2]}"
    lab = re.sub(r"\s+", "", lab)
    m = re.fullmatch(r"(\d+):(\d+)(?:-\d+)?(?:;|\.\.\.)(\d+):(?:\d+-)?(\d+)", lab)
    if m:
        return f"{m[1]}:{m[2]}-{m[3]}:{m[4]}"
    return lab


def load_work(work):
    """Return (preamble_html, sections): one section per verse label (heading = the label,
    normalised), plus the non-verse sections (text under an <h2> before its first label). Each
    keeps its raw html (heading and label included), its body (without them) and its chapter
    (None if non-verse)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Payne Smith's and Pearse's footnotes are editorial apparatus, not Cyril: drop the inline
    # markers and the notes section.
    text = FOOTNOTE_REF_RE.sub("", text)
    text = NOTES_SECTION_RE.sub("", text)
    # Payne Smith's own note marks that Pearse left unlinked when he omitted the notes
    # ("turn<sup>2</sup> away", "spiritually-minded <sup>e</sup> men"): drop the mark, keep any
    # space inside it. (<sup>&quot;</sup> and <sup>...</sup> are text and stay.)
    text = re.sub(r"<sup>(?:[a-z]|\d{1,2})(\s*)</sup>", r"\1", text)
    # Other editorial marks the work asks to drop from its sections (not from the preamble).
    cut = text.find("<h2>")
    for pat in work.get("strip", []):
        text = text[:cut] + re.sub(pat, "", text[cut:])
    parts = H2_RE.split(text)
    preamble = parts[0]
    sections = []
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        heading = _clean(h2)
        body = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        # Paragraph starts (the body's start, or just after a "<br><br>" and its newline).
        para_starts = [0] + [m.end() for m in re.finditer(r"<br><br>\n?", body)]
        starts = sorted({a for a in para_starts if LABEL_RE.match(body, a)})
        lead = body[:starts[0]] if starts else body
        if _clean(lead) or not starts:
            sections.append({"heading": heading, "chapter": None, "html": h2 + "\n" + lead,
                             "body": lead})
            h2 = ""
        for k, a in enumerate(starts):
            chunk = body[a:starts[k + 1] if k + 1 < len(starts) else len(body)]
            m = LABEL_RE.match(chunk)
            head = label_heading(m["lab"])
            sections.append(
                {
                    "heading": head,
                    "chapter": int(re.match(r"\d+", head)[0]),
                    # The <h2> stays in the html of its group's first section.
                    "html": (h2 + "\n" if h2 and not k else "") + chunk,
                    "body": chunk[m.end():],
                }
            )
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in re.split(r"(?:<br\s*/?>\s*){2,}", section["body"]):
        p = _clean(p)
        if p:
            out.append(p)
    return out


def chapter_groups(sections):
    """Contiguous runs of sections by chapter; a non-verse section joins the group of the
    verse section after it (or the last group, if nothing follows)."""
    groups, pending = [], []
    for s in sections:
        if s["chapter"] is None:
            pending.append(s)
            continue
        if not groups or groups[-1]["chapter"] != s["chapter"]:
            groups.append({"chapter": s["chapter"], "sections": []})
        groups[-1]["sections"].extend(pending + [s])
        pending = []
    if pending:
        if not groups:
            groups.append({"chapter": 0, "sections": []})
        groups[-1]["sections"].extend(pending)
    return groups


def split_evenly(sections, cap):
    """Cut a list of sections into the fewest near-equal runs (at section boundaries)
    whose html each fits under `cap`, as far as section sizes allow."""
    sizes = [len(s["html"]) for s in sections]
    total = sum(sizes)
    k = max(1, math.ceil(total / cap))
    while True:
        runs, cur, acc = [], [], 0
        for s, n in zip(sections, sizes):
            # Cut before this section if that lands closer to the next even boundary.
            target = total * (len(runs) + 1) / k
            if cur and len(runs) < k - 1 and abs(acc - target) <= abs(acc + n - target):
                runs.append(cur)
                cur = []
            cur.append(s)
            acc += n
        runs.append(cur)
        too_big = any(
            sum(len(s["html"]) for s in r) > cap and len(r) > 1 for r in runs
        )
        if not too_big or k >= len(sections):
            return runs
        k += 1


def make_units(preamble, sections, cap):
    """The ordered list of pieces: {name, chapter, sections}."""
    units = []
    for g in chapter_groups(sections):
        runs = split_evenly(g["sections"], cap)
        for j, run in enumerate(runs):
            suffix = chr(ord("a") + j) if len(runs) > 1 else ""
            units.append(
                {
                    "name": f"Part{len(units) + 1:03d}_Ch{g['chapter']:02d}{suffix}.html",
                    "chapter": g["chapter"],
                    "sections": run,
                }
            )
    return units


def unit_html(preamble, unit):
    tail = "</article>\n" if "<article" in preamble else ""
    return preamble + "".join(s["html"] for s in unit["sections"]) + tail


def write_units(work_key, preamble, units):
    d = units_dir_for(work_key)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for u in units:
        with open(os.path.join(d, u["name"]), "w", encoding="utf-8") as f:
            f.write(unit_html(preamble, u))
    return d


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have Cyril of Alexandria's {title} here: \"{units_dir}/{first_unit}\" with the files "
    "continuing up to \"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, "
    "from our PUBLIC-DOMAIN English translation of the whole work (R. Payne Smith's, from the "
    "Syriac version, supplemented from the Greek catenae), \"{html_path}\" (consult it if you "
    "need surrounding context). The work is Cyril's commentary on the Gospel of {book}: "
    "homilies on it and, where the Syriac is lost, fragments of them preserved in the catenae "
    "-- file everything under the book \"{book}\", in the \"{father}/\" folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (the translator's verse labels and sermon headings in it: {headings})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. Each "
    "piece repeats the work's title and the source note at the top -- that note is background "
    "for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. The <h2> headings are sermon headings (\"SERMON XL.\", \"FROM SERMON XXI. "
    "Explanation of what follows.\"). The Gospel passage Cyril comments on (the lemma) opens "
    "with the translator's verse label, e.g. \"7:36-50.\" or \"4:3.\", followed by the lemma in "
    "italics; Cyril's comment follows in the paragraphs after it, up to the next label. Treat "
    "these labels as HINTS ONLY: they may be off. For each stretch of commentary, work out "
    "which KJV verse(s) it actually expounds -- compare the Scripture Cyril quotes and "
    "discusses with the KJV text, looking it up with `" + KJV_LOOKUP + "` -- and file it there, "
    "under KJV chapter/verse numbering.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. A sermon's "
    "lemma usually quotes the whole passage it preaches on (e.g. fifteen verses), and the "
    "homily then works through it, so do NOT simply file a sermon under the full range of its "
    "label. Break it up wherever the exposition moves from one verse to the next: e.g. if a "
    "stretch comments on 7:44, insert it in 7:44, not in 7:36-50. It's ok to use a range if "
    "necessary to avoid breaking up a coherent thought/piece (Cyril often expounds several "
    "verses as one argument), just prefer smaller ranges/individual verses. When you split a "
    "section, its pieces together must still contain the WHOLE of it, every word -- and you "
    "split ONLY by cutting the text into consecutive stretches: each block must be one "
    "continuous stretch of Cyril, in his order. Never cut up or move the lemma: when a lemma "
    "quotes several verses, that whole quotation stays, uncut, at the start of the first block "
    "from it. Do NOT duplicate the same stretch of commentary across several {book} verses -- "
    "put it ONCE, at its smallest accurate verse/range.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the within-{book} duplication "
    "forbidden above). Cyril constantly quotes and expounds other Scripture. Whenever a "
    "stretch genuinely QUOTES AND EXPOUNDS a specific verse from another book -- a Psalm or "
    "other OT verse, another Gospel's own wording, or an Epistle passage -- you may ALSO file "
    "that portion under that verse in its own file (e.g. \"Isaiah 53_5\", \"Hebrews 4_15\"), "
    "in addition to its {book} placement. File a cross-parallel only where Cyril genuinely "
    "expounds the passage, not for a passing mention or a bare one-line proof-text, and NOT "
    "merely because the {book} passage has a parallel in Matthew or Mark. Use KJV book/verse "
    "numbering for the target file.\n\n"
    "NON-VERSE SECTIONS. A sermon heading with no verse label after it (a sermon that "
    "continues the previous one's passage, or catena fragments without a label) still holds "
    "commentary: the notes above say where each goes. Rubrics and colophons are not Cyril's "
    "commentary; leave them out.\n\n"
    "THE TEXT. Copy Cyril's words VERBATIM -- nothing abridged, paraphrased, corrected, added "
    "or rearranged -- and keep the lemma where it stands in the source. Drop the html tags "
    "(italics simply become plain text; don't turn them into quotation marks) and separate "
    "paragraphs with a single blank line. Leave out the <h2> headings and the translator's "
    "verse labels (\"7:36-50.\", \"cc. 2:21-24.\", \"Luke ii. 1.\"): a block starts with the "
    "lemma's own words (\"And a certain Pharisee desired Him to eat with him.\"). Don't add "
    "headings, verse numbers or notes of your own. Don't write a python script to do this; "
    "process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- the whole work sits behind one page).\n\n"
    "EXISTING BLOCKS. The old imports of this work (excerpts under several urls and titles) "
    "have ALREADY been deleted, so you are only ADDING: if a verse file exists, append your "
    "[[commentary]] after its existing blocks; otherwise create it. Blocks from other works "
    "must be left exactly as they are."
)

PROMPT2 = "Double check, was this fully imported properly?"


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    return PROMPT1_TEMPLATE.format(
        title=work["source_title"],
        units_dir=units_dir,
        first_unit=units[0]["name"],
        last_unit=units[-1]["name"],
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        book=work["book"],
        father=FATHER,
        unit_name=unit["name"],
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
    )


# --- Deterministic post-import check ------------------------------------------

OLD_RESIDUE_RE = re.compile(r"\((?:Chap\.|Chapter \d|Vers?\.|Verses? \d)")
PROBE_WORDS = 8
# Scribal rubrics the prompt tells the agent to leave out; not counted as missing.
RUBRIC_RE = re.compile(r"^HERE (?:BEGINS|ENDS)\b")


def _norm(s):
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip()


def run_check(work, sections):
    """Return a list of problems (empty == all good). Prints a summary."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    url = source_url_for(work)
    book = work["book"]
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        books = json.load(f)["canonical_names"]
    filename_re = re.compile(
        "(" + "|".join(map(re.escape, books)) + r") \d+_\d+(?:-\d+(?:_\d+)?)?\.toml"
    )
    problems, quotes, files_used, cross, contiguity = [], [], 0, [], []
    source = _norm(" ".join(" ".join(paragraphs_of(s)) for s in sections))
    # "(Verse 11)"-style references that the source itself contains are not residue.
    genuine = set(OLD_RESIDUE_RE.findall(source))

    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        path = os.path.join(folder, fn)
        own_book = fn.startswith(book + " ")
        if not own_book:
            # Cross-book parallels: only files that mention this work's url.
            with open(path, encoding="utf-8") as f:
                if url not in f.read():
                    continue
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{fn}: TOML parse error: {exc}")
            continue
        mine = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        if not mine:
            continue
        if not filename_re.fullmatch(fn):
            problems.append(f"{fn}: filename is not '<Book> C_V' / 'C_V-V' / 'C_V-C_V'")
        if own_book:
            files_used += 1
        else:
            cross.append(fn[:-5])
        for c in mine:
            q = c.get("quote", "")
            contiguity.append((fn, q))
            # Coverage is judged on the commented book's own files only.
            if own_book:
                quotes.append(q)
            if c.get("source_title") != work["source_title"]:
                problems.append(f"{fn}: wrong source_title {c.get('source_title')!r}")
            if any(r not in genuine for r in OLD_RESIDUE_RE.findall(q)):
                problems.append(f"{fn}: old-translation residue in a block")
            if re.search(r"</?i>", q):
                problems.append(f"{fn}: leftover html tag in a block")

    for stale in work.get("stale_files", []):
        if os.path.exists(os.path.join(folder, stale + ".toml")):
            problems.append(f"{stale}.toml: stale old-translation file still exists")

    for fn, q in contiguity:
        if _norm(q) not in source:
            problems.append(
                f"{fn}: block is not one continuous stretch of the source (text cut up, "
                f"rearranged or altered): {_norm(q)[:80]!r}"
            )

    haystack = _norm(" ".join(quotes))
    probed = 0
    for s in sections:
        for i, p in enumerate(paragraphs_of(s), 1):
            if RUBRIC_RE.match(p):
                continue
            words = _norm(p).split(" ")
            for label, probe in (("start", words[:PROBE_WORDS]), ("end", words[-PROBE_WORDS:])):
                probed += 1
                if " ".join(probe) not in haystack:
                    problems.append(
                        f"section {s['heading']!r} paragraph {i} {label} not found: "
                        f"{' '.join(probe)!r}"
                    )

    print(f"\nCHECK: {len(quotes)} block(s) of this work in {files_used} {book} file(s); "
          f"{probed} paragraph probes")
    print(f"Cross-book parallels ({len(cross)}): {', '.join(cross) or 'none'}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        print("(A non-verse section the agent deliberately skipped will show up as "
              "'not found' -- confirm in the log that it was skipped on purpose.)")
    else:
        print("CHECK PASSED")
    return problems


# --- Live rendering of stream-json events -------------------------------------


def _truncate(text, limit=500):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " …"


def render_event(event):
    """Print a human-readable line for one stream-json event, live."""
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        model = event.get("model", "?")
        print(f"    · session start (model={model})")

    elif etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                print(f"    💬 {_truncate(block['text'])}")
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                hint = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                hint = f" {_truncate(str(hint), 160)}" if hint else ""
                print(f"    🔧 {name}{hint}")

    elif etype == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                flag = " [error]" if block.get("is_error") else ""
                print(f"    ↳ result{flag}: {_truncate(str(content), 200)}")

    elif etype == "result":
        if event.get("subtype") != "success":
            print(f"    ⚠ result subtype={event.get('subtype')}")


# --- One claude call ----------------------------------------------------------


def is_rate_limit_error(stderr):
    lower = stderr.lower()
    return any(
        term in lower
        for term in ["rate limit", "rate_limit", "overloaded", "too many requests", "529"]
    )


def call_claude(prompt, events_log, tag, resume_session=None):
    """Run one headless claude invocation, streaming stream-json events.

    Returns (final_text, session_id). Every raw event line is persisted to
    events_log tagged with `tag` (e.g. "Part003_Ch02a/prompt1"). When resume_session
    is given, the call continues that conversation via --resume."""
    delays = RETRY_DELAYS
    for attempt in range(len(delays) + 1):
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if resume_session:
            cmd += ["--resume", resume_session]
        cmd += ["--output-format", "stream-json", "--verbose", prompt]

        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        final_text = ""
        session_id = resume_session
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events_log.write(
                json.dumps({"tag": tag, "attempt": attempt + 1, "event": event}) + "\n"
            )
            events_log.flush()
            if event.get("session_id"):
                session_id = event["session_id"]
            render_event(event)
            if event.get("type") == "result" and "result" in event:
                final_text = event["result"]

        proc.wait()
        stderr = proc.stderr.read()

        if proc.returncode == 0:
            return final_text.strip(), session_id

        if is_rate_limit_error(stderr):
            delays = RATE_LIMIT_DELAYS

        if attempt < len(delays):
            wait = delays[attempt]
            print(
                f"    Retry {attempt + 1}/{len(delays)} after {wait}s... "
                f"(rc={proc.returncode} stderr={stderr.strip()[:80]})"
            )
            time.sleep(wait)
        else:
            msg = (
                f"rc={proc.returncode} stderr={stderr.strip()[:200]} "
                f"final={final_text.strip()[:200]}"
            )
            raise RuntimeError(f"claude call failed after retries: {msg}")

    raise RuntimeError("Unreachable")


# --- Driver -------------------------------------------------------------------


def log_record(log, unit, prompt_no, started, ended, session_id, output):
    log.write(
        json.dumps(
            {
                "unit": unit["name"],
                "sections": [s["heading"] for s in unit["sections"]],
                "prompt": prompt_no,
                "timestamp": started.isoformat(),
                "duration_seconds": round((ended - started).total_seconds(), 1),
                "session_id": session_id,
                "output": output,
            }
        )
        + "\n"
    )
    log.flush()


def process_unit(work, units_dir, units, unit, log, events_log):
    """Run prompt 1 (import) then prompt 2 (self-review) in one conversation."""
    print(f"\n{'=' * 60}")
    print(f"{unit['name']}: {', '.join(s['heading'] for s in unit['sections'])}")
    print(f"{'=' * 60}")
    tag = unit["name"].removesuffix(".html")

    print("  [prompt 1] importing...")
    started = datetime.now()
    out1, session_id = call_claude(
        build_prompt1(work, units_dir, units, unit), events_log, tag=f"{tag}/prompt1"
    )
    ended = datetime.now()
    log_record(log, unit, 1, started, ended, session_id, out1)
    print(f"  [prompt 1] done ({round((ended - started).total_seconds(), 1)}s)"
          f" -- session {session_id}")
    print(f"  {_truncate(out1, 300)}")

    if not session_id:
        print("  WARNING: no session_id captured from prompt 1; prompt 2 would "
              "start a fresh conversation. Skipping prompt 2 for this piece.")
        return

    print("  [prompt 2] double-checking...")
    started = datetime.now()
    out2, _ = call_claude(
        PROMPT2, events_log, tag=f"{tag}/prompt2", resume_session=session_id
    )
    ended = datetime.now()
    log_record(log, unit, 2, started, ended, session_id, out2)
    print(f"  [prompt 2] done ({round((ended - started).total_seconds(), 1)}s)")
    print(f"  {_truncate(out2, 300)}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("work", choices=sorted(WORKS), help="Which commentary to import.")
    parser.add_argument(
        "single", nargs="?",
        help="Process ONE piece (e.g. Part002_Ch02.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_Ch01.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part020_Ch12.html); combine with --start-after "
             "to run a chunk.",
    )
    parser.add_argument(
        "--split-chars", type=int, default=SPLIT_CHARS,
        help=f"Cut chapters bigger than this many html chars (default {SPLIT_CHARS}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folder and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true", help="Run only the check.")
    args = parser.parse_args()
    if args.single and (args.start_after or args.through):
        parser.error("give a single piece or --start-after/--through, not both")

    work = WORKS[args.work]
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        if work["book"] not in json.load(f)["canonical_names"]:
            raise SystemExit(f"Book {work['book']!r} is not in book_names.json")
    preamble, sections = load_work(work)
    units = make_units(preamble, sections, args.split_chars)
    units_dir = units_dir_for(args.work)
    names = [u["name"] for u in units]

    print(f"Work:       {FATHER}, {work['source_title']}")
    print(f"Source:     {os.path.join(WRITINGS_DIR, work['html'])}")
    print(f"Source url: {source_url_for(work)}")
    print(f"Units dir:  {units_dir}")
    print(f"Agent cwd:  {PROJECT_DIR}")

    if args.check:
        sys.exit(1 if run_check(work, sections) else 0)

    print(f"\n{len(sections)} section(s) -> {len(units)} piece(s) "
          f"(chapters over {args.split_chars} chars cut):")
    for u in units:
        size = sum(len(s["html"]) for s in u["sections"])  # excl. the repeated preamble
        print(f"  {u['name']:<22} {size:>7} chars  "
              f"{', '.join(s['heading'] for s in u['sections'])}")

    if args.single:
        if args.single not in names:
            raise SystemExit(f"No piece named {args.single!r}")
        todo = [u for u in units if u["name"] == args.single]
    else:
        first, last = 0, len(units)
        if args.start_after:
            if args.start_after not in names:
                raise SystemExit(f"No piece named {args.start_after!r}")
            first = names.index(args.start_after) + 1
        if args.through:
            if args.through not in names:
                raise SystemExit(f"No piece named {args.through!r}")
            last = names.index(args.through) + 1
        todo = units[first:last]
    if not todo:
        print("Nothing to do.")
        return

    if args.dry_run:
        print(f"\n--dry-run: prompt 1 for {todo[0]['name']}:\n")
        print(build_prompt1(work, units_dir, units, todo[0]))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    write_units(args.work, preamble, units)
    print(f"\nWrote {len(units)} piece(s) to {units_dir}")
    if args.split_only:
        return

    log_dir = os.path.join(WORK_DIR, f"cyril_{args.work.lower()}_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for unit in todo:
            try:
                process_unit(work, units_dir, units, unit, log, events_log)
            except RuntimeError as exc:
                print(f"  ABORTING at {unit['name']}: {exc}")
                print(f"  (pieces kept in {units_dir})")
                log.write(json.dumps({"unit": unit["name"], "error": str(exc)}) + "\n")
                log.flush()
                sys.exit(1)

    shutil.rmtree(units_dir)
    print(f"\nDone. {len(todo)} piece(s) processed; removed {units_dir}")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")

    # A full or resumed run ends on the last piece, so the whole work should be in place.
    if not args.single and todo[-1] is units[-1]:
        run_check(work, sections)


if __name__ == "__main__":
    main()
