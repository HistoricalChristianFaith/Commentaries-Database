#!/usr/bin/env python3
"""Import the Scripture commentary in Augustine's Treatise on Grace and Free Will (De gratia et
libero arbitrio, in P. Holmes and R. E. Wallis's public-domain translation, revised by B. B.
Warfield, NPNF1 vol. 5, 1887), with the two letters to Valentinus printed with it, into the
Commentaries-Database, one piece at a time, by driving a headless ``claude`` agent.

A per-father copy of process_novatian_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting, logs and --check; Augustine's other
importers (Tractates, Psalms, Propositions on Romans, Harmony) each serve one work of their own
layout. The treatise is not a verse-by-verse commentary but an anti-Pelagian work proving from
Scripture both free will and grace, so the import is SELECTIVE (WORKS "selective": True): the
agents read every section and file only the stretches that genuinely expound a verse.

    Writings-Database/Augustine of Hippo/A Treatise on Grace and Free Will.html

    <h1>A Treatise on Grace and Free Will</h1>
    <h2>Addressed to Valentinus ...</h2>                      (empty: dropped)
    <h2>Extract from Augustin's "Retractations," ...</h2> ...  (dropped, the user's choice)
    <h2>Two Letters Written by Augustin to Valentinus ...</h2> (empty: dropped)
    <h2>Letter I.</h2> [<i>The 214th of Augustin's Epistles.</i>] <i>salutation</i>
        1. ... 2. ...                                (NPNF's numbers at paragraph starts)
    <h2>Letter II.</h2> ... 8. ... <i>In this treatise Augustin teaches ...</i>  (editor's summary)
    <h2>Chapter 41 [XX.]—The Wills of Men are ...</h2> ...     (NPNF's section 41, chapter XX)
    <section class="notes"> ...                                 (321 notes, mostly Scripture refs)

``load_work`` gives one section per letter section ("Letter 1, Section 2"; the salutation opens
Section 1; the bracketed epistle number is heading matter; the number is dropped from the body
and shown to the agent as an <h2>) and one per treatise heading ("Chapter 41"; the Arabic number
is NPNF's section number, which the headings call "Chapter" and the titles use; the bracketed
Roman chapter is ignored). The editor's italic summary of the treatise at the end of Letter II is
dropped. The footnotes are shown inline as ``<sup>[note: ...]</sup>`` hints and dropped from the
body (the text imported and checked).

Section keys (``chapter_no``): treatise chapters 1-46, Letter I's sections 1001-1007, Letter
II's 2001-2008.

    python3 process_augustine_grace_commentary.py GraceFreeWill --dry-run
    python3 process_augustine_grace_commentary.py GraceFreeWill --split-only
    python3 process_augustine_grace_commentary.py GraceFreeWill Part002_Ch01-08.html
    python3 process_augustine_grace_commentary.py GraceFreeWill --check
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
import unicodedata
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

FATHER = "Augustine of Hippo"

# A piece holds consecutive chapters up to about this many html chars.
SPLIT_CHARS = 25000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# Letter sections' keys: LETTER_BASE * letter + section.
LETTER_BASE = 1000

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "GraceFreeWill": {
        "html": "Augustine of Hippo/A Treatise on Grace and Free Will.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        # "On Grace and Free Will, Chapter 41" / "..., Chapters 41-42" / "..., Letter 1,
        # Section 2" (the user's choice; the old url'd blocks had "ON GRACE AND FREE WILL 39").
        "source_title": "On Grace and Free Will",
        "notes": (
            "The treatise's headings read \"Chapter 41 [XX.]\": the Arabic number is NPNF's "
            "section number (1-46) and is the one for source_title; the bracketed Roman number is "
            "the older chapter division and is ignored. The notes also hold the editors' remarks "
            "(on Adrumetum, the Latin \"Caritatem vestram\", Warfield's bracketed notes ending "
            "\"—W.\", \"Compare Art. X. of the Church of England.\", cross-references to "
            "Augustine's other works such as \"Ep. 194.\"): these are not Scripture. Augustine "
            "quotes an Old Latin Bible, often following the Septuagint, so his wording can be far "
            "from the KJV's: match by SENSE. \"The will is prepared by the Lord\" is Proverbs 8:35 "
            "in the Septuagint; God's \"wisdom carries law and mercy upon her tongue\" is Proverbs "
            "3:16 in the Septuagint; \"For He who gave the law will give blessings\" is Psalms "
            "84:6; \"Give no heed to a worthless woman\" is Proverbs 5:2; \"Who is this that cometh "
            "up in white raiment, leaning upon her kinsman?\" is Song of Solomon 8:5; \"Ecclus.\" "
            "is Sirach (\"Say not thou, It is through the Lord that I fell away\" is Sirach "
            "15:11-17). The Esther passage in Chapter 42 (\"He looked at her like a bull in the "
            "vehemence of his indignation\", note \"Esther v. (according to the Sept.)\") is the "
            "Greek addition, filed in KJV Apocrypha numbering as Esther 15_7-8 (the lookup's "
            "Greek Esther table numbers it 15:10-11). In Letter II, Section 5 \"Make straight "
            "paths for thy feet, and order thy ways aright\" is Proverbs 4:26-27, whose Septuagint "
            "adds \"for the Lord knoweth the ways on the right hand, but those on the left are "
            "perverse. He will make thy ways straight, and will direct thy steps in peace\" (not in "
            "the KJV: file that exposition under Proverbs 4_26-27). Some notes are misprinted "
            "(kept as printed in the source), so always confirm by the WORDING: in Letter I, "
            "Section 1 \"See Matt. xvi. 17, and Rom. ii. 6.\" on \"render to every man according "
            "to his works\" is Matthew 16:27 and Romans 2:6; in Chapter 4 \"Rom. xii. 1.\" on "
            "\"Be not overcome of evil\" is Romans 12:21; in Chapter 5 \"Ps. lxix. 6.\" on \"Pour "
            "out Thy wrath upon the heathen that have not known Thee\" is Psalms 79:6; in Chapter "
            "20 \"Ps. li. 12.\" on \"Create in me a clean heart, O God\" is Psalms 51:10; in "
            "Chapter 39 \"John i. 5.\" on \"From God the Father,\" says he immediately afterwards, "
            "\"and the Lord Jesus Christ.\" is Ephesians 6:23, continuing the quotation before it. "
            "The notes' Psalm numbers are otherwise the English (KJV) ones. Most sections are one "
            "or two long paragraphs, so cut between sentences. Much of the treatise is chains of "
            "proof-texts (the commands of Chapter 4, \"Be not overcome of evil,\" and, \"Be not "
            "like a horse or a mule ...\" and, \"Reject not the counsels of thy mother;\" ...): a "
            "verse in such a chain with no more said about it is a proof-text. Where Augustine "
            "stops on a verse (why Paul says \"I have obtained mercy that I might be faithful\", "
            "what \"grace for grace\" means, how \"I will take away from you your heart of stone\" "
            "answers the Pelagians, how God hardened Pharaoh while Pharaoh hardened himself), "
            "that is commentary on it. In Chapters 41-43 he goes through Scripture narratives "
            "showing God turning men's wills (Absalom and the counsel of Ahithophel, Shimei's "
            "cursing, Rehoboam, Amaziah, the Canaanites hardened against Joshua, the Philistines "
            "and Arabians stirred against Jehoram, Esther's king): where he draws out how God "
            "worked in that will, the stretch is commentary on that narrative's verse(s), each "
            "under its own; a bare listing is not."
        ),
    },
}


def _raw_notes(work):
    """The notes of a work's file, in printed order (the text of each)."""
    with open(os.path.join(WRITINGS_DIR, work["html"]), encoding="utf-8") as f:
        m = NOTES_RE.search(f.read())
    return [_clean(t) for _, t in NOTE_RE.findall(m.group(1))] if m else []


def note_hints(work, markers):
    """{marker number: note text} for the hint of each footnote marker."""
    notes = _raw_notes(work)
    return {n: notes[n - 1] for n in markers if n <= len(notes)}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing url'd blocks ("file=Augustine%2520of%2520Hippo%2FA%2520Treatise%2520on...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"augustine_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
# A treatise heading: "Chapter 41 [XX.]—The Wills of Men ..." or "Chapter 3.—Sinners are ...".
CHAPTER_RE = re.compile(r"Chapter (\d+)(?: \[[IVXL]+\.\])?\.?—.*", re.S)
LETTER_RE = re.compile(r"Letter (I|II)\.")
# <h2>s with nothing of Augustine's under them to import (the user's choice for the extract).
DROP_H2 = ("Addressed to Valentinus", "Extract from Augustin's", "Two Letters Written")
# Letter heading matter: the bracketed epistle number.
EPISTLE_NO_RE = re.compile(r"\A\s*\[<i>The 21[45]th of Augustin's Epistles\.</i>\]<br/><br/>\n")
# NPNF's section number opening a letter paragraph ("\n2. ").
LETTER_NO_RE = re.compile(r"(?:\A|(?<=<br/><br/>\n))(\d+)\. ")
# The old chapter division's one mark inside a section (Chapter III begins mid-section 5,
# "... than they who know it. [III.] It is seemingly worse ..."): dropped; the agents drop it.
INLINE_CHAPTER_RE = re.compile(r" \[III\.\](?= )")
# The editor's italic summary of the treatise at the end of Letter II.
SUMMARY_RE = re.compile(r"<i>In this treatise Augustin teaches us .*?</i><br/><br/>\n", re.S)


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _label(no):
    if no >= LETTER_BASE:
        return ("letter", no // LETTER_BASE, no % LETTER_BASE)
    return ("chapter", None, no)


def chapter_title(work, chapters):
    """The source_title for a block from these section keys: "On Grace and Free Will, Chapter
    7", "..., Chapters 7-8", "..., Letter 1, Section 2", "..., Letter 2, Sections 5-6"."""
    t = work["source_title"]
    labels = [_label(n) for n in chapters]
    kinds = {(k, l) for k, l, _ in labels}
    if len(kinds) != 1:
        return f"{t}, (block crosses a letter/treatise boundary)"
    kind, letter = kinds.pop()
    a, b = min(x for *_, x in labels), max(x for *_, x in labels)
    if kind == "letter":
        return (f"{t}, Letter {letter}, Section {a}" if a == b
                else f"{t}, Letter {letter}, Sections {a}-{b}")
    return f"{t}, Chapter {a}" if a == b else f"{t}, Chapters {a}-{b}"


def load_work(work):
    """Return (preamble_html, sections) in source order: Letter I's and Letter II's sections,
    then the treatise's 46 chapters. A section's html is what the agent sees (an <h2> naming
    it, the text, the footnotes inline as [note: ...] hints), its body the text without heading
    and notes, `chapter` None (there are no verse sections) and `chapter_no` its key."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(text)])

    def hinted(s):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""),
            s)

    parts = H2_RE.split(text)
    preamble = hinted(parts[0])
    sections = []
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        raw = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        title = _clean(FOOTNOTE_REF_RE.sub("", h2))
        if title.startswith(DROP_H2):
            continue
        lm = LETTER_RE.fullmatch(title)
        if lm:
            letter = len(lm.group(1))
            em = EPISTLE_NO_RE.match(raw)
            if not em:
                raise SystemExit(f"{work['html']}: Letter {letter} lacks its epistle number")
            head, raw = em.group(0), raw[em.end():]
            if letter == 2:
                raw, k = SUMMARY_RE.subn("", raw)
                if k != 1:
                    raise SystemExit(f"{work['html']}: the editor's summary not found once")
            cuts = list(LETTER_NO_RE.finditer(raw))
            nos = [int(c.group(1)) for c in cuts]
            if nos != list(range(1, len(nos) + 1)):
                raise SystemExit(f"{work['html']}: Letter {letter} sections are {nos}")
            for j, c in enumerate(cuts):
                # Section 1 opens with the salutation before "1.".
                start = 0 if j == 0 else c.start()
                end = cuts[j + 1].start() if j + 1 < len(cuts) else len(raw)
                piece = raw[start:c.start()] + raw[c.end():end]
                piece = piece.rstrip() + "\n"
                sec_h2 = f"<h2>Letter {letter}, Section {c.group(1)}.</h2>\n"
                sections.append({
                    "heading": f"Letter {letter}, Section {c.group(1)}",
                    "chapter": None,
                    "chapter_no": LETTER_BASE * letter + int(c.group(1)),
                    "html": (hinted(h2) + "\n" + hinted(head) if j == 0 else "")
                            + sec_h2 + hinted(piece),
                    "body": FOOTNOTE_REF_RE.sub("", piece),
                })
            continue
        cm = CHAPTER_RE.fullmatch(title)
        if not cm:
            raise SystemExit(f"{work['html']}: unexpected <h2>: {h2}")
        no = int(cm.group(1))
        if no == 5:
            raw, k = INLINE_CHAPTER_RE.subn("", raw)
            if k != 1:
                raise SystemExit(f"{work['html']}: Chapter 5's inline [III.] not found once")
        sections.append({
            "heading": f"Chapter {no}",
            "chapter": None,
            "chapter_no": no,
            "html": hinted(h2) + "\n" + hinted(raw),
            "body": FOOTNOTE_REF_RE.sub("", raw),
        })
    nos = [s["chapter_no"] for s in sections if s["chapter_no"] < LETTER_BASE]
    if nos != list(range(1, 47)):
        raise SystemExit(f"{work['html']}: chapters are not numbered 1..46: {nos}")
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in re.split(r"(?:<br\s*/?>\s*){2,}", section["body"]):
        p = _clean(p)
        if p:
            out.append(p)
    return out


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
    """The ordered list of pieces: {name, chapter, sections}. The two letters make the first
    piece(s) ("Part001_Letters.html"); the treatise's chapters are cut into runs of whole
    chapters, named by their first and last chapter."""
    letters = [s for s in sections if s["chapter_no"] >= LETTER_BASE]
    chapters = [s for s in sections if s["chapter_no"] < LETTER_BASE]
    units = []
    runs = split_evenly(letters, cap) if letters else []
    for k, run in enumerate(runs):
        suffix = "" if len(runs) == 1 else chr(ord("a") + k)
        units.append({"name": f"Part{len(units) + 1:03d}_Letters{suffix}.html",
                      "chapter": None, "sections": run})
    for run in split_evenly(chapters, cap):
        a, b = run[0]["chapter_no"], run[-1]["chapter_no"]
        units.append({
            "name": f"Part{len(units) + 1:03d}_Ch{a:02d}-{b:02d}.html",
            "chapter": None,
            "sections": run,
        })
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
    "We have Augustine's Treatise on Grace and Free Will (De gratia et libero arbitrio, 426-427) "
    "here, with the two letters to Valentinus that were sent with it: "
    "\"{units_dir}/{first_unit}\" with the files continuing up to \"{units_dir}/{last_unit}\". "
    "These are consecutive pieces cut, in order, from our PUBLIC-DOMAIN English translation of "
    "the work (Holmes and Wallis's, revised by Warfield, Nicene and Post-Nicene Fathers, first "
    "series, vol. 5, 1887), \"{html_path}\" (consult it if you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. Augustine wrote it for the monks of Adrumetum, "
    "some of whom so defended grace as to deny free will. The two letters (Augustine's Epistles "
    "214 and 215 to Valentinus, the abbot) explain why he wrote and warn against both errors. "
    "The treatise, in 46 numbered sections, proves first from Scripture that man has free will "
    "(1-5), then against the Pelagians that grace is necessary and is not given according to "
    "merit (6-20); that grace is neither the law, nor nature, nor only the forgiveness of sins "
    "(21-27); that faith, the good will, and love are God's gifts (28-40); that God turns men's "
    "wills as He pleases, to good by mercy and to evil by just judgment (41-43); and that grace "
    "is gratuitous, as infants show (44-46). Augustine argues from Scripture throughout, quoting "
    "and expounding it constantly. Your task is to EXTRACT from the piece the stretches that are "
    "genuinely commentary on a specific verse of Scripture, and file each under that verse in "
    "the \"{father}/\" folder. Much of the text will NOT be imported, and that is expected: a "
    "section with no exposition of a verse gives no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the work's title at the top; that is background "
    "for you, not text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Augustine QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words, "
    "resolves a difficulty in it (how a command can be given if grace must give what it "
    "commands), builds his argument on its wording (why it says \"I have obtained mercy to be "
    "faithful\" and not \"because I was faithful\"), applies it to free will or grace in a way "
    "that shows how he reads it, or answers the Pelagians' reading of it. Do NOT import a verse "
    "quoted only in passing, a bare proof-text dropped into a sentence, a chain of proof-texts "
    "quoted without comment, or teaching that merely mentions Scripture. Ask: would a reader "
    "studying this verse learn something about how Augustine understood or used it from this "
    "stretch? If so, import it; if it would only learn that Augustine quoted it, leave it out.\n\n"
    "VERSE KEYS. The footnotes are shown inline as \"[note: ...]\" in superscript, after the "
    "word they mark. Most give the reference of a quotation, abbreviated with Roman chapter "
    "numbers (\"John xv. 5.\" = John 15:5, \"Ps. xcv. 8.\", \"Ecclus. xv. 11-17.\"); "
    "others are the editors' remarks and give no verse. A note can sit on the wrong quotation, "
    "or be missing. Use the notes as HINTS only, and confirm every verse against the KJV "
    "wording with `" + KJV_LOOKUP + "`, filing under KJV book/chapter/verse numbering. "
    "Deuterocanonical books are fine (\"Sirach\", \"Wisdom\", \"Baruch\", ...): use only the "
    "book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Augustine's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse and the whole of his exposition of it. Don't pad a "
    "block with unrelated argument before or after the exposition. File it under the SMALLEST "
    "verse range the exposition really addresses: a single verse when it expounds one verse, a "
    "range only when it expounds several verses as one argument (a range crossing chapters is "
    "written like \"Romans 7_25-8_2\"). When one stretch genuinely expounds two different "
    "passages (e.g. two verses set against each other and reconciled), file the same text under "
    "each, as separate files; that is welcome. But never put two overlapping blocks of this "
    "work in the SAME file, and don't split one exposition into fragments under one verse.\n\n"
    "THE TEXT. Copy Augustine's words VERBATIM: nothing abridged, paraphrased, corrected, added "
    "or rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Leave out the \"[note: "
    "...]\" footnotes and the <h2> headings (a section's number and the editor's title, e.g. "
    "\"Chapter 41 [XX.]—The Wills of Men are So Much in the Power of God ...\", or \"Letter 1, "
    "Section 2.\", are a heading, not text), and in the letters the bracketed epistle number "
    "(\"[The 214th of Augustin's Epistles.]\"). Keep the printed text's quotation marks, dashes, "
    "bracketed words and misprints as they are. Don't add headings, verse numbers or notes of "
    "your own. Don't write a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"  (a block from the treatise)\n"
    "  source_title = \"{source_title}, Letter L, Section N\"  (a block from a letter)\n"
    "where, in the treatise, N is the ARABIC number in the heading (\"{source_title}, Chapter "
    "41\" for a block from \"Chapter 41 [XX.]\"; ignore the bracketed Roman number), and a block "
    "running across headings is \"{source_title}, Chapters 41-42\"; in the letters, L is 1 or 2 "
    "and N the section (\"{source_title}, Letter 2, Section 5\", or \"..., Letter 2, Sections "
    "5-6\" for a block crossing sections). A block never runs from a letter into the treatise.\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are only "
    "ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it (with no blank line before its first [[commentary]]). Earlier pieces "
    "of THIS run may already have left blocks from On Grace and Free Will in the files you "
    "write to: they are NOT old imports or duplicates; leave them exactly as they are and "
    "append yours after them. Blocks from Augustine's other works (the Tractates on John, the "
    "Expositions on the Psalms, On the Spirit and the Letter, On Rebuke and Grace, the City of "
    "God, the letters, and many excerpts with no source_url, some titled from De libero "
    "arbitrio as \"ON FREE WILL ...\") must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- section, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    return PROMPT1_TEMPLATE.format(
        units_dir=units_dir,
        first_unit=units[0]["name"],
        last_unit=units[-1]["name"],
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        father=FATHER,
        unit_name=unit["name"],
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
    # NFC: accented Greek can come in oxia forms (U+1F73 "έ"), which an agent copying it may
    # write as the identical-looking tonos form (U+03AD); neither should fail the check.
    s = unicodedata.normalize("NFC", s)
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip()


def source_offsets(sections):
    """(normalised source text, [(start, end, chapter_no)] per section)."""
    parts = [_norm(" ".join(paragraphs_of(s))) for s in sections]
    source = " ".join(parts)
    offs, pos = [], 0
    for s, p in zip(sections, parts):
        offs.append((pos, pos + len(p), s["chapter_no"]))
        pos += len(p) + 1
    return source, offs


def chapters_spanned(offs, a, e):
    return [no for x, y, no in offs if x < e and y > a]


def run_check(work, sections):
    """Return a list of problems (empty == all good). Prints a summary. A selective import
    has no coverage to check: this checks that every block of this book is one verbatim
    stretch of it, found once, under a valid filename, with the right source_title."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    url = source_url_for(work)
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        books = json.load(f)["canonical_names"]
    filename_re = re.compile(
        "(" + "|".join(map(re.escape, books)) + r") \d+_\d+(?:-\d+(?:_\d+)?)?\.toml"
    )
    source, offs = source_offsets(sections)
    problems, n, files, per_chapter = [], 0, set(), {}

    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if url not in text:
            continue
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{fn}: TOML parse error: {exc}")
            continue
        mine = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        if not mine:
            continue
        files.add(fn)
        # (The agents of the Athanasius run created 42 files opening with a blank line.)
        if text.startswith("\n"):
            problems.append(f"{fn}: file starts with a blank line")
        if not filename_re.fullmatch(fn):
            problems.append(f"{fn}: filename is not '<Book> C_V' / 'C_V-V' / 'C_V-C_V'")
        spans = []
        for c in mine:
            n += 1
            q = _norm(c.get("quote", ""))
            if re.search(r"</?[a-z]+>|\[note:", q):
                problems.append(f"{fn}: leftover html tag or [note: ...] in a block")
            hits = [m.start() for m in re.finditer(re.escape(q), source)] if q else []
            if not hits:
                problems.append(f"{fn}: block is not one continuous stretch of the source "
                                f"(text cut up, rearranged or altered): {q[:80]!r}")
                continue
            if len(hits) > 1:
                problems.append(f"{fn}: block matches the source {len(hits)} times: {q[:60]!r}")
            a, e = hits[0], hits[0] + len(q)
            spans.append((a, e))
            chs = chapters_spanned(offs, a, e)
            want = chapter_title(work, chs)
            if c.get("source_title") != want:
                problems.append(f"{fn}: source_title {c.get('source_title')!r}, the text is "
                                f"{want!r}")
            for no in chs:
                per_chapter.setdefault(no, []).append(fn[:-5])
        spans.sort()
        for (a1, e1), (a2, e2) in zip(spans, spans[1:]):
            if a2 < e1:
                problems.append(f"{fn}: two blocks of this work overlap in one file")

    print(f"\nCHECK: {n} block(s) of this work in {len(files)} file(s); "
          f"{len(per_chapter)} of {len(sections)} sections used")
    heads = {s["chapter_no"]: s["heading"] for s in sections}
    for no in sorted(per_chapter):
        print(f"  {heads[no]}: {', '.join(per_chapter[no])}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
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
    parser.add_argument("work", choices=sorted(WORKS), help="Which work to import.")
    parser.add_argument(
        "single", nargs="?",
        help="Process ONE piece (e.g. Part002_Ch01-08.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_Ch01-08.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part002_Ch01-08.html); combine with --start-after "
             "to run a chunk.",
    )
    parser.add_argument(
        "--chapters", metavar="A-B",
        help="Run ONE ad-hoc piece of exactly chapters A..B (e.g. 1-14), instead of the usual "
             "pieces: for re-running a stretch when the usual split no longer matches the pieces "
             "already imported.",
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
    preamble, sections = load_work(work)
    units = make_units(preamble, sections, args.split_chars)
    if args.chapters:
        if args.single or args.start_after or args.through:
            parser.error("--chapters runs one piece of its own; give no other piece options")
        lo, hi = map(int, args.chapters.split("-"))
        run = [s for s in sections if lo <= s["chapter_no"] <= hi]
        if not run or run[0]["chapter_no"] != lo or run[-1]["chapter_no"] != hi:
            raise SystemExit(f"No chapters {args.chapters} in this work")
        units = [{"name": f"Part001_Ch{lo:02d}-{hi:02d}.html", "chapter": None, "sections": run}]
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
          f"(runs of chapters up to {args.split_chars} chars):")
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

    log_dir = os.path.join(WORK_DIR, f"augustine_{args.work.lower()}_import_logs")
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
