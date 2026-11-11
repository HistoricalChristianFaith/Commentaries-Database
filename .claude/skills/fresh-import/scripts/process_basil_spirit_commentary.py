#!/usr/bin/env python3
"""Import the Scripture commentary in Basil of Caesarea's treatise On the Spirit (De Spiritu
Sancto, in Blomfield Jackson's public-domain translation, NPNF2 vol. 8, 1895) into the
Commentaries-Database, one piece at a time, by driving a headless ``claude`` agent.

A copy of process_novatian_commentary.py (see ../SKILL.md, "Other fathers" and "Selective
works") with the same two-prompt flow, splitting, logs and --check; Basil's other importers are
built for the Longer Rules' Questions, the Letters and the Hexaemeron's homilies. The treatise is
not a verse-by-verse commentary but a defence of the doxology "with the Spirit" that argues from
Scripture throughout, so the import is SELECTIVE (WORKS "selective": True): the agents read
every chapter and file only the stretches that genuinely expound a verse; the rest is left out.

    Writings-Database/Basil of Caesarea/ON THE SPIRIT.html

    <h1>ON THE SPIRIT</h1>
    <h2>De Spiritu Sancto. </h2>                    (the title only: no text, ignored)
    <h2>Chapter XII</h2>                            (a chapter = one section)
    <i>Against those who assert ...</i><br/><br/>   (the editor's summary: a heading)
    28. Let no one be misled ...<sup><a href="#fn240" id="r240">240</a></sup> ...
    <section class="notes"><hr/><span id="fn1">... Luke xi. 10.</span> ...  (the notes)

``load_work`` gives one section per chapter (heading "Chapter XII. (= 12)"). The summary line
(the first paragraph after the <h2>, whatever its italics) is moved into the <h2> the agent sees
and left out of the body. The NPNF section numbers 1-79 opening paragraphs are dropped from the
pieces and the body (the user's choice); load_work requires them to run 1..79. The footnotes
give most of the Scripture references, so the html the agent sees carries each one inline, as
``<sup>[note: Luke xi. 10.]</sup>``, as a hint; the body (the text imported and checked) drops
them.

    python3 process_basil_spirit_commentary.py OnSpirit --dry-run
    python3 process_basil_spirit_commentary.py OnSpirit --split-only
    python3 process_basil_spirit_commentary.py OnSpirit Part002_Ch05-08.html
    python3 process_basil_spirit_commentary.py OnSpirit --check
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

FATHER = "Basil of Caesarea"

# A piece holds consecutive chapters up to about this many html chars.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "OnSpirit": {
        "html": "Basil of Caesarea/ON THE SPIRIT.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        # "On the Spirit, Chapter 12" / "..., Chapters 12-13" (the user's choice; the old url'd
        # blocks had "ON THE SPIRIT 11:27", "On The Holy Spirit, Chapter 12", the ACCS
        # excerpts "ON THE HOLY SPIRIT 8.18").
        "source_title": "On the Spirit",
        "notes": (
            "Jackson's notes also hold remarks that are NOT Scripture references: Greek words and "
            "readings (\"ἐν\", \"the Bodleian ms.\", \"The Benedictine text\"), parallels in "
            "Basil's other works (\"Hom.\", \"Ep.\") and in other writers "
            "(\"Aug.\", \"Euseb.\", \"Ath.\", Aristotle), and history. \"lxx.\" / \"LXX.\" "
            "marks the Septuagint's wording, \"R.V.\" / \"A.V.\" the English versions, and "
            "\"P.B.\" the Prayer Book Psalter, whose verse numbers can differ (in Chapter VI "
            "\"Ps. cxxxix. 7, P.B.\" on \"If I climb up into heaven thou art there; if I go down "
            "to hell thou art there also.\" is Psalms 139:8). The notes' Psalm numbers are "
            "otherwise the English (KJV) ones. Some of Jackson's references are misprinted (kept "
            "as printed in the source), so always confirm by the WORDING: in Chapter V \"Rom. xi. "
            "38.\" on \"Of him and through him and to him are all things.\" is Romans 11:36, "
            "\"1 John xvi. 15.\" on \"He shall take of mine, and shall shew it unto you.\" is "
            "John 16:15, and \"Ps. cvii. 13.\" on \"through (ἐν) God we shall do valiantly\" is "
            "Psalms 108:13 (the Septuagint's number); in Chapter VII \"Heb. i. 1.\" on \"the "
            "brightness\" is Hebrews 1:3; in Chapter VIII \"Eph. v. 29.\" on \"not having spot or "
            "wrinkle\" is Ephesians 5:27, and \"1 Cor. iv. 6, R.V. marg.\" on \"the illumination "
            "of knowledge\" is 2 Corinthians 4:6; in Chapter XV \"Ps. li. 9.\" on \"Thou shalt "
            "wash me, and I shall be whiter than snow.\" is Psalms 51:7; in Chapter XVI \"Ps. "
            "xiv. 4.\" on \"Who maketh his angels spirits and his ministers a flame of fire;\" is "
            "Psalms 104:4; in Chapter XVIII \"2 Cor. i. 12.\" on \"of God;\" is 1 Corinthians "
            "2:12; in Chapter XIX \"1 John i. 20.\" on \"He is called holy\" is 1 John 2:20, and "
            "\"Is. lxii. 14, LXX.\" on \"the Spirit came down from the Lord and guided them\" is "
            "Isaiah 63:14; in Chapter XXIV \"Ps. xxix. 12.\" on \"that my glory may sing praise to "
            "Thee\" is Psalms 30:12; in Chapter XXV \"2 Cor. xiii. 13.\" (the Greek verse number) "
            "is 2 Corinthians 13:14; in Chapter XXVI \"Gal. vi. 4.\" on \"cries in our hearts, "
            "Abba, Father,\" is Galatians 4:6; in Chapter XXX \"Ezek. xxiii. 5.\" on \"his "
            "enemy's beast of burden fallen under his load\" is Exodus 23:5. Septuagint wordings "
            "far from the KJV's: in Chapter I \"To the fool on his asking for wisdom, wisdom shall "
            "be reckoned\" is Proverbs 17:28 and \"the wise hearer\" with \"the admirable "
            "counsellor\" is Isaiah 3:3 (both applied to Amphilochius in passing); in Chapter XIX "
            "the Spirit \"called royal\" is Psalms 51:12 (the KJV's \"free spirit\"). The opening "
            "of Chapter I is Basil's address to Amphilochius; Chapter XXIX quotes earlier writers "
            "(Irenaeus, Eusebius, Origen, Africanus, the evening hymn, Gregory, Firmilian, "
            "Meletius) as witnesses to the word \"with\", and Chapter XXX describes the state of "
            "the Churches: expect little or nothing from them. Many chapters are a few long "
            "paragraphs, so cut between sentences. Much of the treatise turns on the prepositions "
            "of a verse (\"of\", \"through\", \"in\", \"with\", \"and\"): where Basil argues from "
            "how a verse is worded, that is commentary on that verse; a verse merely cited as one "
            "more instance of a preposition, in a list of such instances, is a proof-text."
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
    the other importers ("file=Basil%2520of%2520Caesarea%2FON%2520THE%2520SPIRIT.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"basil_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50}
# A chapter's heading: "Chapter XII" (the summary is the paragraph after it).
CHAPTER_RE = re.compile(r"Chapter ([IVXL]+)")
# The title <h2> before Chapter I, with no text under it.
TITLE_H2 = "De Spiritu Sancto."
# The editor's summary: everything up to the first paragraph break (Chapter VIII's has a
# non-italic stretch, "</i>Through whom<i>"; Chapter XII's italics are never closed; XVIII's and
# XXII's carry a note mark), then the first paragraph's NPNF section number.
SUMMARY_RE = re.compile(r"\s*(<i>.*?)<br\s*/?>\s*<br\s*/?>\s*", re.S)
# An NPNF section number opening a paragraph ("28. Let no one", "54.<sup>…</sup> Now").
SECNUM_RE = re.compile(r"(^|<br/><br/>\n?)\s*(\d+)\.(?=\s|<sup>)")


def roman(s):
    n = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN_VALUES[a]
        n += -v if ROMAN_VALUES.get(b, 0) > v else v
    return n


def _body(raw):
    return FOOTNOTE_REF_RE.sub("", raw)


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def chapter_title(work, chapters):
    """The source_title for a block from these chapter numbers:
    "On the Spirit, Chapter 7", "..., Chapters 7-8"."""
    a, b = min(chapters), max(chapters)
    t = work["source_title"]
    return f"{t}, Chapter {a}" if a == b else f"{t}, Chapters {a}-{b}"


def load_work(work):
    """Return (preamble_html, sections): one section per chapter. A section's heading is
    "Chapter XII. (= 12)", its html the section as the agent sees it (an <h2> holding the
    chapter number and the editor's summary, then the text, the footnotes inline as [note: ...]
    hints), its body the text without heading, summary, section numbers and notes, and
    `chapter` None (there are no verse sections); `chapter_no` is the chapter's number."""
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
    sections, secnos = [], []
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        raw = parts[i + 1].replace("</article>", "")
        title = _clean(FOOTNOTE_REF_RE.sub("", h2))
        if title == TITLE_H2:
            if sections or _clean(raw):
                raise SystemExit(f"{work['html']}: unexpected title heading {h2!r}")
            continue
        cm = CHAPTER_RE.fullmatch(title)
        if not cm:
            raise SystemExit(f"{work['html']}: unexpected <h2>: {h2}")
        no = roman(cm.group(1))
        sm = SUMMARY_RE.match(raw)
        if not sm:
            raise SystemExit(f"{work['html']}: Chapter {cm.group(1)} has no summary line")
        summary, raw = sm.group(1), raw[sm.end():]
        found = [int(x.group(2)) for x in SECNUM_RE.finditer(raw)]
        if not found or not re.match(r"\d+\.", raw):
            raise SystemExit(f"{work['html']}: Chapter {cm.group(1)} doesn't open with a "
                             "section number")
        secnos += found
        raw = SECNUM_RE.sub(lambda x: x.group(1), raw).strip() + "\n"
        sections.append({
            "heading": f"Chapter {cm.group(1)}. (= {no})",
            "chapter": None,
            "chapter_no": no,
            # (The summary's italics are dropped: Chapter XII's are never closed.)
            "html": (f"<h2>Chapter {cm.group(1)}. "
                     f"{re.sub(r'</?i>', '', hinted(summary)).strip()}</h2>\n"
                     + hinted(raw)),
            "body": _body(raw),
        })
    nos = [s["chapter_no"] for s in sections]
    if nos != list(range(1, len(nos) + 1)):
        raise SystemExit(f"{work['html']}: chapters are not numbered 1..n: {nos}")
    if secnos != list(range(1, len(secnos) + 1)):
        raise SystemExit(f"{work['html']}: section numbers are not 1..n: {secnos}")
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
    """The ordered list of pieces: {name, chapter, sections}; a piece is a run of whole
    chapters, named by its first and last chapter."""
    units = []
    for run in split_evenly(sections, cap):
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
    "We have Basil of Caesarea's treatise On the Spirit (De Spiritu Sancto) here: "
    "\"{units_dir}/{first_unit}\" with the files continuing up to \"{units_dir}/{last_unit}\". "
    "These are consecutive pieces cut, in order, from our PUBLIC-DOMAIN English translation of "
    "the work (Blomfield Jackson's, Nicene and Post-Nicene Fathers, Second Series, vol. 8, "
    "1895), \"{html_path}\" (consult it if you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. Basil wrote the treatise (about 375) for "
    "Amphilochius of Iconium, to defend the doxology to God the Father \"with the Son "
    "together with the Holy Ghost\" beside \"through the Son in the Holy Ghost\", in 30 "
    "chapters: the heretics' rule about the prepositions \"of whom\", \"through whom\" and "
    "\"in whom\", refuted from Scripture's own usage of them for the Father and the Son "
    "(Chapters I-VIII); what Scripture teaches about the Spirit, and the Spirit ranked with the "
    "Father and the Son in baptism (IX-XV); the Spirit inseparable from the Father and the Son "
    "in creation, in the dispensation and in judgment, not \"subnumerated\", glorified, called "
    "Lord, and the meaning of \"in\" and \"with\" (XVI-XXVIII); the unwritten tradition and "
    "the earlier writers who used \"with\" (XXVII, XXIX); and the present state of the "
    "Churches (XXX). Basil argues from Scripture throughout, quoting and expounding it "
    "constantly. Your task is to EXTRACT from the piece the stretches that are genuinely "
    "commentary on a specific verse of Scripture, and file each under that verse in the "
    "\"{father}/\" folder. Much of the text will NOT be imported, and that is expected: a "
    "chapter with no exposition of a verse gives no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the work's title at the top; that is background "
    "for you, not text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Basil QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words "
    "(literally or spiritually), resolves a difficulty in it, applies a figure or type in it "
    "(the cloud and the sea as types of baptism, the rock as Christ), builds his argument on "
    "its wording (which preposition it uses, who is named with whom, why it says what it says), "
    "or answers the heretics' reading of it. Do NOT import a verse quoted only in passing, a "
    "bare proof-text dropped into a sentence, a chain of proof-texts quoted without comment, or "
    "teaching that merely mentions Scripture. Ask: would a reader studying this verse learn "
    "something about how Basil understood or used it from this stretch? If so, import it; if it "
    "would only learn that Basil quoted it, leave it out.\n\n"
    "VERSE KEYS. Jackson's footnotes are shown inline as \"[note: ...]\" in superscript, after "
    "the word they mark. Many give the reference of a quotation, abbreviated with Roman chapter "
    "numbers (\"Luke xi. 10.\", \"1 Cor. viii. 6.\", \"Prov. xvii. 28, lxx.\" = the "
    "Septuagint's wording); many others are Jackson's remarks (the Greek of a word, the "
    "manuscripts' readings, the Benedictine editors, parallels in Basil's other works and in "
    "other Fathers) and give no verse. A note can sit on the wrong quotation, or be missing. Use "
    "the notes as HINTS only, and confirm every verse against the KJV wording with `"
    + KJV_LOOKUP + "`, filing under KJV book/chapter/verse numbering. Basil quotes the Greek "
    "Bible (the Septuagint for the Old Testament) and Jackson translates his wording, so it "
    "can differ from the KJV's: match by sense. Deuterocanonical books are fine (\"Sirach\", "
    "\"Wisdom\", \"Baruch\", ...): use only the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Basil's order, "
    "starting and ending at sentence boundaries, and able to stand on its own: include the "
    "sentence(s) that bring in the verse and the whole of his exposition of it (with the "
    "opponents' objection it answers, when the answer needs it to be understood). Don't pad a "
    "block with unrelated argument before or after the exposition. File it under the SMALLEST "
    "verse range the exposition really addresses: a single verse when it expounds one verse, a "
    "range only when it expounds several verses as one argument (a range crossing chapters is "
    "written like \"Exodus 13_21-14_22\"). When one stretch genuinely expounds two different "
    "passages (e.g. an Old Testament type and the New Testament verse that interprets it, "
    "expounded together), file the same text under each, as separate files; that is welcome. "
    "But never put two overlapping blocks of this work in the SAME file, and don't split one "
    "exposition into fragments under one verse.\n\n"
    "THE TEXT. Copy Basil's words VERBATIM: nothing abridged, paraphrased, corrected, added or "
    "rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Leave out the \"[note: "
    "...]\" footnotes and the <h2> headings (the chapter's number and the editor's summary, "
    "e.g. \"Chapter XII. Against those who assert that the baptism in the name of the Father "
    "alone is sufficient.\", are a heading, not text). The printed section numbers (1-79) have "
    "already been removed from the pieces: don't add them back. Keep the printed text's "
    "quotation marks, dashes, Greek words, bracketed words and misprints as they are. Don't add "
    "headings, verse numbers or notes of your own. Don't write a python script to do this; "
    "process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"\n"
    "where N is the (Arabic) number of the chapter the block comes from, e.g. \"{source_title}, "
    "Chapter 12\" for a block from \"Chapter XII.\"; a block running across chapters is "
    "\"{source_title}, Chapters 12-13\".\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are only "
    "ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it (with no blank line before its first [[commentary]]). Earlier pieces "
    "of THIS run may already have left blocks from Basil's On the Spirit in the files you "
    "write to: they are NOT old imports or duplicates; leave them exactly as they are and "
    "append yours after them. Blocks from Basil's other works (the Longer Rules, the Letters, "
    "the Hexaemeron, the homilies, the Catena Aurea's excerpts, and excerpts with no "
    "source_url) must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- chapter, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
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
        help="Process ONE piece (e.g. Part002_Ch09-16.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_Ch01-08.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part002_Ch09-16.html); combine with --start-after "
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

    log_dir = os.path.join(WORK_DIR, f"basil_{args.work.lower()}_import_logs")
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
