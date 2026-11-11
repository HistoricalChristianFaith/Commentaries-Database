#!/usr/bin/env python3
"""Import the Scripture commentary in Augustine of Hippo's The Harmony of the Gospels (De
consensu evangelistarum, Books 1-4, in S. D. F. Salmond's public-domain translation, revised by
M. B. Riddle, NPNF 1st series vol. 6, 1888) into the Commentaries-Database, one piece at a time,
by driving a headless ``claude`` agent.

A per-work copy of process_salvian_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting, logs and --check; a third Augustine
importer, since the Tractates' (process_augustine_commentary.py) is a homily importer. The work
is not a verse-by-verse commentary: Book 1 defends the evangelists against the pagans, and Books
2-4 go through the Gospel narrative in order, reconciling the four evangelists' accounts. So the
import is SELECTIVE (WORKS "selective": True): the agents read every chapter and file only the
stretches that genuinely expound a verse, under every Gospel's verse a harmonizing stretch
reconciles.

Each book is its own file in the Writings-Database, with its own url, so each is its own WORKS
entry ("Harmony1" .. "Harmony4"):

    Writings-Database/Augustine of Hippo/The Harmony of the Gospels/Book 2.html

    <h1>Book 2</h1>
    <i>editor's summary of the book</i><br/><br/>
    <h2>The Prologue.</h2>                      (Books 2-4: section 0)
    1. text ...<br/><br/>
    <h2>Chapter I.—A Statement of the Reason Why ...</h2>    (one section per chapter)
    2. text ...<sup><a href="#fn1" id="r1">1</a></sup> ...<br/><br/>
    text ...                                    (not every paragraph has a number)
    <section class="notes"><hr/><span id="fn1"><a href="#r1">1</a>&nbsp;Matt. i. 1.</span> ...

``load_work`` gives one section per chapter (and the book's prologue, as chapter 0). The NPNF
section numbers opening paragraphs ("2. ") are dropped (the user's choice), from the pieces as well
as the body, and must run 1..n through each book. Salmond's footnotes give most of the Scripture
references, so the html the agent sees carries each one inline, as ``<sup>[note: ...]</sup>``, as
a hint; the body (the text imported and checked) drops them.

    python3 process_augustine_harmony_commentary.py Harmony2 --dry-run
    python3 process_augustine_harmony_commentary.py Harmony2 --split-only
    python3 process_augustine_harmony_commentary.py Harmony2 Part002_Ch05-08.html
    python3 process_augustine_harmony_commentary.py Harmony2 --start-after Part001_Ch00-04.html
    python3 process_augustine_harmony_commentary.py Harmony2 --check
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

# A piece holds consecutive chapters up to about this many html chars (25k rather than the
# usual 30k: in Books 2-4 most of the text is imported, often under three or four Gospels).
SPLIT_CHARS = 25000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

HARMONY = "Augustine of Hippo/The Harmony of the Gospels"

# (book number, notes for that book).
_BOOKS = [
    (1, "Book 1 has no prologue. Its Chapters I-VI concern the evangelists themselves (their "
        "order, Matthew and Mark on Christ's kingly character, Luke on the priestly, John on "
        "His divinity, the active and contemplative virtues); Chapter VI reads the four living "
        "creatures as figures of the evangelists (KJV Revelation 4:7 and Ezekiel 1:10). The "
        "rest of the book argues against the pagans, quoting many prophecies of the overthrow "
        "of idols and the calling of the Gentiles: a prophecy Augustine quotes and shows to "
        "be fulfilled is commentary on it; a chain of them quoted without comment is not. "
        "Note 11 (\"Ps. lxxv. 1.\") marks \"Destroy not the writing of the title\", the "
        "psalm's title (KJV Psalm 75 \"Al-taschith\"), which goes under Psalms 75:1. Notes "
        "such as \"See chap. iii.\" refer to this work, not to Scripture."),
    (2, "Book 2's \"The Prologue.\" (from \"Whereas, in a discourse of no small length\" "
        "to \"rather than pondered in the spirit of consideration.\") only introduces the "
        "plan of Books 2-3: import nothing from it. The book then goes through Matthew in "
        "order, from the genealogy (Chapters I-V, with Luke's genealogy and infancy narrative) "
        "to the Last Supper; its last chapter ends with a quotation of Matthew 26:20-25 and "
        "\"offer nothing calculated to raise any question of serious difficulty.\", which "
        "is not commentary."),
    (3, "Book 3's \"Prologue.\" (from \"Inasmuch as we have now reached that point in the "
        "history\" to \"are taken as made by all the evangelists together.\") only states "
        "the method of the book: import nothing from it. From the Supper on, Augustine "
        "weaves all four Gospels into one narrative, so most stretches treat the same moment "
        "in several Gospels: file them under each Gospel's verse(s) they treat. Chapter XXV "
        "(Christ's appearances after the resurrection) is very long and moves through many "
        "separate appearances and questions: give each its own block under its own verses. "
        "Note 57 (\"Matt. xxvi. 53.\") is a misprint: the quotation there, \"Are ye come out "
        "as against a thief with swords and staves for to take me?\", is KJV Matthew 26:55."),
    (4, "Book 4's \"Prologue.\" (from \"As we have examined Matthew's narrative in its "
        "complete connection\" to \"have considered the subject of their mutual "
        "consistency.\") only states the plan of the book: import nothing from it. Chapters "
        "I-VII take the passages peculiar to Mark, Chapters VIII-IX those peculiar to Luke "
        "(Chapter VIII on Luke's preface, Luke 1:1-4, and the opening of Acts, Acts 1:1), "
        "and Chapter X John and his Gospel as a whole. Note 2 (\"Mark iv. 31.\") is a "
        "misprint: the passage there, His going into the synagogue at Capharnaum and teaching "
        "on the Sabbath-day, is KJV Mark 1:21."),
]

WORKS = {
    f"Harmony{no}": {
        "html": f"{HARMONY}/Book {no}.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        "kind": "harmony",
        "number": no,
        # "The Harmony of the Gospels, Book 2, Chapter 12" (the user's choice), as the url'd
        # blocks of the old import had it ("The Harmony of the Gospels, Book 2").
        "source_title": f"The Harmony of the Gospels, Book {no}",
        "notes": notes,
    }
    for no, notes in _BOOKS
}


def _raw_notes(work):
    """Salmond's notes of a work's file, in printed order (the text of each)."""
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
    the existing url'd blocks of the old import ("file=Augustine%2520of%2520Hippo%2FThe...")."""
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
# "<h2>Chapter XII.—Concerning the Words Ascribed to John ...</h2>"; "<h2>The Prologue.</h2>"
# (Book 2) / "<h2>Prologue.</h2>" (Books 3-4).
CHAPTER_H2_RE = re.compile(r"Chapter ([IVXL]+)\.—(.+)", re.S)
PROLOGUE_H2_RE = re.compile(r"(?:The )?Prologue\.")
# The NPNF section numbers, each opening a paragraph ("<br/><br/>\n25. Matthew proceeds", and
# after a heading "</h2>\n 49. What, then"). Dropped from pieces and body alike.
SECTION_NO_RE = re.compile(r"(?:^|(?<=<br/><br/>\n)) *(\d+)\. +")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman(s):
    n = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN_VALUES[a]
        n += -v if ROMAN_VALUES.get(b, 0) > v else v
    return n


# A note mark before a closing parenthesis keeps a space after it ("chargeable to any of
# them<sup>..327..</sup> ), but"; also Book 2 n.46, Book 3 n.100): the agents rightly write
# "them)," so the body drops the space with the mark.
MARK_BEFORE_PAREN_RE = re.compile(FOOTNOTE_REF_RE.pattern + r" (?=\))")


def _body(raw):
    return FOOTNOTE_REF_RE.sub("", MARK_BEFORE_PAREN_RE.sub("", raw))


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def chapter_title(work, chapters):
    """The source_title for a block from these chapter numbers (0 = the book's prologue)."""
    a, b = min(chapters), max(chapters)
    if a == b == 0:
        return f"{work['source_title']}, Prologue"
    if a == 0:
        return f"{work['source_title']}, Prologue and Chapter{'s 1-' if b > 1 else ' '}{b}"
    return (f"{work['source_title']}, Chapter {a}" if a == b
            else f"{work['source_title']}, Chapters {a}-{b}")


def load_work(work):
    """Return (preamble_html, sections): one section per chapter (and the book's prologue, as
    chapter 0). A section's heading is "Chapter XII. (= 12)" (or "Prologue"), its html the
    chapter as the agent sees it (its <h2> with the editor's title, the text without the NPNF
    section numbers, the footnotes inline as [note: ...] hints), its body the text without
    heading, numbers and notes, and `chapter` None (there are no verse sections); `chapter_no`
    is the chapter's number."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(text)])

    def hinted(raw):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""),
            raw)

    parts = H2_RE.split(text)
    preamble = parts[0]
    sections, numbers = [], []
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        raw = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        numbers += [int(n) for n in SECTION_NO_RE.findall(raw)]
        raw = SECTION_NO_RE.sub("", raw)
        title = _clean(h2)
        if PROLOGUE_H2_RE.fullmatch(title):
            if sections:
                raise SystemExit(f"{work['html']}: prologue after the first chapter")
            heading, no = "Prologue", 0
        else:
            cm = CHAPTER_H2_RE.fullmatch(title)
            if not cm:
                raise SystemExit(f"{work['html']}: unexpected <h2>: {h2}")
            no = roman(cm.group(1))
            heading = f"Chapter {cm.group(1)}. (= {no})"
        sections.append({
            "heading": heading,
            "chapter": None,
            "chapter_no": no,
            "html": h2 + "\n" + hinted(raw),
            "body": _body(raw),
        })
    nos = [s["chapter_no"] for s in sections if s["chapter_no"]]
    if nos != list(range(1, len(nos) + 1)):
        raise SystemExit(f"{work['html']}: chapters are not numbered 1..n: {nos}")
    if numbers != list(range(1, len(numbers) + 1)):
        raise SystemExit(f"{work['html']}: section numbers are not 1..n: {numbers}")
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
    "We have Augustine of Hippo's \"{title}\" ({work_ref}) here: "
    "\"{units_dir}/{first_unit}\" with the files continuing up to \"{units_dir}/{last_unit}\". "
    "These are consecutive pieces cut, in order, from our PUBLIC-DOMAIN English translation of "
    "the {unit} (S. D. F. Salmond's, revised by M. B. Riddle, 1888), \"{html_path}\" (consult "
    "it if you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. {about} Your task is to EXTRACT from the "
    "piece the stretches that are genuinely commentary on a specific verse of Scripture, and "
    "file each under that verse in the \"{father}/\" folder.{coverage}\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its chapters: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the {unit}'s title and the editor's italic "
    "summary of it at the top; that is background for you, not text to import. Each chapter's "
    "<h2> heading is the editor's title for it (often naming the passage and the question "
    "Augustine takes up): a useful hint, but not text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when {speaker} QUOTES or "
    "plainly refers to a specific verse AND DOES SOMETHING WITH IT: says what it means, "
    "interprets its words (literally, morally or spiritually), resolves a difficulty in it, "
    "applies a figure or type in it, builds his argument on its wording, shows how a prophecy "
    "in it is fulfilled, or, above all in this work, RECONCILES IT WITH ANOTHER GOSPEL'S "
    "ACCOUNT: explains a difference of wording, of detail, of names or numbers, or of order "
    "between the evangelists (\"Matthew says ..., while Mark says ...; but ...\"), or settles "
    "when and how an event happened. Do NOT import a verse quoted only in passing, a bare "
    "proof-text dropped into a sentence, a chain of proof-texts quoted without comment, or "
    "argument that merely mentions Scripture. In Books 2-4 Augustine often quotes a Gospel "
    "passage and then says only that the other evangelists report it too, or that it raises "
    "no question (\"In what we have now presented for consideration here, the other three "
    "evangelists ... offer nothing calculated to raise any question of serious difficulty.\"): "
    "such a stretch, with no observation of his own about the passage, is NOT commentary; "
    "leave it out. But if he notes anything about it (a detail one evangelist adds, why the "
    "order differs, that two accounts are of one event or of two), import it. Ask: would a "
    "reader studying this verse learn something about how Augustine understood it, or how he "
    "squared it with the other Gospels, from this stretch? If so, import it; if it would only "
    "learn that Augustine quoted it, leave it out.\n\n"
    "WHERE TO FILE. File each block under the SMALLEST verse range its exposition really "
    "addresses, and, because this work compares the Gospels, under EVERY Gospel's verse(s) "
    "that the stretch actually treats: when a stretch quotes or discusses Matthew's AND Mark's "
    "AND Luke's wording of the same saying or event and reconciles them, the same text goes "
    "in all three files (e.g. a reconciliation of Peter's denial foretold in Matthew 26:34, "
    "Mark 14:30, Luke 22:34 and John 13:38 goes under each of the four). Only the Gospels the "
    "stretch really deals with count: a Gospel named only in a footnote, or mentioned only as "
    "\"Mark and Luke also record this\" with nothing said about its wording or place, gets no "
    "copy. Augustine usually brings in a passage by quoting its opening and its close (\"... "
    "and so on, down to where we read, ...\", the note giving the whole range, e.g. \"Matt. "
    "ix. 35-x. 42.\"); that quotation stays in the block that discusses it, but it never "
    "widens the block's range: \"We are interested in the commentary, not so much the "
    "lemma.\" So: a discussion of a detail goes under the verse(s) of that detail (the staff "
    "and the shoes in Matthew 10:10, Mark 6:8-9, Luke 9:3; not the whole mission discourse); "
    "a discussion of where a passage stands in the ORDER of the narrative (whether the "
    "evangelist keeps the historical order or the order of his recollection, whether an "
    "incident is told in anticipation or by recapitulation) is about where it begins, so it "
    "goes under the passage's opening verse(s) as each evangelist quotes them (e.g. Matthew "
    "9:35, Mark 6:6-7, Luke 9:1), not under the whole range down to its end; and only an "
    "exposition that really treats a whole passage (a full reconstruction of a sequence of "
    "events, verse by verse) gets that passage's range. A range crossing chapters is written "
    "like \"Matthew 9_35-10_1\". Where a stretch genuinely expounds an Old Testament verse too "
    "(a prophecy quoted in the Gospel, a figure or a type), file it under that verse as well. "
    "Psalm numbers in the notes are the English (KJV) ones; a psalm's title goes under its "
    "verse 1. Never put two overlapping blocks of this {unit} in the SAME file, and don't split "
    "one exposition into fragments under one verse.\n\n"
    "VERSE KEYS. Salmond's footnotes are shown inline as \"[note: ...]\" in superscript, after "
    "the word they mark. Most give the reference of a quotation (\"Matt. ix. 35-x. 42.\", "
    "\"Mark vi. 6-11.\", \"Ps. cx. 4.\", \"Comp.\" = compare); many others give the Latin "
    "(\"Regnum evangelii.\"), a manuscript reading (\"... —Migne.\") or the American editor's "
    "remarks in brackets (\"[... —R.]\"), and give no verse. A note can sit on the wrong "
    "quotation, or be missing. Use the notes as HINTS only, and confirm every verse against "
    "the KJV wording with `" + KJV_LOOKUP + "`, filing under KJV book/chapter/verse "
    "numbering. Augustine quotes the Latin Bible, so his wording often differs from the KJV's: "
    "match by sense. Deuterocanonical books are fine (\"Sirach\", \"Wisdom\", ...): use only "
    "the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Augustine's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the passage (with its quotation) and the whole of his "
    "discussion of it. Augustine's discussions are long and run on from one point to the "
    "next: where he moves on to a different question about different verses (\"Another "
    "question which it is also usual to put is this: ...\"), start a new block, filed under "
    "those verses. Don't pad a block with unrelated argument before or after the exposition.\n\n"
    "THE TEXT. Copy Augustine's words VERBATIM: nothing abridged, paraphrased, corrected, "
    "added or rearranged. Drop the html tags (italics simply become plain text; don't turn "
    "them into quotation marks) and separate paragraphs with a single blank line. Leave out "
    "the \"[note: ...]\" footnotes and the <h2> chapter headings. The paragraph numbers of "
    "the printed edition have already been removed: don't add any. Keep the translator's "
    "square brackets (\"[represented as being]\"), the printed quotation marks, the dashes "
    "\"—\" (often ',—' or ';—'), the accented names (\"Jaïrus\", \"Judæa\"), the few Greek "
    "and Hebrew words, and misprints exactly as they are. Don't add headings, verse numbers "
    "or notes of your own. Don't write a python script to do this; process the file yourself "
    "manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this {unit}, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"\n"
    "where N is the (Arabic) number of the chapter the block comes from, e.g. \"{source_title}, "
    "Chapter 13\" for a block from \"Chapter XIII.\"; a block running across chapters is "
    "\"{source_title}, Chapters 13-14\". (A block from a book's Prologue would be "
    "\"{source_title}, Prologue\", but see the notes.)\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (and of the other books of the "
    "work) may already have left blocks from Augustine's {work_name} in the files you write "
    "to: they are NOT old imports or duplicates; leave them exactly as they are and append "
    "yours after them. Blocks from other works must be left exactly as they are: Augustine's "
    "Tractates on John, Sermons, Expositions on the Psalms, Our Lord's Sermon on the Mount, "
    "and above all the CATENA AUREA blocks (source_title \"Catena Aurea by Aquinas\"), which "
    "often quote this same work in another translation (\"(De Cons. Evang. ii. 2.) ...\"): "
    "they are a different source; don't touch them, and don't skip a block of yours because "
    "one of them covers similar ground.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- chapter, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


KIND_WORDING = {
    "harmony": {
        "work_ref": "Book {number} of his Harmony of the Gospels",
        "unit": "book",
        "work_name": "Harmony of the Gospels",
        "about": (
            "The Harmony of the Gospels (De consensu evangelistarum, about 400) answers those "
            "who said the four evangelists contradict each other. Book 1 defends the "
            "evangelists against the pagans: their order and character (the four living "
            "creatures of Ezekiel and the Apocalypse), and, at length, that the God of Israel "
            "whom the apostles preached has overthrown the idols as the prophets foretold. "
            "Book 2 goes through Matthew's Gospel in order from the genealogy to the Last "
            "Supper, comparing Mark, Luke and John with it at each step; Book 3 builds one "
            "narrative out of all four from the Supper to the resurrection appearances; Book "
            "4 takes the passages peculiar to Mark, Luke and John. Augustine writes in his "
            "own voice, quoting each Gospel's wording and showing how the accounts agree."),
        "speaker": "Augustine",
    },
}


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    words = KIND_WORDING[work["kind"]]
    coverage = (
        " Most of the text will NOT be imported, and that is expected: a chapter with no "
        "exposition of a verse gives no block."
        if work["number"] == 1 else
        " In this book most chapters reconcile a specific Gospel passage, so most of the text "
        "WILL be imported, but not all of it (see below).")
    return PROMPT1_TEMPLATE.format(
        **{k: v for k, v in words.items() if k != "work_ref"},
        work_ref=words["work_ref"].format(number=work["number"]),
        title=work["source_title"],
        units_dir=units_dir,
        first_unit=units[0]["name"],
        last_unit=units[-1]["name"],
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        father=FATHER,
        coverage=coverage,
        unit_name=unit["name"],
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
    # NFC, as in the Damascene importer (Salmond prints a few Greek and Hebrew words).
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
          f"{len(per_chapter)} of {len(sections)} chapters used")
    for no in sorted(per_chapter):
        print(f"  Chapter {no}: {', '.join(per_chapter[no])}")
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
    parser.add_argument("work", choices=sorted(WORKS), help="Which book of The Harmony of the Gospels to import.")
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
