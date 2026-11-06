#!/usr/bin/env python3
"""Import the Scripture commentary in the Letters of Basil of Caesarea (Blomfield Jackson's
translation, NPNF 2nd series vol. 8, 1895, public domain) into the Commentaries-Database by
driving a headless ``claude`` agent over pieces that each hold a run of consecutive letters.

A per-father copy of process_athanasius_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, --check and --order/--fix-order. The letters
are correspondence (doctrinal letters on the Trinity and the Holy Spirit, ascetic, consolatory
and canonical letters, commendations and news), so the import is SELECTIVE (WORKS "selective":
True): the agents read every letter and file only the stretches that genuinely expound a verse.

Each letter is its own file in the Writings-Database, with its own url, so each is its own
WORKS entry ("BasLet001" .. "BasLet366", by the letter's number), built by scanning the folder.
No entry (the user's choices): the letters written TO Basil by others (OTHERS), the files that
hold no letter text (lost letters printed as an address only, or as the editor's bracketed
summary, "[Commendatory: short and unimportant.]"), the editor's Introduction, and the files
"Letters 330, 331, 332, 333" and "Letters 361, ...", which hold only editor's notes.

    Writings-Database/Basil of Caesarea/Letters/Letter 2.html

    <h1>Letter 2<sup><a href="#fn1" id="r1">1</a></sup></h1>     (the note dates the letter)
    <i>Basil to Gregory</i>.<br/><br/>                         (the heading line)
    1. [I recognised your letter, ...<br/><br/>                 (NPNF section numbers, or none)
    2. We must strive after a quiet mind. ...
    <section class="notes"><hr/><span id="fn2">... Matt. xvi. 24.</span> ...

``load_work`` gives one section per NPNF section number ("2." opening a paragraph; the text
before "2." is Section 1), one per canon in the canonical letters to Amphilochius (188, 199,
217: "XVII. You asked me ...", with the text before the first canon as section 0, the
"Introduction"), or one section for a letter without numbers ("whole letter"). The numbers are
dropped from the text; the pieces show them as ``<h2>`` headings. The heading line(s) under the
<h1> are the preamble (background for the agent, not text). The footnotes (Scripture references,
the dating, notes on the Greek) are shown inline as ``<sup>[note: Matt. xvi. 24.]</sup>`` hints
and dropped from the body.

A run is made of PIECES (the user's choice: most letters are 1-4k chars): ``make_batches``
packs consecutive letters, in number order over the whole collection, into pieces of up to
SPLIT_CHARS html chars ("B007_L041-046.html"); a letter bigger than that is cut at section
boundaries into pieces of its own ("B002_L008_S01-04.html"). The packing is global and
deterministic, so piece names don't depend on what a run selects.

    python3 process_basil_letters_commentary.py B001 --dry-run
    python3 process_basil_letters_commentary.py B001 B010-B014      # run these pieces
    python3 process_basil_letters_commentary.py --list               # all pieces and letters
    python3 process_basil_letters_commentary.py BasLet001-BasLet366 --check
    python3 process_basil_letters_commentary.py BasLet001 --order      # all files: letter order
    python3 process_basil_letters_commentary.py BasLet001 --fix-order BASE   # ... and fix it
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

# A piece packs consecutive letters up to about this many html chars (inline notes included); a
# bigger letter is cut at section boundaries into pieces of its own.
SPLIT_CHARS = 25000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

LETTERS_DIR = "Basil of Caesarea/Letters"

# Letters written TO Basil by others, printed in the collection: no entry (the user's choice).
OTHERS = {39: "Julian", 40: "Julian", 187: "Antipater",
          **{n: "Libanius" for n in (336, 338, 340, 341, 343, 345, 346, 347, 349, 352, 354,
                                     355, 357, 358)}}

# The canonical letters to Amphilochius, divided into canons numbered I-LXXXIV in Roman
# numerals across the three letters (188: I-XVI, 199: XVII-L, 217: LI-LXXXIV).
CANON_LETTERS = {188, 199, 217}

# Per-letter settings: `head` = how many paragraphs under the <h1> are heading matter (default
# 1, the italic address line); `gaps` = section/canon numbers the print lacks; `drop_paras` =
# regexes, a paragraph whose plain text starts with one is dropped; `strip` = regexes removed
# from the raw html. Each must match.
EXTRA = {
    # "(Canonica Prima.)" / "Canonica Secunda." above the address line.
    188: {"head": 2},
    # (Canon XXXII, "Clerics who are guilty of the sin unto death ...", had lost its numeral
    # and paragraph break in the source; restored there with the user's OK.)
    199: {"head": 2},
    # The text runs from the unnumbered Section 1 to "3.": there is no "2.".
    99: {"gaps": [2]},
    # Section 1 is numbered "I." (the rest "2.").
    233: {"strip": [r"(?<=\n)I\. (?=I know that I have myself heard of this)"]},
}

# Per-letter notes for the agents.
_NOTES = {
    99: ("The printed text has no Section 2: the unnumbered text before \"3.\" is Section 1, "
         "and the next is Section 3."),
    199: "The heading line \"Canonica Secunda.\" above the address is the letter's title.",
    188: "The heading line \"(Canonica Prima.)\" above the address is the letter's title.",
    233: ("Section 1 is printed \"I.\" in the source file (the next is \"2.\"); the numeral "
          "has been removed like the others."),
}

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
PARA_SPLIT_RE = re.compile(r"(?:<br\s*/?>\s*){2,}")
# An NPNF section number opening a paragraph ("2. But hitherto"; Letter 203's "[3. Let not",
# whose bracket is the translator's and stays in the text).
SECTION_NO_RE = re.compile(r"(\[?)(\d+)\.\s+")
# A canon number opening a paragraph ("XVII. You asked me").
CANON_NO_RE = re.compile(r"([IVXL]+)\.\s+")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50}
# An editor's bracketed summary standing for a lost letter ("[A salutation.]").
SUMMARY_RE = re.compile(r"\[[^\[\]]*\]\.?")


def roman(s):
    vals = [ROMAN_VALUES[c] for c in s]
    return sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _plain(p):
    """A paragraph's plain text without its note marks."""
    return _clean(FOOTNOTE_REF_RE.sub("", p))


def _read_letter(fn, extra):
    """(head html up to </h1>, paragraphs after it) of a letter file, notes section removed and
    the letter's `strip` patterns applied."""
    with open(os.path.join(WRITINGS_DIR, LETTERS_DIR, fn), encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    for rx in extra.get("strip", []):
        text, n = re.subn(rx, "", text)
        if not n:
            raise SystemExit(f"{fn}: strip pattern matched nothing: {rx!r}")
    head, rest = text.split("</h1>", 1)
    paras = [p.strip() for p in PARA_SPLIT_RE.split(rest.replace("</article>", ""))]
    return head, [p for p in paras if p]


def _scan():
    """WORKS: one entry per letter file with letter text, by number. Returns (works, skipped),
    skipped = {file name: reason}."""
    works, skipped = {}, {}
    for fn in sorted(os.listdir(os.path.join(WRITINGS_DIR, LETTERS_DIR))):
        m = re.fullmatch(r"Letter (\d+)\.html", fn)
        if not m:
            skipped[fn] = "not a single letter's file"
            continue
        no = int(m.group(1))
        if no in OTHERS:
            skipped[fn] = f"written to Basil by {OTHERS[no]}"
            continue
        extra = EXTRA.get(no, {})
        _, paras = _read_letter(fn, extra)
        body = paras[extra.get("head", 1):]
        if not body or all(SUMMARY_RE.fullmatch(_plain(p)) for p in body):
            skipped[fn] = "no letter text (address or editor's summary only)"
            continue
        if no in CANON_LETTERS:
            label = "Canon"
        elif any(SECTION_NO_RE.match(p) for p in body):
            label = "Section"
        else:
            label = None
        works[f"BasLet{no:03d}"] = {
            "html": f"{LETTERS_DIR}/{fn}",
            # No commented book: the agents choose any book of book_names.json.
            "book": None,
            "selective": True,
            "number": no,
            "label": label,
            # "Letter 8, Section 2" / "Letter 8, Sections 2-3" / "Letter 188, Canon 12" /
            # "Letter 188, Introduction"; a letter without numbers is plain "Letter 13" (the
            # user's choice).
            "source_title": f"Letter {no}",
            "notes": _NOTES.get(no, ""),
            **extra,
        }
    return dict(sorted(works.items())), skipped


WORKS, SKIPPED = _scan()


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
    the url'd blocks of the old import ("file=Basil%2520of%2520Caesarea%2FLetters%2FLetter%2520101.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"basil_{work_key.lower()}_units")


BATCH_UNITS_DIR = os.path.join(WORK_DIR, "basil_letters_units")


# --- Parsing and splitting ----------------------------------------------------


def chapter_title(work, chapters):
    """The source_title for a block from these section (canon) numbers."""
    if not work["label"]:
        return work["source_title"]
    nos = [c for c in chapters if c]
    a, b = (min(nos), max(nos)) if nos else (0, 0)
    lab = work["label"]
    tail = "" if not nos else (f"{lab} {a}" if a == b else f"{lab}s {a}-{b}")
    if 0 in chapters:
        tail = "Introduction" + (f" and {tail}" if tail else "")
    return f"{work['source_title']}, {tail}"


def load_work(work):
    """Return (preamble_html, sections): one section per NPNF section (or canon, or the whole
    letter). A section's heading is "Section 2" / "Canon 17" / "Introduction" / "whole letter",
    its html the section as the agent sees it (an <h2> with the number, the text, the footnotes
    inline as [note: ...] hints), its body the text without number and notes, `chapter` None
    (there are no verse sections) and `chapter_no` its number (0 for a canonical letter's
    introduction)."""
    fn = os.path.basename(work["html"])
    head, paras = _read_letter(fn, work)
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(head + "".join(paras))])

    def hinted(s):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""), s)

    nhead = work.get("head", 1)
    if not paras[nhead - 1].startswith("<i>"):
        raise SystemExit(f"{work['html']}: no italic address line: {paras[nhead - 1][:100]!r}")
    preamble = (hinted(head) + "</h1>\n"
                + "".join(hinted(p) + "<br/><br/>\n" for p in paras[:nhead]))

    used, keep = set(), []
    for p in paras[nhead:]:
        rxs = [rx for rx in work.get("drop_paras", []) if re.match(rx, _plain(p))]
        if rxs:
            used.update(rxs)
            continue
        keep.append(p)
    for rx in work.get("drop_paras", []):
        if rx not in used:
            raise SystemExit(f"{work['html']}: pattern matched no paragraph: {rx!r}")

    label, gaps = work["label"], set(work.get("gaps", []))
    sections = []

    def start(no, h2):
        heading = ({"Section": f"Section {no}", "Canon": f"Canon {no}"}[label] if label and no
                   else "Introduction" if label else "whole letter")
        sections.append({"heading": heading, "chapter": None, "chapter_no": no, "h2": h2,
                         "paras": []})

    def follows(n, last):
        return n == last + 1 or (n == last + 2 and last + 1 in gaps)

    for p in keep:
        if label == "Canon":
            cm = CANON_NO_RE.match(p)
            if cm:
                n = roman(cm.group(1))
                if sections and sections[-1]["chapter_no"] and not follows(
                        n, sections[-1]["chapter_no"]):
                    raise SystemExit(f"{work['html']}: canon {n} after "
                                     f"{sections[-1]['chapter_no']}: {_plain(p)[:80]!r}")
                start(n, f"<h2>Canon {cm.group(1)}. (= {n})</h2>\n")
                p = p[cm.end():]
            elif not sections:
                start(0, "<h2>The letter's opening, before the first canon.</h2>\n")
            sections[-1]["paras"].append(p)
            continue
        sm = SECTION_NO_RE.match(p)
        if sm:
            if label != "Section":
                raise SystemExit(f"{work['html']}: a section number in a letter labelled "
                                 f"{label}: {_plain(p)[:80]!r}")
            n = int(sm.group(2))
            last = sections[-1]["chapter_no"] if sections else 0
            # (Unnumbered text before "2." has already started Section 1 below.)
            if follows(n, last):
                start(n, f"<h2>Section {n}.</h2>\n")
            elif n != last:
                raise SystemExit(f"{work['html']}: section {n} after {last}: {_plain(p)[:80]!r}")
            p = sm.group(1) + p[sm.end():]
        elif not sections:
            # (A letter without numbers gets an <h2> too, marking where its text starts.)
            start(1, "<h2>Section 1.</h2>\n" if label else "<h2>The letter.</h2>\n")
        sections[-1]["paras"].append(p)

    for s in sections:
        raw = "<br/><br/>\n".join(s.pop("paras")) + "\n"
        s["html"] = s.pop("h2") + hinted(raw)
        s["body"] = FOOTNOTE_REF_RE.sub("", raw)
    nos = [s["chapter_no"] for s in sections]
    if label == "Canon":
        if nos[0] != 0 or len(nos) < 2:
            raise SystemExit(f"{work['html']}: canons {nos}: no introduction or no canon")
    elif label == "Section":
        if [n for n in range(1, nos[-1] + 1) if n not in gaps] != nos or len(nos) < 2:
            raise SystemExit(f"{work['html']}: sections are not numbered 1..n: {nos}")
    elif nos != [1]:
        raise SystemExit(f"{work['html']}: sections {nos} in a letter without numbers")
    return preamble, sections


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in PARA_SPLIT_RE.split(section["body"]):
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
    sections, named by its first and last section."""
    units = []
    for run in split_evenly(sections, cap):
        a, b = run[0]["chapter_no"], run[-1]["chapter_no"]
        units.append({
            "name": f"Part{len(units) + 1:03d}_S{a:02d}-{b:02d}.html",
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


# --- Pieces: runs of consecutive letters --------------------------------------


def make_batches():
    """Every piece of the run, in letter order: {name, letters: [(key, preamble, sections)],
    part: (i, n) for the pieces of a letter too big for one piece, else None}. Consecutive
    letters are packed up to SPLIT_CHARS; the packing runs over the whole collection, so a
    piece's name and content don't depend on what a run selects."""
    batches, cur, acc = [], [], 0

    def flush():
        nonlocal cur, acc
        if cur:
            batches.append({"letters": cur, "part": None})
        cur, acc = [], 0

    for k in WORKS:
        pre, secs = load_work(WORKS[k])
        size = len(pre) + sum(len(s["html"]) for s in secs)
        if size > SPLIT_CHARS:
            flush()
            runs = split_evenly(secs, SPLIT_CHARS) if len(secs) > 1 else [secs]
            for i, run in enumerate(runs):
                batches.append({"letters": [(k, pre, run)], "part": (i + 1, len(runs))})
            continue
        if cur and acc + size > SPLIT_CHARS:
            flush()
        cur.append((k, pre, secs))
        acc += size
    flush()
    for i, b in enumerate(batches):
        nos = [WORKS[k]["number"] for k, _, _ in b["letters"]]
        if b["part"]:
            secs = b["letters"][0][2]
            b["name"] = (f"B{i + 1:03d}_L{nos[0]:03d}_S{secs[0]['chapter_no']:02d}-"
                         f"{secs[-1]['chapter_no']:02d}.html")
        else:
            b["name"] = f"B{i + 1:03d}_L{nos[0]:03d}-{nos[-1]:03d}.html"
    return batches


def batch_html(batch):
    """A piece as the agent sees it: each letter's <h1>, address line(s) and sections."""
    out = ['<article class="writing">\n']
    for k, pre, secs in batch["letters"]:
        out.append(pre.replace('<article class="writing">', "", 1))
        out += [s["html"] for s in secs]
        out.append("\n")
    out.append("</article>\n")
    return "".join(out)


def write_batches(batches):
    d = BATCH_UNITS_DIR
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for b in batches:
        with open(os.path.join(d, b["name"]), "w", encoding="utf-8") as f:
            f.write(batch_html(b))
    return d


def batch_size(batch):
    return sum(len(pre) + sum(len(s["html"]) for s in secs) for _, pre, secs in batch["letters"])


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have letters of Basil of Caesarea (Basil the Great, bishop of Caesarea in Cappadocia, "
    "d. 379) here: \"{units_dir}/{unit_name}\". {piece_desc} They come from our PUBLIC-DOMAIN "
    "English translation of his Letters (Blomfield Jackson, Nicene and Post-Nicene Fathers, "
    "2nd series, vol. 8, 1895); each letter's full source file is named below (consult it if "
    "you need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. The Letters are Basil's correspondence: "
    "doctrinal letters (on the Trinity, the Son's Godhead against Eunomius and the Arians, the "
    "Holy Spirit against the Pneumatomachi, the Incarnation against Apollinarius), ascetic and "
    "consolatory letters, canonical letters on penance and church discipline, and many "
    "letters of friendship, commendation, news and church business. Your task is to EXTRACT "
    "the stretches that are genuinely commentary on a specific verse of Scripture, and file "
    "each under that verse in the \"{father}/\" folder. Most of the text will NOT be imported, "
    "and that is expected: many letters give no block at all.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  ({contents})\n\n"
    "Read the WHOLE file. Each letter opens with its <h1> (\"Letter 8\", with the editor's "
    "note on its date), then its address line (\"To the Cæsareans\", sometimes with the "
    "editor's summary); that is background for you, not text to import. A block NEVER runs "
    "from one letter into the next.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Basil QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words "
    "(literally, morally or spiritually), resolves a difficulty in it, applies a figure or "
    "type in it, builds his argument on its wording (e.g. a doctrinal point on the Son or the "
    "Spirit drawn from how a verse is phrased, or a reply to the heretics' reading of it), "
    "grounds a canon or a ruling on what a verse says, or APPLIES it to the Christian or "
    "ascetic life, to a sorrow or a trial, in a way that shows how he reads it (a verse "
    "brought in to describe the state of the churches, a bereavement or a fall, and then "
    "drawn out). Do NOT import a verse quoted only in passing, a bare proof-text dropped into "
    "a sentence, a chain of proof-texts quoted without comment, a scriptural phrase borrowed "
    "into his own sentence, or news, courtesy and church business that merely mentions "
    "Scripture. Ask: would a reader studying this verse learn something about how Basil "
    "understood or used it from this stretch? If so, import it; if it would only learn that "
    "Basil quoted it, leave it out.\n\n"
    "VERSE KEYS. Jackson's footnotes are shown inline as \"[note: ...]\" in superscript, after "
    "the word they mark. Many give the reference of a quotation (\"Matt. xvi. 24.\", \"Ps. lv. "
    "22 and 1 Pet. v. 7.\", \"Cf.\" = an allusion; \"LXX\" after one means Basil follows the "
    "Septuagint's wording); others date the letter, discuss the Greek, the persons, the "
    "manuscripts or the canons, or cite other writers, and give no verse. The notes' Psalm "
    "numbers are the English (KJV) ones. The notes also cite works that are NOT Scripture: "
    "\"Ep.\" / \"Letter cciv.\" another letter of Basil, \"De Sp. S.\" his On the Holy "
    "Spirit, \"Hex.\" / \"Hom.\" his homilies, \"Ecc. Hist.\" / \"Hist. Ecc.\" and "
    "\"Soz.\", \"Soc.\", \"Theod.\" the church historians, \"Or.\" / \"Orat.\" "
    "Gregory's orations, \"Vit. Bas.\" the Benedictine life of Basil, \"Ben.\" the "
    "Benedictine editors, \"Can.\" a council's canon, \"Cod. Theod.\" the Theodosian Code, "
    "\"Od.\" / \"Il.\" Homer, \"R.V.\" the Revised Version; \"Ecclus.\" is Sirach, and "
    "\"Ecc.\" may be Ecclesiastes or Ecclesiasticus (check the wording). A note can sit on "
    "the wrong quotation, be misprinted, "
    "or be missing. Use the notes as HINTS only, and confirm every verse against the KJV "
    "wording with `" + KJV_LOOKUP + "`, filing under KJV book/chapter/verse numbering. Basil "
    "quotes the Greek Bible (the Septuagint for the Old Testament), so his wording often "
    "differs from the KJV's, and the Septuagint verse division sometimes differs too: match by "
    "sense. Deuterocanonical books are fine (\"Sirach\", \"Wisdom\", \"Baruch\", ...): use only "
    "the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of ONE letter, in Basil's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse and the whole of his exposition of it. "
    "Don't pad a block with unrelated matter before or after the exposition. File it under the "
    "SMALLEST verse range the exposition really addresses: a single verse when it expounds one "
    "verse, a range only when it expounds several verses as one argument (a range crossing "
    "chapters is written like \"Matthew 5_48-6_1\"). When one stretch genuinely expounds two "
    "different passages (e.g. two verses set side by side and interpreted together), file the "
    "same text under each, as separate files; that is welcome. But never put two overlapping "
    "blocks of the same letter in the SAME file, and don't split one exposition into fragments "
    "under one verse.\n\n"
    "THE TEXT. Copy Basil's words VERBATIM: nothing abridged, paraphrased, corrected, added or "
    "rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Leave out the "
    "\"[note: ...]\" footnotes and the <h1>/<h2> headings: the editors' section numbers (and "
    "the canon numerals of the canonical letters) have already been removed from the text, so "
    "a paragraph that opened \"2. But hitherto\" or \"XVII. You asked me\" in the printed "
    "book reads \"But hitherto\" / \"You asked me\" here, and so it must in your block. Keep "
    "the square brackets of the printed text (some passages are printed wholly in brackets; "
    "\"[3. Let not\" now reads \"[Let not\") and parenthesised remarks as printed, and the "
    "printed text's quotation marks (‘ ’ “ ”), "
    "dashes, ellipses, Greek and Latin words, run-together words and misprints as they are. "
    "Don't add headings, verse numbers or notes of your own. Don't write a python script to "
    "do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. Every letter has its own source_url and source_title. For EVERY block you "
    "import, set the fields of the letter it comes from:\n"
    "{fields}\n\n"
    "EXISTING BLOCKS. The old imports of these letters have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (other letters of Basil{earlier}) may "
    "already have left blocks from his Letters in the files you write to: they are NOT old "
    "imports or duplicates; leave them exactly as they are and append yours after them. Blocks "
    "from other works (The Longer Rules, On the Holy Spirit, the Hexaemeron, the homilies, the "
    "Catena Aurea, the old url-less excerpts, ...) must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- letter and "
    "section, opening words), and every exposition of a verse you considered but left out, "
    "with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


def _fields(work, secs):
    """The SOURCE FIELDS lines of one letter in a piece."""
    head = (f"- Letter {work['number']} (source file \"{os.path.join(WRITINGS_DIR, work['html'])}\"):\n"
            f"    source_url   = {source_url_for(work)}\n")
    st = work["source_title"]
    lab = work["label"]
    if not lab:
        return head + f"    source_title = \"{st}\"   (no section numbers, so no suffix)"
    if lab == "Canon":
        return head + (
            f"    source_title = \"{st}, Canon N\" where N is the canon's number in ARABIC "
            f"figures (its <h2>: \"Canon XVII. (= 17)\" gives \"{st}, Canon 17\"); a block "
            f"running across canons is \"{st}, Canons 17-18\"; the letter's opening before the "
            f"first canon is \"{st}, Introduction\" (\"{st}, Introduction and Canon N\" if a "
            f"block runs on into the first canon)")
    return head + (
        f"    source_title = \"{st}, Section N\" where N is the section the block comes from "
        f"(the <h2> headings), e.g. \"{st}, Section {secs[0]['chapter_no']}\"; a block "
        f"running across sections is \"{st}, Sections 2-3\"")


def build_prompt1(batch, units_dir):
    letters = batch["letters"]
    if batch["part"]:
        k, pre, secs = letters[0]
        i, n = batch["part"]
        piece_desc = (f"It is piece {i} of {n} of Letter {WORKS[k]['number']}, which is too "
                      f"long for one piece; the other pieces are processed separately (the "
                      f"earlier ones may already have left blocks of this letter: don't touch "
                      f"them, and don't import text outside this piece).")
        contents = (f"Letter {WORKS[k]['number']}: "
                    + ", ".join(s["heading"] for s in secs))
        earlier = ", or earlier pieces of this letter"
    elif len(letters) == 1:
        piece_desc = "It holds one whole letter."
        contents = f"Letter {WORKS[letters[0][0]]['number']}"
        earlier = ""
    else:
        a, b = WORKS[letters[0][0]]["number"], WORKS[letters[-1][0]]["number"]
        piece_desc = (f"It holds {len(letters)} consecutive letters of the collection, from "
                      f"Letter {a} to Letter {b}, each complete and each opening with its "
                      f"<h1>.")
        contents = "; ".join(
            f"Letter {WORKS[k]['number']}"
            + (f" ({', '.join(s['heading'] for s in secs)})" if WORKS[k]["label"] else "")
            for k, _, secs in letters)
        earlier = ""
    notes = " ".join(f"In Letter {WORKS[k]['number']}: {WORKS[k]['notes']}"
                     for k, _, _ in letters if WORKS[k].get("notes"))
    return PROMPT1_TEMPLATE.format(
        units_dir=units_dir,
        unit_name=batch["name"],
        piece_desc=piece_desc,
        father=FATHER,
        contents=contents,
        notes=f" {notes}" if notes else "",
        fields="\n".join(_fields(WORKS[k], secs) for k, _, secs in letters),
        earlier=earlier,
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
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


def run_check(work, sections, quiet=False):
    """Return a list of problems (empty == all good). Prints a summary (with `quiet`, only
    failures). A selective import has no coverage to check: this checks that every block of
    this letter is one verbatim stretch of it, found once, under a valid filename, with the
    right source_title."""
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

    if not quiet or problems:
        print(f"\nCHECK {work['source_title']}: {n} block(s) in {len(files)} file(s); "
              f"{len(per_chapter)} of {len(sections)} section(s) used")
    if not quiet:
        heads = {s["chapter_no"]: s["heading"] for s in sections}
        for no in sorted(per_chapter):
            print(f"  {heads[no]}: {', '.join(per_chapter[no])}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    elif not quiet:
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


def _contents(batch):
    return [f"Letter {WORKS[k]['number']}"
            + (f" ({', '.join(s['heading'] for s in secs)})" if WORKS[k]["label"] else "")
            for k, _, secs in batch["letters"]]


def log_record(log, batch, prompt_no, started, ended, session_id, output):
    log.write(
        json.dumps(
            {
                "unit": batch["name"],
                "sections": _contents(batch),
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


def process_unit(batch, units_dir, log, events_log):
    """Run prompt 1 (import) then prompt 2 (self-review) in one conversation."""
    print(f"\n{'=' * 60}")
    print(f"{batch['name']}: {'; '.join(_contents(batch))}")
    print(f"{'=' * 60}")
    tag = batch["name"].removesuffix(".html")

    print("  [prompt 1] importing...")
    started = datetime.now()
    out1, session_id = call_claude(
        build_prompt1(batch, units_dir), events_log, tag=f"{tag}/prompt1"
    )
    ended = datetime.now()
    log_record(log, batch, 1, started, ended, session_id, out1)
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
    log_record(log, batch, 2, started, ended, session_id, out2)
    print(f"  [prompt 2] done ({round((ended - started).total_seconds(), 1)}s)")
    print(f"  {_truncate(out2, 300)}")



def check_order(base=None):
    """Cross-letter order: in each file, the Letters' blocks (all appended after the files'
    BASE content) must follow letter number, then source position. Letters run out of
    sequence (the pilot) break it. With `base`, reorder only those appended blocks, by cutting
    the file text, and assert the BASE content stays a byte-identical prefix. Returns the files
    out of order (before any fix)."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    block_re = re.compile(r"(?m)^\[\[commentary\]\][ \t]*$")
    url_key = {source_url_for(w): k for k, w in WORKS.items()}
    sources = {}

    def pos(k, quote):
        if k not in sources:
            secs = load_work(WORKS[k])[1]
            sources[k] = _norm(" ".join(" ".join(paragraphs_of(s)) for s in secs))
        return sources[k].find(_norm(quote))

    bad = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml") or fn == "metadata.toml":
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if "Basil%2520of%2520Caesarea%2FLetters%2F" not in text:
            continue
        starts = [m.start() for m in block_re.finditer(text)]
        blocks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
        parsed = tomllib.loads(text)["commentary"]
        assert len(parsed) == len(blocks), fn
        keys = [(WORKS[url_key[c["source_url"]]]["number"],
                 pos(url_key[c["source_url"]], c["quote"]))
                if c.get("source_url") in url_key else None for c in parsed]
        mine = [i for i, k in enumerate(keys) if k]
        if not mine:
            continue
        if mine != list(range(mine[0], len(blocks))):
            print(f"  NOT APPENDED AT THE END: {fn}")
            bad.append(fn)
            continue
        order = sorted(mine, key=lambda i: keys[i])
        if order == mine:
            continue
        print(f"  OUT OF LETTER ORDER: {fn[:-5]} {[keys[i] for i in mine]}")
        bad.append(fn)
        if base:
            new = text[:starts[mine[0]]] + "".join(
                blocks[i].rstrip("\n") + "\n\n" for i in order)
            new = new.rstrip("\n") + "\n"
            old = subprocess.run(["git", "-C", PROJECT_DIR, "show",
                                  f"{base}:{FATHER}/{fn}"], capture_output=True, text=True).stdout
            assert new.startswith(old.rstrip("\n")), fn
            assert tomllib.loads(new)["commentary"] == (
                parsed[:mine[0]] + [parsed[i] for i in order]), fn
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print("    reordered")
    print(f"{len(bad)} file(s) out of letter order" + (" (fixed)" if base and bad else ""))
    return bad


def expand_works(specs):
    """Letter keys from the arguments: keys ("BasLet005") and ranges ("BasLet005-BasLet020")."""
    keys = list(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown letter {spec!r} (keys BasLet001 .. BasLet366; see --list)")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def expand_batches(specs, batches):
    """Pieces from the arguments: "B007", "B007_L041-046.html", ranges "B007-B012"."""
    ids = [b["name"][:4] for b in batches]
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        a, b = a[:4], b[:4]
        if a not in ids or (b and b not in ids):
            raise SystemExit(f"unknown piece {spec!r} (B001 .. {ids[-1]}; see --list)")
        out += batches[ids.index(a):ids.index(b) + 1] if b else [batches[ids.index(a)]]
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "specs", nargs="*",
        help="Pieces to run, one after another (B007, B007-B012), or, with --check/--order, "
             "letters (BasLet005, BasLet005-BasLet020).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="List every piece and its letters.")
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folder and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true",
                      help="Run only the check of these letters (printing only failures when "
                           "several).")
    mode.add_argument("--order", action="store_true",
                      help="Check that every file holds the Letters' blocks in letter order "
                           "(any letter argument; all files are checked).")
    mode.add_argument("--fix-order", metavar="BASE",
                      help="As --order, and reorder the out-of-order files' appended blocks, "
                           "keeping their content at BASE (the deletion commit) unchanged.")
    args = parser.parse_args()
    if args.order or args.fix_order:
        sys.exit(1 if check_order(args.fix_order) and not args.fix_order else 0)
    if args.check:
        keys = expand_works(args.specs or [f"{next(iter(WORKS))}-{list(WORKS)[-1]}"])
        bad = [k for k in keys
               if run_check(WORKS[k], load_work(WORKS[k])[1], quiet=len(keys) > 1)]
        print(f"\n{len(keys) - len(bad)} of {len(keys)} letter(s) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    batches = make_batches()
    if args.list:
        for b in batches:
            print(f"  {b['name']:<26} {batch_size(b):>6} chars  {'; '.join(_contents(b))}")
        print(f"{len(batches)} pieces, {len(WORKS)} letters")
        return
    if args.split_only and not args.specs:
        print(f"Wrote {len(batches)} piece(s) to {write_batches(batches)}")
        return
    if not args.specs:
        parser.error("name the pieces to run (see --list)")
    run = expand_batches(args.specs, batches)

    print(f"Work:       {FATHER}, Letters ({len(run)} piece(s))")
    print(f"Agent cwd:  {PROJECT_DIR}")
    for b in run:
        print(f"  {b['name']:<26} {batch_size(b):>6} chars  {'; '.join(_contents(b))}")

    if args.dry_run:
        print(f"\n--dry-run: prompt 1 for {run[0]['name']}:\n")
        print(build_prompt1(run[0], BATCH_UNITS_DIR))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    if args.split_only:
        print(f"Wrote {len(batches)} piece(s) to {write_batches(batches)}")
        return

    log_dir = os.path.join(WORK_DIR, "basil_letters_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    failed = []
    units_dir = write_batches(batches)
    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for b in run:
            try:
                process_unit(b, units_dir, log, events_log)
            except RuntimeError as exc:
                print(f"  ABORTING at {b['name']}: {exc}")
                print(f"  (pieces kept in {units_dir})")
                log.write(json.dumps({"unit": b["name"], "error": str(exc)}) + "\n")
                log.flush()
                sys.exit(1)
            # Check each letter once its last piece has run.
            for k, _, _ in b["letters"]:
                if not b["part"] or b["part"][0] == b["part"][1]:
                    if run_check(WORKS[k], load_work(WORKS[k])[1], quiet=True):
                        failed.append(k)
    shutil.rmtree(units_dir)

    print(f"\nDone. {len(run)} piece(s) processed.")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")
    if failed:
        print(f"CHECK FAILED for: {', '.join(failed)} (see above)")
    else:
        print("Every letter of these pieces passes the check.")


if __name__ == "__main__":
    main()
