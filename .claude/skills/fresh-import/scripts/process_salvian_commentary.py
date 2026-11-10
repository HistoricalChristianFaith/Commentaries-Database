#!/usr/bin/env python3
"""Import the Scripture commentary in Salvian the Presbyter's On the Government of God (De
gubernatione Dei, Books 1-8, in Eva M. Sanford's public-domain translation, Columbia University
Press 1930, transcribed by Roger Pearse) into the Commentaries-Database, one piece at a time, by
driving a headless ``claude`` agent.

A per-father copy of process_damascene_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting, logs and --check. The work is not a
verse-by-verse commentary but a treatise on providence and the sins of the Romans that quotes and
expounds Scripture throughout, so the import is SELECTIVE (WORKS "selective": True): the agents
read every chapter and file only the stretches that genuinely expound a verse.

Each book is its own file in the Writings-Database, with its own url, so each is its own WORKS
entry ("GG01" .. "GG08"):

    Writings-Database/Salvian the Presbyter/On the Government of God/Book 1.html

    <h1>Book 1</h1><i>source note</i> <b>Book I : summary</b> [Translated by Eva M. Sanford]
    <h2>PREFACE</h2> ...                     (Book 1 only: the preface to Salonius = section 0)
    <h2>THE FIRST BOOK</h2>
    1.&nbsp;text ...<sup><a href="#fn1" id="r1">1</a></sup> ...<br><br>     (chapter 1)
    2.&nbsp;text ...                         (each chapter number opens a paragraph)
    <section class="notes"><hr><span id="fn1">... II Corinthians 12. 10.</span> ...

``load_work`` gives one section per chapter (cut at the numbers, which are dropped from the body
and shown to the agent as "<h2>Chapter 3.</h2>"). Sanford's footnotes give many of the Scripture
references, so the html the agent sees carries each one inline, as ``<sup>[note: ...]</sup>``,
as a hint; the body (the text imported and checked) drops them.

    python3 process_salvian_commentary.py GG01 --dry-run
    python3 process_salvian_commentary.py GG01 --split-only
    python3 process_salvian_commentary.py GG01 Part002_Ch05-08.html
    python3 process_salvian_commentary.py GG04 --start-after Part001_Ch01-06.html
    python3 process_salvian_commentary.py GG01 --check
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

FATHER = "Salvian the Presbyter"

# A piece holds consecutive chapters up to about this many html chars.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

GOVERNMENT = "Salvian the Presbyter/On the Government of God"

# (book number, notes for that book).
_BOOKS = [
    (1, "Book 1 opens with Salvian's preface to Bishop Salonius (\"<h2>PREFACE</h2>\", from "
        "\"TO THE HOLY BISHOP SALONIUS, SALVIAN SENDS GREETINGS IN THE LORD\" to \"At this point "
        "then I shall begin.\"); a block from it, if any, has source_title \"On the Government of "
        "God, Book 1, Preface\"."),
    (2, ""),
    (3, ""),
    (4, ""),
    (5, ""),
    (6, ""),
    (7, ""),
    (8, ""),
]

WORKS = {
    f"GG{no:02d}": {
        "html": f"{GOVERNMENT}/Book {no}.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        "kind": "government",
        "number": no,
        # "On the Government of God, Book 4, Chapter 3", as the one url'd block of the old
        # import had it ("On the Government of God, Book 4").
        "source_title": f"On the Government of God, Book {no}",
        "notes": notes,
    }
    for no, notes in _BOOKS
}


def _raw_notes(work):
    """Sanford's notes of a work's file, in printed order (the text of each)."""
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
    the existing url'd block of the old import ("file=Salvian%2520the%2520Presbyter%2FOn...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"salvian_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
# Sanford's chapter numbers, each opening a paragraph ("<br><br>\n3.&nbsp;Since this is true").
CHAPTER_RE = re.compile(r"(?:^|(?<=<br><br>\n))(\d+)\.&nbsp;")
BOOK_H2_RE = re.compile(r"THE (FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH) BOOK")
# Pearse's transcription leaves empty superscripts ("differing<sup> </sup>from", and after a
# note mark: "...&quot; <sup>..36..</sup><sup> </sup>Again") and, in Book 6, a period caught
# with a note mark in one: "the devil<sup>.<sup>..23..</sup> </sup>How". Both become plain text
# (a space; the period and a space) before anything else is done.
FIXUPS = [
    (re.compile(r"<sup>\.(<sup><a href=\"#fn\d+\" id=\"r\d+\">\d+</a></sup>) </sup>"), r".\1 "),
    (re.compile(r"<sup> </sup>"), " "),
]


# A note mark with text right before it and a letter right after it ("the Nine
# Peoples<sup>..4..</sup>had", "captures,<sup>..52..</sup>yet") stands for a space in the body.
GLUED_REF_RE = re.compile(r'(?<=\S)<sup><a href="#fn\d+" id="r\d+">\d+</a></sup>(?=[A-Za-z])')


def _body(raw):
    return FOOTNOTE_REF_RE.sub("", GLUED_REF_RE.sub(" ", raw))


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def chapter_title(work, chapters):
    """The source_title for a block from these chapter numbers (0 = Book 1's preface)."""
    a, b = min(chapters), max(chapters)
    if a == b == 0:
        return f"{work['source_title']}, Preface"
    if a == 0:
        return f"{work['source_title']}, Preface and Chapter{'s 1-' if b > 1 else ' '}{b}"
    return (f"{work['source_title']}, Chapter {a}" if a == b
            else f"{work['source_title']}, Chapters {a}-{b}")


def load_work(work):
    """Return (preamble_html, sections): one section per chapter (and Book 1's preface, as
    chapter 0). A section's heading is "Chapter 3" (or "Preface"), its html the chapter as the
    agent sees it ("<h2>Chapter 3.</h2>", the text without its number, the footnotes inline as
    [note: ...] hints), its body the text without heading, number and notes, and `chapter` None
    (there are no verse sections); `chapter_no` is the chapter's number."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    for rx, rep in FIXUPS:
        text = rx.sub(rep, text)
    if "<sup> " in text or "<sup>." in text:
        raise SystemExit(f"{work['html']}: unhandled bare <sup>")
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(text)])

    def hinted(raw):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""),
            raw)

    parts = H2_RE.split(text)
    preamble = parts[0]
    sections = []
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        raw = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        title = _clean(h2)
        if title == "PREFACE":
            if work["number"] != 1 or sections:
                raise SystemExit(f"{work['html']}: unexpected preface")
            sections.append({
                "heading": "Preface",
                "chapter": None,
                "chapter_no": 0,
                "html": h2 + "\n" + hinted(raw),
                "body": _body(raw),
            })
            continue
        if not BOOK_H2_RE.fullmatch(title):
            raise SystemExit(f"{work['html']}: unexpected <h2>: {h2}")
        cuts = list(CHAPTER_RE.finditer(raw))
        if not cuts or cuts[0].start() != 0:
            raise SystemExit(f"{work['html']}: text before chapter 1: {raw[:120]!r}")
        for j, c in enumerate(cuts):
            no = int(c.group(1))
            chunk = raw[c.end():cuts[j + 1].start() if j + 1 < len(cuts) else len(raw)]
            chunk = chunk.rstrip() + "\n"
            # The book's own heading ("THE FOURTH BOOK") stays before its first chapter.
            head = (h2 + "\n") if j == 0 else ""
            sections.append({
                "heading": f"Chapter {no}",
                "chapter": None,
                "chapter_no": no,
                "html": head + f"<h2>Chapter {no}.</h2>\n" + hinted(chunk),
                "body": _body(chunk),
            })
    nos = [s["chapter_no"] for s in sections if s["chapter_no"]]
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
    "We have Salvian the Presbyter's \"{title}\" ({work_ref}) here: "
    "\"{units_dir}/{first_unit}\" with the files continuing up to \"{units_dir}/{last_unit}\". "
    "These are consecutive pieces cut, in order, from our PUBLIC-DOMAIN English translation of "
    "the {unit} (Eva M. Sanford's, 1930), \"{html_path}\" (consult it if you need "
    "surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. {about} Your task is to EXTRACT from the "
    "piece the stretches that are genuinely commentary on a specific verse of Scripture, and "
    "file each under that verse in the \"{father}/\" folder. Most of the text will NOT be "
    "imported, and that is expected: a chapter with no exposition of a verse gives no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its chapters: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the {unit}'s title, Sanford's one-line summary of "
    "it in bold, and the source note at the top; that is background for you, not text to "
    "import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when {speaker} QUOTES or "
    "plainly refers to a specific verse AND DOES SOMETHING WITH IT: says what it means, "
    "interprets its words (literally, morally or spiritually), resolves a difficulty in it, "
    "applies a figure in it, builds his argument on its wording (\"he did not say ... but "
    "...\"), draws out what a Scripture narrative shows about God's judgment or care (Salvian "
    "retells many of them, e.g. the Flood, Sodom, David's sin and punishment, Gideon's three "
    "hundred, as proofs of God's government: such a retelling with his reading of it is "
    "commentary on the verses it retells), or APPLIES a verse to his readers' conduct in a way "
    "that shows how he reads it. Do NOT import a verse quoted only in passing, a bare "
    "proof-text dropped into a sentence, a chain of proof-texts quoted without comment, or "
    "denunciation and narrative of his own times that merely mentions Scripture. Ask: would a "
    "reader studying this verse learn something about how Salvian understood or used it from "
    "this stretch? If so, import it; if it would only learn that Salvian quoted it, leave it "
    "out.\n\n"
    "VERSE KEYS. Sanford's footnotes are shown inline as \"[note: ...]\" in superscript, after "
    "the word they mark. Many give the reference of a quotation (\"II Corinthians 12. 10.\", "
    "\"Ibid. 12. 9.\" = the same book as the note before, \"See ...\" or \"cf.\" = an allusion "
    "or a loose quotation, \"..., condensed\" or \"..., selections\" = Salvian abridges the "
    "passage); many others cite his classical and Christian sources (Seneca, Cicero, "
    "Lactantius, Valerius Maximus; \"Ad ecclesiam\" and \"Ep.\" are Salvian's own works) or "
    "discuss history, and give no verse. Sanford's Psalm numbers are the English (KJV) ones. A "
    "note can sit on the wrong quotation, or be missing. Use the notes as HINTS only, and "
    "confirm every verse against the KJV wording with `" + KJV_LOOKUP + "`, filing under KJV "
    "book/chapter/verse numbering. Salvian quotes the Latin Bible, so his wording often "
    "differs from the KJV's: match by sense. Deuterocanonical books are fine (\"Sirach\", "
    "\"Wisdom\", ...): use only the book names in book_names.json. Sanford's "
    "\"Ecclesiasticus\" is Sirach, and his verse numbers there are the Latin ones, which can "
    "differ from the KJV's (his \"Ecclesiasticus 39.10\", \"He himself loves counsel and "
    "discipline\", is KJV Sirach 39:7): place it by wording.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Salvian's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse and the whole of his exposition of it{question}. "
    "Don't pad a block with unrelated argument or denunciation before or after "
    "the exposition. File it under the SMALLEST verse range the exposition really addresses: a "
    "single verse when it expounds one verse, a range only when it expounds several verses as "
    "one argument or retells one passage as a whole (a range crossing chapters is written like "
    "\"Genesis 6_5-7_4\"). When one stretch genuinely expounds two different passages (e.g. "
    "two sayings interpreted together, or an Old Testament verse and the New Testament verse "
    "it is read with), file the same text under each, as separate files; that is welcome. "
    "But never put two overlapping blocks of this {unit} in the SAME file, and don't split "
    "one exposition into fragments under one verse.\n\n"
    "THE TEXT. Copy Salvian's words VERBATIM: nothing abridged, paraphrased, corrected, added "
    "or rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Leave out the \"[note: "
    "...]\" footnotes and the <h2> headings (the book heading, and the \"Chapter N.\" headings, "
    "which stand where Sanford printed the chapter number at the start of a paragraph: the "
    "number is not part of the text, so a block starting a chapter begins with its first "
    "word).{speakers} Keep the printed text's quotation marks (including doubled single quotes "
    "like '' and spaces inside quotation marks), the four-hyphen dashes \"----\", run-together "
    "words and misprints as they are. Don't add headings, verse numbers or notes of your own. "
    "Don't write a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this {unit}, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"\n"
    "where N is the number of the chapter the block comes from, e.g. \"{source_title}, "
    "Chapter 3\" for a block from \"Chapter 3.\"; a block running across chapters is "
    "\"{source_title}, Chapters 3-4\".\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (and of the other books of the "
    "work) may already have left blocks from Salvian's {work_name} in the files you write "
    "to: they are NOT old imports or duplicates; leave them exactly as they are and append "
    "yours after them. Blocks from Salvian's other works (To the Church against Avarice, also "
    "titled \"Four Books of Timothy to the Church\", and his Letters) must be left exactly as "
    "they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- chapter, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


KIND_WORDING = {
    "government": {
        "work_ref": "Book {number} of his On the Government of God",
        "unit": "book",
        "work_name": "On the Government of God",
        "about": (
            "On the Government of God (written in Gaul about 440, as the barbarians overran the "
            "Western Empire) answers those who said that God neglects the world because the "
            "Christian Romans suffer while barbarians prosper. Books 1-2 prove God's watchful "
            "care, rule and immediate judgment from the philosophers and from Scripture (the "
            "Flood, Sodom, the Exodus and the wilderness, David's history); Books 3-8 argue "
            "that the Romans suffer justly for their sins: their neglect of Christ's commands, "
            "the oppression of the poor by the rich, the circus and the theatres, the "
            "impurity of Aquitaine and Africa, compared with the chastity of the Goths and "
            "Vandals. Salvian writes in his own voice, often answering an imagined objector "
            "(\"But, you say, ...\"), and quotes and retells Scripture constantly."),
        "speaker": "Salvian",
        "question": " (and the objection it answers, when needed to make sense of it)",
        "speakers": "",
    },
}


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    words = KIND_WORDING[work["kind"]]
    return PROMPT1_TEMPLATE.format(
        **{k: v for k, v in words.items() if k != "work_ref"},
        work_ref=words["work_ref"].format(number=work["number"]),
        title=work["source_title"],
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
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
    # NFC, as in the Damascene importer (harmless here: Sanford prints no Greek).
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
    parser.add_argument("work", choices=sorted(WORKS), help="Which book of On the Government of God to import.")
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

    log_dir = os.path.join(WORK_DIR, f"salvian_{args.work.lower()}_import_logs")
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
