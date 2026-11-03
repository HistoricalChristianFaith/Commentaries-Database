#!/usr/bin/env python3
"""Import the Scripture commentary in Eusebius of Caesarea's Proof of the Gospel (Demonstratio
Evangelica, Books 1-10 and the fragment of Book 15, in W. J. Ferrar's public-domain translation,
SPCK 1920) into the Commentaries-Database, one piece at a time, by driving a headless ``claude``
agent.

A per-father copy of process_cassian_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting, logs and --check. The Proof of
the Gospel is not a verse-by-verse commentary but an apologetic treatise that quotes and
expounds the Hebrew prophecies chapter by chapter, so the import is SELECTIVE (WORKS
"selective": True): the agents read every chapter and file only the stretches that genuinely
expound a verse; the rest is left out.

Each book is its own file in the Writings-Database (Roger Pearse's transcription), with its own
url, so each is its own WORKS entry ("DE01" .. "DE10"); Ferrar's INTRODUCTION and the online
edition's prefaces have none. The fragment of Book 15 (on Daniel 2) is printed at the end of
Book 10, so it is a section of DE10.

    Writings-Database/Eusebius of Caesarea/The Proof of the Gospel/Book 8.html

    <article class="writing"><h1>Book 8</h1><h2>BOOK VIII</h2>
    <b>INTRODUCTION</b><br><br> (362) I HAVE proved ...     (the book's introduction)
    <b>CHAPTER 2</b><br><br>                               (a chapter = one section)
    From Daniel.<br><br>                                   (Ferrar's heading: source line,
    <I>How after the Period of ...</I><br><br>              italic summary)
    [Passages quoted, Dan. ix. 20-27.]<br><br>              (Ferrar's placeholder: kept)
    text ... (b) ... (363) ...                              (Fabricius' page marks: dropped)
    <section class="notes"> ... </section>                  (Ferrar's footnotes: hints)

``load_work`` gives one section per chapter (heading "Chapter 2"), plus the book's
introduction (chapter_no 0) and, in Book 10, the Book 15 fragment (chapter_no 99). The html the
agent sees carries the footnotes inline as ``<sup>[note: ...]</sup>`` hints, and Pearse's
marginal Scripture references ("[[Isa. x. 33.]]") as they stand; the body (the text imported
and checked) drops the headings, summaries and sub-headings, the page marks, the notes and
marginal references, and Pearse's own editorial notes.

    python3 process_eusebius_commentary.py DE08 --dry-run
    python3 process_eusebius_commentary.py DE08 --split-only
    python3 process_eusebius_commentary.py DE08 Part002_Ch02-02.html
    python3 process_eusebius_commentary.py DE08 --start-after Part001_Ch00-01.html
    python3 process_eusebius_commentary.py DE08 --check
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

FATHER = "Eusebius of Caesarea"

# A piece holds consecutive chapters up to about this many html chars.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# The section numbers of the non-chapter sections.
INTRO_NO = 0
FRAGMENT_NO = 99

# --- Per-work configuration ---------------------------------------------------

PROOF = "Eusebius of Caesarea/The Proof of the Gospel"

# (book, label of the text before Chapter 1, notes for that book). The text before Chapter 1 is
# Eusebius's introduction to the book: headed "INTRODUCTION" (Books 1, 5, 8, 10) or "PREFACE"
# (Book 2), or unheaded (Books 3, 6, 7, 9); Book 4 has none.
_BOOKS = [
    (1, "Introduction", ""),
    (2, "Preface",
     "Book 2 is a collection of prophecies about the Gentiles and the Jews, numbered by Ferrar "
     "(\"12. From Psalm ii.\", \"36. From Isaiah.\"): each number opens a sub-section with its "
     "own source line, italic summary and usually a \"[Passage quoted, ...]\" line, and "
     "Eusebius's comment on it is often only a sentence or two (\"This is clear, and needs no "
     "interpretation.\"): import a sub-section's comment only when it really says something "
     "about the verse. Near the end of Chapter 3 stands a note by Pearse on his transcription "
     "(\"[Footnotes have been renumbered at placed at the end. ... a complete representation "
     "of this book.]\"): leave it out."),
    (3, "Introduction", ""),
    (4, None, ""),
    (5, "Introduction",
     "At the end of Chapter 1 a footnote of Ferrar's stands in the text (\"[There is a long "
     "lacuna at the end of this chapter, noted in the Paris MS., ...]\"), and the book ends "
     "with the printer's line \"END OF VOL. I.\": leave both out."),
    (6, "Introduction", ""),
    (7, "Introduction", ""),
    (8, "Introduction", ""),
    (9, "Introduction", ""),
    (10, "Introduction", ""),
]

WORKS = {
    f"DE{no:02d}": {
        "html": f"{PROOF}/Book {no}.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        "kind": "proof",
        "number": no,
        # "The Proof of the Gospel, Book 4, Chapter 16"; the book's introduction is
        # "..., Book 4, Introduction" and the fragment "The Proof of the Gospel, Book 15
        # (Fragment)".
        "source_title": f"The Proof of the Gospel, Book {no}",
        "intro_label": label,
        "notes": notes,
    }
    for no, label, notes in _BOOKS
}
FRAGMENT_TITLE = "The Proof of the Gospel, Book 15 (Fragment)"

# Pearse's editorial matter in the running text, cut from the body (the agents are told to
# leave it out too). The notes section and the footnote marks are handled separately.
STRIP = [
    # Fabricius' page numbers and their quarter-page letters, from Ferrar's margin: "(144)",
    # "(b)" (Books 2-10), "{2}", "{2b}" (Book 1). Only 2-3 digit numbers: Book 5's "(1)
    # accident ... (2) ... (3)" is Eusebius's own enumeration, and every book's pages are > 40.
    # Book 7 has one "(321 )".
    r"\([1-9]\d{1,2}\s*\)", r"\([a-d]\)", r"\{\d+[a-d]?\}",
    # The printer's line at the end of Book 5 (vol. i.).
    r"END OF VOL\. I\.",
    r"\[A few (?:of the )?footnotes (?:have been )?renumbered and placed (?:here|at the end)\]",
    # Pearse's notes on his transcription.
    r"\[All footnotes, biblical references, and indications of the numbering of the Greek "
    r"text \(beyond the first few\) have reluctantly been omitted\]",
    r"\[Footnotes up to p\.145 renumbered and placed here at the end\.(?:&nbsp;|\s)*Footnotes "
    r"after that omitted as tedious to transcribe and of limited value to the general reader\.\]",
    r"\[Note to the online text:[^\]]*\]",
    r"\[A footnote has been renumbered and moved here\]",
    r"\[Footnotes have been renumbered at placed at the end\.&nbsp; Greek page locations are in "
    r"\(\), scripture refs in \[\[\]\]\.&nbsp; This page was scanned at a time when I thought it "
    r"possible to include all the notes etc, so this is a complete representation of this "
    r"book\.\]",
    # A footnote of Ferrar's that Pearse moved into the text (end of Book 5, Chapter 1).
    r"\[There is a long lacuna at the end of this chapter, noted in the Paris MS\., [^\]]*\]",
    # Book 10: the separator before the Book 15 fragment, and the fragment's provenance line.
    r"(?i)<sup>-+</sup>",
    r"Given by A\. Majus in the New Collection of Ancient Writers\. Rome, 1825, tom\. 1, par\. 2, "
    r"p\. 173, in the Commentary on Daniel ii\. 31\.",
    # Pearse's marginal Scripture references, kept in the hint html: "[[Isa. x. 33.]]" (two
    # in Book 2 close with one bracket: "[[Jer. xxxi. 33.] they shall be"). Last, after the
    # Book 2 note above that mentions "[[]]".
    r"\[\[[^\]]*\]\]?",
]


def _raw_notes(work):
    """{note number: note text} of a work's notes section (Ferrar's footnotes, as kept by
    Pearse), without the printed per-page numbers ("49&nbsp;<SUP>4</SUP> ...", "1 [1] ...")."""
    with open(os.path.join(WRITINGS_DIR, work["html"]), encoding="utf-8") as f:
        m = NOTES_RE.search(f.read())
    out = {}
    for n, t in (NOTE_RE.findall(m.group(1)) if m else []):
        out[int(n)] = re.sub(r"^\d+\s*(?:\[\d+\]\s*)?", "", _clean(t))
    return out


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing url'd Proof of the Gospel blocks ("file=Eusebius%2520of%2520Caesarea%2FThe
    %2520Proof%2520of%2520the%2520Gospel%2FBook%25201.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"eusebius_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
# A section heading: "<b> CHAPTER 5&nbsp;</b>" (with any page mark after it on the line), or
# the fragment's "<b>A FRAGMENT OF THE FIFTEENTH BOOK</b>".
HEADING_RE = re.compile(r"<b>\s*(?:CHAPTER\s+(\d+)|(A FRAGMENT OF THE FIFTEENTH BOOK))"
                        r"(?:\s|&nbsp;)*</b>")
UNLINKED_SUP_RE = re.compile(r"<sup>(?!<a href)([^<]*)</sup>", re.I)
PARA_SPLIT_RE = re.compile(r"((?:<br\s*/?>\s*){2,})")
# The marks that may stand around a heading line or summary (page marks, spaces, note marks).
_MARKS = r"(?:\(\d{2,3}\s*\)|\([a-d]\)|\{\d+[a-d]?\}|&nbsp;|<[sS][uU][pP]>.*?</[sS][uU][pP]>|\s)*"
ITALIC_PARA_RE = re.compile(r"(?:" + _MARKS + r"<[iI]>.*?</[iI]>)+" + _MARKS, re.S)
# Ferrar's sub-heading lines, matched on their plain text: "From Micah.", "(46) 3. From the
# same.", "12. From Psalm ii.", "From the Second Book of Chronicles.", "From Porphyry On
# Vegetarianism", "Psalm xix.", and the book introductions' "INTRODUCTION" / "PREFACE".
SUBHEAD_RE = re.compile(r"(?:\d+\.\s*)?From [^.]{1,70}\.?|From Psalms [ivxlc]+\. and [ivxlc]+\."
                        r"|Psalms? [ivxlc]+\.?|INTRODUCTION|PREFACE")


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _plain(s):
    """A paragraph's plain text without page marks and note marks (for heading tests)."""
    s = re.sub(r"<sup>.*?</sup>", "", s, flags=re.S | re.I)
    s = re.sub(r"\(\d{2,3}\s*\)|\([a-d]\)|\{\d+[a-d]?\}", "", s)
    return _clean(s)


def is_heading_para(p):
    """True for a paragraph of Ferrar's apparatus: a bold heading, a sub-heading line, or a
    wholly italic chapter or sub-section summary."""
    s = p.strip()
    if not _plain(s):
        return False
    if re.fullmatch(_MARKS + r"<b>.*?</b>" + _MARKS, s, re.S):
        return True
    if ITALIC_PARA_RE.fullmatch(s):
        return True
    return bool(SUBHEAD_RE.fullmatch(_plain(s)))


def make_body(raw):
    """The text imported and checked: the raw section html without its apparatus paragraphs
    (headings, sub-headings, summaries), footnote marks, page marks, marginal references and
    Pearse's editorial notes. "[Passage(s) quoted, ...]" lines are Ferrar's and stay."""
    parts = PARA_SPLIT_RE.split(raw)
    kept = []
    for i in range(0, len(parts), 2):
        p = parts[i]
        if is_heading_para(FOOTNOTE_REF_RE.sub("", p)):
            continue
        kept.append(p)
    s = "<br><br>".join(kept)
    # Every removed mark becomes a placeholder first, so the spacing around it can be settled
    # by its neighbours (see _settle).
    s = FOOTNOTE_REF_RE.sub(NOTE_GAP, s)
    for pat in STRIP:
        s = re.sub(pat, GAP, s)
    # Unlinked note marks and empty superscripts, in either case: a mark goes ("expansion<sup>1
    # </sup> of", "for ever,<SUP>3</SUP> since"), an empty one counts as a space ("commands,<SUP>
    # </SUP>and" is "commands, and").
    s = UNLINKED_SUP_RE.sub(lambda m: f" {GAP} " if re.search(r"\s|&nbsp;", m.group(1)) else GAP,
                            s)
    return GAP_RUN_RE.sub(_settle, s)


# A removed mark, with the spaces around it.
GAP = "\x00"
# A removed footnote mark: printed after a word, so with no space after it in the markup it
# still separates words ("by the power of Christ.<sup>39</sup>And these" is "Christ. And").
NOTE_GAP = "\x01"
GAP_RUN_RE = re.compile(r"(?:\s|&nbsp;)*[\x00\x01](?:(?:\s|&nbsp;)*[\x00\x01])*(?:\s|&nbsp;)*")
# An opening quotation mark or bracket just before the gap ('&quot;{6a}&nbsp;Go' is '"Go').
_OPENER_RE = re.compile(r"(?:^|[\s>(\[])(?:&quot;|[\"“‘(\[])$|(?:^|<br\s*/?>\s*)$")
# Closing punctuation or a dash just after it ('rejoice&quot; [[John xvi. 20]]----the' is
# 'rejoice"----the').
_TIGHT_RE = re.compile(r"-|[,.;:!?)\]”’]|&quot;(?=[\s<,.;:)]|$)|<br|$")


def _settle(m):
    """What a removed mark leaves: nothing if no space stood around it, after an opening quote
    or at a paragraph start, or before closing punctuation or a dash; else one space."""
    left, right = m.string[:m.start()], m.string[m.end():]
    if not re.search(r"\s|&nbsp;", m.group()):
        if NOTE_GAP in m.group() and re.search(r"(?:[A-Za-z.,;:!?”’]|&quot;)$", left) \
                and re.match(r"[A-Za-z]", right):
            return " "
        return ""
    if _OPENER_RE.search(left) or _TIGHT_RE.match(right):
        return ""
    # A compound broken by a page mark: "His Only- (232) begotten Word" is "Only-begotten".
    if re.search(r"[A-Za-z]-$", left) and re.match(r"[a-z]", right):
        return ""
    return " "


def section_label(work, no):
    if no == INTRO_NO:
        return work["intro_label"]
    if no == FRAGMENT_NO:
        return "Fragment of Book 15"
    return f"Chapter {no}"


def chapter_title(work, chapters):
    """The source_title for a block from these section numbers."""
    chs = sorted(set(chapters))
    if chs == [FRAGMENT_NO]:
        return FRAGMENT_TITLE
    real = [c for c in chs if c not in (INTRO_NO, FRAGMENT_NO)]
    parts = []
    if INTRO_NO in chs:
        parts.append(work["intro_label"])
    if real:
        a, b = real[0], real[-1]
        parts.append(f"Chapter {a}" if a == b else f"Chapters {a}-{b}")
    return f"{work['source_title']}, {' and '.join(parts)}"


def load_work(work):
    """Return (preamble_html, sections): the book's introduction (chapter_no 0, if any), one
    section per chapter, and in Book 10 the Book 15 fragment (chapter_no 99). A section's
    heading is "Chapter 9" / "Introduction" / "Fragment of Book 15", its html the section as
    the agent sees it (heading, apparatus, text, the footnotes inline as [note: ...] hints), its
    body the text without apparatus and notes, and `chapter` None (there are no verse
    sections); `chapter_no` is its number."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    notes = _raw_notes(work)
    text = text.replace("</article>", "")
    h2 = text.index("</h2>") + len("</h2>")
    preamble = text[:h2] + "\n"
    heads = list(HEADING_RE.finditer(text))
    spans = [(INTRO_NO, None, h2, heads[0].start() if heads else len(text))]
    for k, hm in enumerate(heads):
        no = int(hm.group(1)) if hm.group(1) else FRAGMENT_NO
        end = heads[k + 1].start() if k + 1 < len(heads) else len(text)
        spans.append((no, hm.group(), hm.end(), end))
    sections = []
    for no, head, a, e in spans:
        raw = text[a:e].strip() + "\n"
        if no == INTRO_NO and not _clean(make_body(raw)):
            continue  # Book 4: no introduction
        if no == INTRO_NO and not work["intro_label"]:
            raise SystemExit(f"{work['html']}: text before Chapter 1 but no intro_label")
        hinted = FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(notes[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in notes else ""),
            raw)
        label = section_label(work, no)
        sections.append({
            "heading": label,
            "chapter": None,
            "chapter_no": no,
            "html": (head or f"<b>[{label}]</b>") + "\n" + hinted,
            "body": make_body(raw),
        })
    nos = [s["chapter_no"] for s in sections if s["chapter_no"] not in (INTRO_NO, FRAGMENT_NO)]
    if nos != list(range(1, len(nos) + 1)):
        raise SystemExit(f"{work['html']}: chapters are not numbered 1..n: {nos}")
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
    sections, named by its first and last chapter (00 = the introduction, 99 = the
    fragment)."""
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
    "We have Book {number} of Eusebius of Caesarea's \"Proof of the Gospel\" (Demonstratio "
    "Evangelica) here: \"{units_dir}/{first_unit}\" with the files continuing up to "
    "\"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, from our "
    "PUBLIC-DOMAIN English translation of the book (W. J. Ferrar's, 1920), \"{html_path}\" "
    "(consult it if you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. The Proof of the Gospel is Eusebius's apologetic "
    "treatise proving the Gospel from the Hebrew prophecies: Books 1-2 explain why Christians "
    "accept the Hebrew Scriptures but not the Mosaic way of life, and that the prophecies "
    "promise salvation to the Gentiles; Books 3-10 set out the prophecies of Christ's divinity, "
    "incarnation, name, time, birth, life, miracles and passion, quoting passage after passage "
    "and expounding them. Your task is to EXTRACT from the piece the stretches that are "
    "genuinely commentary on a specific verse of Scripture, and file each under that verse in "
    "the \"{father}/\" folder. Much of the text will NOT be imported, and that is expected: a "
    "chapter with no exposition of a verse gives no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the book's title at the top; that is background "
    "for you, not text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Eusebius QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words "
    "(literally or spiritually), shows how it was fulfilled in Christ, the apostles or the "
    "Church, resolves a difficulty in it, compares the versions (Aquila, Symmachus, Theodotion, "
    "the Hebrew), applies a figure in it (\"by Libanus here Jerusalem is meant\"), or builds "
    "his argument on its wording. Do NOT import a verse quoted only in passing, a bare "
    "proof-text dropped into a sentence, a chain of proof-texts quoted without comment, a long "
    "quotation with no exposition after it, or argument that merely mentions Scripture. Ask: "
    "would a reader studying this verse learn something about how Eusebius understood or used "
    "it from this stretch? If so, import it; if it would only learn that Eusebius quoted it, "
    "leave it out.\n\n"
    "VERSE KEYS. Eusebius quotes the Greek Old Testament (the Septuagint), and Ferrar "
    "translates his Greek, so the wording often differs from the KJV's: match every verse by "
    "its SENSE against the KJV wording with `" + KJV_LOOKUP + "`, and file under KJV "
    "book/chapter/verse numbering. Ferrar's references use the Septuagint's Psalm numbers "
    "(\"Ps. cix.\" is KJV Psalm 110; mostly add one, but Septuagint 9 = KJV 9-10, 113 = "
    "114-115, 114-115 = 116, 146-147 = 147) and Roman numerals (\"Isa. liii.\" = 53; an "
    "\"l\" or \"1\" may stand for 50, as in \"Isa. 1. 1\" for Isaiah 50:1). The verse numbers "
    "printed inside quotations (\"6. All we as sheep have gone astray\") follow Ferrar's "
    "Septuagint, so confirm them by the wording too. Hints, to be confirmed against the KJV: "
    "Ferrar's \"[Passage quoted, Isa. xxxv. 3.]\" lines (where Eusebius quotes a long passage, "
    "Ferrar prints only its reference), the sub-headings (\"From Micah.\", \"12. From Psalm "
    "ii.\"), Pearse's marginal references in double brackets (\"[[Isa. x. 33.]]\"), and "
    "Ferrar's footnotes, shown inline as \"[note: ...]\" in superscript after the word they "
    "mark (mostly textual notes on the Greek, a few references). Deuterocanonical books are "
    "fine (\"Sirach\", \"Wisdom\", \"Baruch\", ...): use only the book names in "
    "book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Eusebius's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse (the quotation itself, when it is printed) and the "
    "whole of his exposition of it. When the exposition follows a \"[Passage quoted, ...]\" "
    "line, start the block with that line, so the reader sees which passage is meant. Don't "
    "pad a block with unrelated argument before or after the exposition. File it under the "
    "SMALLEST verse range the exposition really addresses: a single verse when it expounds one "
    "verse, a range only when it expounds several verses as one argument (a range crossing "
    "chapters is written like \"Isaiah 52_13-53_12\"). A quoted passage expounded verse by "
    "verse gives one block per verse or small group of verses, not one block for the whole "
    "passage. When one stretch genuinely expounds two different passages (e.g. a prophecy and "
    "the Gospel verse that records its fulfilment, both interpreted), file the same text under "
    "each, as separate files; that is welcome. But never put two overlapping blocks of this "
    "book in the SAME file, and don't split one exposition into fragments under one verse.\n\n"
    "THE TEXT. Copy Ferrar's words VERBATIM: nothing abridged, paraphrased, corrected, added or "
    "rearranged; keep his Greek, his \"----\" dashes, the \"|\" marks dividing verse-lines in "
    "some quotations, his brackets and parentheses. Drop the html tags (italics simply become "
    "plain text; don't turn them into quotation marks) and separate paragraphs with a single "
    "blank line. LEAVE OUT: the bold headings (\"CHAPTER 5\", \"INTRODUCTION\"); Ferrar's "
    "apparatus around them and at each sub-section, i.e. the source lines (\"From Micah.\", "
    "\"(46) 3. From the same.\", \"Psalm xix.\") and every paragraph printed wholly in italics "
    "(the chapter and sub-section summaries, e.g. \"Of the Place of the Birth of the God "
    "fore-announced, ...\"); the page numbers and letters from Ferrar's margin, \"(144)\", "
    "\"(b)\", \"(c)\", \"(d)\", \"{{2}}\", wherever they stand, even mid-sentence (but keep "
    "Eusebius's own enumeration \"(1) ... (2) ... (3)\" in Book 5); the \"[note: ...]\" "
    "footnotes and any other superscript marks; Pearse's \"[[...]]\" marginal references; and "
    "Pearse's notes on his transcription (\"[Note to the online text: ...]\", \"[All footnotes, "
    "biblical references, ... omitted]\", \"[A footnote has been renumbered and moved here]\"). "
    "Keep the \"[Passage quoted, ...]\" lines when they fall inside or at the start of a "
    "block. Keep the printed text's run-together words and misprints as they are. Don't add "
    "headings, verse numbers or notes of your own. Don't write a python script to do this; "
    "process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this book, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"\n"
    "where N is the number of the chapter the block comes from, e.g. \"{source_title}, "
    "Chapter 13\" for a block from \"CHAPTER 13\"; a block running across chapters is "
    "\"{source_title}, Chapters 13-14\".{intro_fields}\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are only "
    "ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (and of the other books) may already have "
    "left blocks from Eusebius's Proof of the Gospel in the files you write to: they are NOT "
    "old imports or duplicates; leave them exactly as they are and append yours after them. "
    "Blocks from other works (his Commentary on Isaiah or on the Psalms, the Church History, "
    "the Catena Aurea, ...) must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- chapter, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    labels = {s["chapter_no"] for s in unit["sections"]}
    intro = ""
    if INTRO_NO in labels:
        intro += (f" A block from the book's {work['intro_label'].lower()} (the text before "
                  f"CHAPTER 1) is \"{work['source_title']}, {work['intro_label']}\"; don't run "
                  "a block from it into Chapter 1.")
    if FRAGMENT_NO in labels:
        intro += (" The \"FRAGMENT OF THE FIFTEENTH BOOK\" printed after Chapter 8 is not part "
                  f"of Book 10: a block from it is \"{FRAGMENT_TITLE}\" (with the same "
                  "source_url), and it starts with the sentence of the Daniel commentator "
                  "who quotes it (\"I THOUGHT it incumbent on me to quote ...\"); leave out "
                  "its provenance line (\"Given by A. Majus ...\") and the dashed rule before "
                  "the heading.")
    return PROMPT1_TEMPLATE.format(
        number=work["number"],
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
        intro_fields=intro,
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
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
            if re.search(r"</?[a-z]+>|\[note:|\[\[", q):
                problems.append(f"{fn}: leftover html tag, [note: ...] or [[...]] in a block")
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
    for no in sorted(per_chapter):
        print(f"  {section_label(work, no)}: {', '.join(per_chapter[no])}")
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
    parser.add_argument("work", choices=sorted(WORKS), help="Which book of the Proof of the Gospel to import (DE01 .. DE10).")
    parser.add_argument(
        "single", nargs="?",
        help="Process ONE piece (e.g. Part002_Ch02-02.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_Ch00-01.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part002_Ch02-02.html); combine with --start-after "
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

    log_dir = os.path.join(WORK_DIR, f"eusebius_{args.work.lower()}_import_logs")
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
