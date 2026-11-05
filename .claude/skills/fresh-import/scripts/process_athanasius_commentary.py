#!/usr/bin/env python3
"""Import the Scripture commentary in the Letters of Athanasius (the Festal Letters and the
Personal Letters, NPNF 2nd series vol. 4, 1892, public domain) into the Commentaries-Database,
one letter at a time, by driving a headless ``claude`` agent.

A per-father copy of process_damascene_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, splitting and --check, and the multi-work
command line of process_augustine_commentary.py. The letters are not a verse-by-verse
commentary but Paschal exhortations, doctrinal letters and correspondence that quote and expound
Scripture throughout, so the import is SELECTIVE (WORKS "selective": True): the agents read
every letter and file only the stretches that genuinely expound a verse.

Each letter is its own file in the Writings-Database, with its own url, so each is its own
WORKS entry ("AthLet01" .. "AthLet64", by the letter's number; the editor's introduction file,
"Letters of Athanasius with Two Ancient Chronicles of His Life.html", gets none):

    Writings-Database/Athanasius of Alexandria/Letters of Athanasius/Letter 1 For 329.html

    <h1>Letter 1 For 329</h1>
    <i>For 329. Easter-day xi Pharmuthi; ...</i><br/><br/>     (the heading line)
    Come, my beloved, ...<sup><a href="#fn1" id="r1">1</a></sup> ...<br/><br/>
    2. And, on this account, ...                             (NPNF section numbers)
    <section class="notes"><hr/><span id="fn1">... Mal. iv. 2 ...</span> ...

``load_work`` gives one section per NPNF section number ("2." opening a paragraph; the text
before "2." is Section 1), or one section for a letter without numbers ("whole letter"), or,
for the fragment collections of Letters 28 and 29, one per fragment (cut at "Another
Fragment."). The numbers and fragment headings are dropped from the text; the pieces show
them as ``<h2>`` headings. The heading line(s) under the <h1> are the preamble (background
for the agent, not text). Editorial matter is dropped from both (DROP_PARAS, and the work's
``drop_paras``, ``cut_from`` and ``strip``): the Syriac scribes' rubrics ("Here endeth the
first Festal Letter ...", "There is no twelfth Letter."), the narrative framing Letters 50,
57 and 58, Jovian's letter and the Arians' petitions printed with Letter 56, the editor's
Memorandum after Letter 64. The footnotes (mostly Scripture references) are shown inline as
``<sup>[note: Mal. iv. 2.]</sup>`` hints and dropped from the body.

    python3 process_athanasius_commentary.py AthLet01 --dry-run
    python3 process_athanasius_commentary.py AthLet01 AthLet10-AthLet14   # run these letters
    python3 process_athanasius_commentary.py AthLet01-AthLet64 --check
    python3 process_athanasius_commentary.py AthLet01 --order             # all files: letter order
    python3 process_athanasius_commentary.py AthLet01 --fix-order BASE    # ... and fix it
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

FATHER = "Athanasius of Alexandria"

# A piece holds consecutive sections up to about this many html chars (only Letters 10 and
# 11 are bigger, and are cut at section boundaries).
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

LETTERS_DIR = "Athanasius of Alexandria/Letters of Athanasius"

# (number, file name, source_title, kind, label, extra settings). `label` names the units
# a letter is cut into ("Section" for NPNF's numbers, "Fragment" for 28 and 29, None for a
# letter without numbers); load_work refuses a letter whose numbers don't fit it.
# Extra settings: `head` = how many paragraphs under the <h1> are heading matter (default 1,
# the italic heading line); `drop_paras` = regexes, a paragraph whose plain text starts with
# one is dropped; `cut_from` = a regex, the paragraph whose plain text starts with it and
# everything after are dropped; `strip` = regexes removed from the raw html. Each must match.
_LETTERS = [
    (1, "Letter 1 For 329", "Festal Letter 1 (for 329)", "festal", "Section",
     # "Of Fasting, and Trumpets, and Feasts.": the Syriac MS's title of the letter.
     {"head": 2}),
    (2, "Letter 2 For 330", "Festal Letter 2 (for 330)", "festal", "Section", {}),
    (3, "Letter 3 For 331", "Festal Letter 3 (for 331)", "festal", "Section", {}),
    (4, "Letter 4 For 332", "Festal Letter 4 (for 332)", "festal", "Section",
     # "He sent this Letter from the Emperor’s Court by a soldier."
     {"head": 2}),
    (5, "Letter 5 For 333", "Festal Letter 5 (for 333)", "festal", "Section", {}),
    (6, "Letter 6 For 334", "Festal Letter 6 (for 334)", "festal", "Section", {}),
    (7, "Letter 7 For 335", "Festal Letter 7 (for 335)", "festal", "Section", {}),
    (10, "Letter 10 For 338", "Festal Letter 10 (for 338)", "festal", "Section", {}),
    (11, "Letter 11 For 339", "Festal Letter 11 (for 339)", "festal", "Section", {}),
    (12, "Letter 12 (Probably for 340 ad)", "Festal Letter 12 (probably for 340)", "festal",
     "Section", {}),
    (13, "Letter 13 (for 341)", "Festal Letter 13 (for 341)", "festal", "Section", {}),
    (14, "Letter 14 (for 342)", "Festal Letter 14 (for 342)", "festal", "Section", {}),
    (17, "Letter 17 (for 345)", "Festal Letter 17 (for 345)", "festal", None, {}),
    (18, "Letter 18 (for 346)", "Festal Letter 18 (for 346)", "festal", None, {}),
    (19, "Letter 19 (for 347)", "Festal Letter 19 (for 347)", "festal", "Section", {}),
    (20, "Letter 20 (for 348)", "Festal Letter 20 (for 348)", "festal", "Section", {}),
    (22, "From Letter 22 (for 350)", "Festal Letter 22 (for 350)", "festal", None, {}),
    (24, "From Letter 24 (for 352)", "Festal Letter 24 (for 352)", "festal", None, {}),
    (27, "From Letter 27 (for 355)", "Festal Letter 27 (for 355)", "festal", None, {}),
    (28, "From Letter 28 (for 356)", "Festal Letter 28 (for 356)", "festal", "Fragment", {}),
    (29, "From Letter 29 (for 357)", "Festal Letter 29 (for 357)", "festal", "Fragment",
     # The Latin "Filiis suis" (the third fragment) opens with its MS rubric.
     {"strip": [r"<i>Here begins a letter of S\. Athanasius, Bishop of Alexandria, to his "
                r"children\.</i> "]}),
    (39, "From Letter 39 (for 367)", "Festal Letter 39 (for 367)", "festal", "Section", {}),
    (40, "From Letter 40 (for 368)", "Festal Letter 40 (for 368)", "festal", None, {}),
    (42, "From Letter 42 (for 370)", "Festal Letter 42 (for 370)", "festal", None, {}),
    (43, "From Letter 43 (for 371)", "Festal Letter 43 (for 371)", "festal", None, {}),
    (44, "From Letter 44 (for 372)", "Festal Letter 44 (for 372)", "festal", None, {}),
    (45, "From Letter 45 (for 373)", "Festal Letter 45 (for 373)", "festal", None, {}),
    (46, "Letter 46 Letter To the Mareotis from Sardica, ad 343-4",
     "Letter 46, To the Mareotis from Sardica", "personal", None, {}),
    (47, "Letter 47 To the Church of Alexandria on the Same Occasion",
     "Letter 47, To the Church of Alexandria", "personal", None, {}),
    (48, "Letter 48 Letter to Amun Written Before 354 ad", "Letter 48, To Amun", "personal",
     None, {}),
    (49, "Letter 49 Letter to Dracontius Written ad 354 or 355", "Letter 49, To Dracontius",
     "personal", "Section", {}),
    (50, "Letter 50 First Letter to Lucifer", "Letter 50, First Letter to Lucifer", "personal",
     None, {"drop_paras": [r"Upon receiving this letter, blessed Lucifer sent the books"]}),
    (51, "Letter 51 Second Letter to Lucifer", "Letter 51, Second Letter to Lucifer",
     "personal", None, {}),
    (52, "Letter 52 First Letter to Monks (Written 358-360)", "Letter 52, First Letter to Monks",
     "personal", "Section", {}),
    (53, "Letter 53 Second Letter To Monks", "Letter 53, Second Letter to Monks", "personal",
     None, {}),
    (54, "Letter 54 To Serapion, Concerning the Death of Arius",
     "Letter 54, To Serapion, Concerning the Death of Arius", "personal", "Section", {}),
    (55, "Letter 55 Letter to Rufinianus", "Letter 55, To Rufinianus", "personal", None, {}),
    (56, "Letter 56 To the Emperor Jovian", "Letter 56, To the Emperor Jovian", "personal",
     "Section",
     # Jovian's letter to Athanasius and the heading of the reply; the Arians' petitions.
     {"drop_paras": [r"Copy of a letter of the Emperor Jovian",
                     r"To the most religious and friend of God, Athanasius, Jovian\.",
                     r"Admiring exceedingly the achievements of your most honourable life",
                     r"56\. Letter of Athanasius to Jovian concerning the Faith\."],
      "cut_from": r"Appendix to Letter LVI\."}),
    (57, "Letter 57 First Letter to Orsisius", "Letter 57, First Letter to Orsisius",
     "personal", None,
     # The Life of Pachomius's narrative that frames the letter.
     {"head": 2}),
    (58, "Letter 58 Second Letter to Orsisius", "Letter 58, Second Letter to Orsisius",
     "personal", None, {"head": 2}),
    (59, "Letter 59 To Epictetus", "Letter 59, To Epictetus", "personal", "Section", {}),
    (60, "Letter 60 To Adelphius, Bishop and Confessor: Against the Arians",
     "Letter 60, To Adelphius", "personal", "Section", {}),
    (61, "Letter 61 Letter to Maximus (Written About 371 ad)", "Letter 61, To Maximus",
     "personal", "Section", {}),
    (62, "Letter 62 To John and Antiochus", "Letter 62, To John and Antiochus", "personal",
     None, {}),
    (63, "Letter 63 Letter to the Presbyter Palladius", "Letter 63, To the Presbyter Palladius",
     "personal", None, {}),
    (64, "Letter 64 To Diodorus (Fragment)", "Letter 64, To Diodorus", "personal", None,
     {"cut_from": r"Memorandum\.—On other Letters ascribed to Athanasius\."}),
]

# Per-letter notes for the agents (added to the general notes of its kind).
_NOTES = {
    1: ("The second heading line, \"Of Fasting, and Trumpets, and Feasts.\", is the Syriac "
        "MS's title of the letter, not text."),
    4: ("The second heading line, \"He sent this Letter from the Emperor’s Court by a "
        "soldier.\", is the Syriac editor's note, not text."),
    28: ("This file holds two fragments quoted by Cosmas Indicopleustes, each its own <h2> "
         "(\"Fragment 1.\", \"Another Fragment. (= Fragment 2)\"). They are not continuous "
         "text: never run a block from one fragment into the next."),
    29: ("This file holds three separate fragments, each its own <h2>: Fragment 1 and 2 from "
         "Cosmas, and Fragment 3 the Latin letter \"to his children\" (Filiis suis), which "
         "the editor conjecturally placed here (its Latin MS rubric has been removed). They "
         "are not continuous text: never run a block from one fragment into the next. In "
         "Fragment 3, \"(After a little:)\" is the excerptor's mark of an omission: keep it "
         "as printed if it falls inside a block."),
    39: ("Sections 1 and 2 are separate fragments (Section 1 from the Coptic Life of S. "
         "Theodore, Section 2 opening the Greek text preserved by Balsamon); each opens with "
         "an ellipsis (\"…\") that is part of the printed text. Sections 4-7 are Athanasius's "
         "list of the canonical books: the list itself is not commentary on a verse, though "
         "his comments on particular Scriptures around it may be."),
    52: ("Section 1 opens with the letter's address (\"To those in every place who are "
         "living a monastic life ...\"), then the letter itself."),
    56: ("Only Athanasius's reply is given here (Jovian's letter to him, printed before it, and "
         "the Arians' petitions printed after it as an appendix, have been removed). Section "
         "3, \"We believe, &c., &c.\", stands for the Nicene Creed, which the edition does not "
         "reprint."),
    57: ("The second heading line, a narrative from the Life of Pachomius that introduces the "
         "letter (\"And having spent a few days there ...\"), is background, not text."),
    58: ("The second heading line, a narrative from the Life of Pachomius that introduces the "
         "letter (\"But the most holy Archbishop Athanasius, when he heard about our father "
         "Theodorus ...\"), is background, not text."),
}

WORKS = {
    f"AthLet{no:02d}": {
        "html": f"{LETTERS_DIR}/{fn}.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        "kind": kind,
        "number": no,
        "label": label,
        # "Festal Letter 1 (for 329), Section 2"; "Letter 59, To Epictetus, Sections 5-6" (as
        # the old url'd block had it); a letter without numbers has no suffix.
        "source_title": title,
        "notes": _NOTES.get(no, ""),
        **extra,
    }
    for no, fn, title, kind, label, extra in _LETTERS
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
    the url'd blocks of the old import ("file=Athanasius%2520of%2520Alexandria%2FLetters...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"athanasius_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
PARA_SPLIT_RE = re.compile(r"(?:<br\s*/?>\s*){2,}")
# An NPNF section number opening a paragraph ("2. And, on this account"; Letter 39's
# fragments "…1. They have").
SECTION_NO_RE = re.compile(r"(…?)(\d+)\.\s+")
FRAGMENT_RE = re.compile(r"Another Fragment\.")
# The Syriac scribes' rubrics and notes at the end of the Festal Letters (plain text, notes
# removed, matched at the paragraph start).
DROP_PARAS = [
    r"Here endeth the ",
    r"There is no eighth or ninth, for he did not send them",
    r"He wrote this (?:also )?from Rome\.",
    r"The fifteenth and sixteenth are wanting\.",
]


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _plain(p):
    """A paragraph's plain text without its note marks."""
    return _clean(FOOTNOTE_REF_RE.sub("", p))


def chapter_title(work, chapters):
    """The source_title for a block from these section numbers."""
    if not work["label"]:
        return work["source_title"]
    a, b = min(chapters), max(chapters)
    return (f"{work['source_title']}, {work['label']} {a}" if a == b
            else f"{work['source_title']}, {work['label']}s {a}-{b}")


def load_work(work):
    """Return (preamble_html, sections): one section per NPNF section (or fragment, or the
    whole letter). A section's heading is "Section 2" / "Fragment 2" / "whole letter", its html
    the section as the agent sees it (an <h2> with the number, the text, the footnotes inline as
    [note: ...] hints), its body the text without number and notes, `chapter` None (there are
    no verse sections) and `chapter_no` its number."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    for rx in work.get("strip", []):
        text, n = re.subn(rx, "", text)
        if not n:
            raise SystemExit(f"{work['html']}: strip pattern matched nothing: {rx!r}")
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(text)])

    def hinted(s):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""), s)

    head, rest = text.split("</h1>", 1)
    rest = rest.replace("</article>", "")
    paras = [p.strip() for p in PARA_SPLIT_RE.split(rest)]
    paras = [p for p in paras if p]
    nhead = work.get("head", 1)
    if not paras[0].startswith("<i>"):
        raise SystemExit(f"{work['html']}: no italic heading line: {paras[0][:100]!r}")
    preamble = (hinted(head) + "</h1>\n"
                + "".join(hinted(p) + "<br/><br/>\n" for p in paras[:nhead]))

    used = set()
    keep = []
    cut = work.get("cut_from")
    for p in paras[nhead:]:
        plain = _plain(p)
        if cut and re.match(cut, plain):
            used.add(cut)
            break
        rxs = [rx for rx in work.get("drop_paras", []) + DROP_PARAS if re.match(rx, plain)]
        if rxs:
            used.update(rxs)
            continue
        keep.append(p)
    for rx in work.get("drop_paras", []) + ([cut] if cut else []):
        if rx not in used:
            raise SystemExit(f"{work['html']}: pattern matched no paragraph: {rx!r}")

    label = work["label"]
    sections, cur = [], None

    def start(no, h2):
        sections.append({"heading": f"{label} {no}" if label else "whole letter",
                         "chapter": None, "chapter_no": no, "h2": h2, "paras": []})

    for p in keep:
        plain = _plain(p)
        if label == "Fragment" and FRAGMENT_RE.fullmatch(plain):
            start(len(sections) + 1, f"<h2>{hinted(p)} (= Fragment {len(sections) + 1})</h2>\n")
            continue
        sm = SECTION_NO_RE.match(p)
        if sm:
            if label != "Section":
                raise SystemExit(f"{work['html']}: a section number in a letter labelled "
                                 f"{label}: {plain[:80]!r}")
            n = int(sm.group(2))
            last = sections[-1]["chapter_no"] if sections else 0
            # (Unnumbered text before "2." has already started Section 1 below.)
            if n == last + 1:
                start(n, f"<h2>Section {n}.</h2>\n")
            elif n != last:
                raise SystemExit(f"{work['html']}: section {n} after {last}: {plain[:80]!r}")
            p = sm.group(1) + p[sm.end():]
        elif not sections:
            # (A letter without numbers gets an <h2> too, marking where its text starts.)
            start(1, f"<h2>{label} 1.</h2>\n" if label else "<h2>The letter.</h2>\n")
        sections[-1]["paras"].append(p)

    for s in sections:
        raw = "<br/><br/>\n".join(s.pop("paras")) + "\n"
        s["html"] = s.pop("h2") + hinted(raw)
        s["body"] = FOOTNOTE_REF_RE.sub("", raw)
    nos = [s["chapter_no"] for s in sections]
    if nos != list(range(1, len(nos) + 1)):
        raise SystemExit(f"{work['html']}: sections are not numbered 1..n: {nos}")
    if (len(nos) > 1) != bool(label):
        raise SystemExit(f"{work['html']}: {len(nos)} section(s) but label {label!r}")
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


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have Athanasius's \"{title}\" here: \"{units_dir}/{first_unit}\"{more_units}. "
    "{piece_word} our PUBLIC-DOMAIN English translation of the Letters (Nicene and "
    "Post-Nicene Fathers, 2nd series, vol. 4, 1892), \"{html_path}\" (consult it if you need "
    "surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. {about} Your task is to EXTRACT from the "
    "letter the stretches that are genuinely commentary on a specific verse of Scripture, and "
    "file each under that verse in the \"{father}/\" folder. Much of the text will NOT be "
    "imported, and that is expected: a letter (or section) with no exposition of a verse gives "
    "no block.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the letter's title and heading line(s) at the top "
    "(the date, the Syriac editor's or the narrator's heading); that is background for you, not "
    "text to import.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Athanasius QUOTES or "
    "plainly refers to a specific verse AND DOES SOMETHING WITH IT: says what it means, "
    "interprets its words (literally, morally or spiritually), resolves a difficulty in it, "
    "applies a figure or type in it (\"by the ... is meant ...\", \"this was a figure of "
    "...\", the Passover lamb, the feasts and trumpets of the Law, Israel's going out of "
    "Egypt), builds his argument on its wording (e.g. a doctrinal point against the Arians "
    "drawn from how a verse is phrased), or APPLIES it to the keeping of the feast or to the "
    "Christian life in a way that shows how he reads it (a verse brought in to describe the "
    "true fast or the true feast, and then drawn out). Do NOT import a verse quoted only in "
    "passing, a bare proof-text dropped into a sentence, a chain of proof-texts quoted without "
    "comment, or exhortation, news and church business that merely mentions Scripture. Ask: "
    "would a reader studying this verse learn something about how Athanasius understood or "
    "used it from this stretch? If so, import it; if it would only learn that Athanasius "
    "quoted it, leave it out.\n\n"
    "VERSE KEYS. The editors' footnotes are shown inline as \"[note: ...]\" in superscript, "
    "after the word they mark. Many give the reference of a quotation (\"Mal. iv. 2.\", \"Ps. "
    "lxxxi. 3, cf. Num. x. 8.\", \"Cf.\" = an allusion); others discuss the Syriac, the dates or "
    "the persons and give no verse. The notes' Psalm numbers are the English (KJV) ones "
    "(\"LXX\" after one means Athanasius follows the Septuagint's wording). A note can sit on "
    "the wrong quotation, or be missing. Use the notes as HINTS only, and confirm every verse "
    "against the KJV wording with `" + KJV_LOOKUP + "`, filing under KJV book/chapter/verse "
    "numbering. Athanasius quotes the Greek Bible (the Septuagint for the Old Testament), "
    "{syriac}so his wording often differs from the KJV's, and the Septuagint verse division "
    "sometimes differs too: match by sense. Deuterocanonical books are fine (\"Sirach\", "
    "\"Wisdom\", \"Baruch\", ...): use only the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Athanasius's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the verse and the whole of his exposition of it. "
    "Don't pad a block with unrelated exhortation before or after "
    "the exposition. File it under the SMALLEST verse range the exposition really addresses: a "
    "single verse when it expounds one verse, a range only when it expounds several verses as "
    "one argument (a range crossing chapters is written like \"Matthew 5_48-6_1\"). When one "
    "stretch genuinely expounds two different passages (e.g. an Old Testament type and the "
    "Gospel verse that fulfils it, interpreted together), file the same text under each, as "
    "separate files; that is welcome. "
    "But never put two overlapping blocks of this letter in the SAME file, and don't split "
    "one exposition into fragments under one verse.\n\n"
    "THE TEXT. Copy Athanasius's words VERBATIM: nothing abridged, paraphrased, corrected, "
    "added or rearranged. Drop the html tags (italics simply become plain text; don't turn "
    "them into quotation marks) and separate paragraphs with a single blank line. Leave out "
    "the \"[note: ...]\" footnotes and the <h2> headings (\"Section 2.\"): the editors' "
    "section numbers have already been removed from the text, so a paragraph that opened "
    "\"2. And, on this account\" in the printed book reads \"And, on this account\" here, and "
    "so it must in your block. Keep the translators' square-bracketed supplements (\"on the "
    "[solemn] day\") and parenthesised dates and remarks (\"(Feb. 17)\") as printed, and the "
    "printed text's quotation marks (‘ ’ “ ”), dashes, ellipses (…), Greek words, "
    "run-together words and misprints as they are. Don't add headings, verse numbers or notes "
    "of your own. Don't write a python script to do this; process the file yourself "
    "manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this letter, set:\n"
    "  source_url   = {source_url}\n"
    "{title_rule}\n\n"
    "EXISTING BLOCKS. The old imports of these letters have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (other letters of Athanasius, or earlier "
    "sections of this one) may already have left blocks from his Letters in the files you "
    "write to: they are NOT old imports or duplicates; leave them exactly as they are and "
    "append yours after them. Blocks from other works (the Discourses against the Arians, On "
    "the Incarnation, the Life of Antony, the Letters to Serapion, the Catena Aurea, ...) "
    "must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- section, opening "
    "words), and every exposition of a verse you considered but left out, with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


KIND_ABOUT = {
    "festal": (
        "It is one of Athanasius's Festal (Easter) Letters: each year the bishop of Alexandria "
        "wrote to the churches of Egypt announcing the dates of the Lenten fast and of Easter, "
        "with an exhortation to keep the feast worthily. They are full of Scripture, often "
        "expounded as type and figure (the Passover and the feasts of the Law, Israel's going "
        "out of Egypt, the true fast and the true feast), and against the Arians and Meletians. "
        "Most survive only in a Syriac version, from which this translation was made; some only "
        "as fragments quoted by later writers."),
    "personal": (
        "It is one of Athanasius's personal letters (to bishops, monks, a philosopher, an "
        "emperor, his church), on doctrine against the Arians, on the monastic life, or on "
        "church affairs, quoting Scripture constantly."),
}


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    if work["label"]:
        lab = work["label"]
        title_rule = (
            f"  source_title = \"{work['source_title']}, {lab} N\"\n"
            f"where N is the number of the {lab.lower()} the block comes from (the <h2> "
            f"headings), e.g. \"{work['source_title']}, {lab} 2\"; a block running across "
            f"{lab.lower()}s is \"{work['source_title']}, {lab}s 2-3\".")
    else:
        title_rule = (f"  source_title = \"{work['source_title']}\"\n"
                      "(this letter has no section numbers, so the title has no suffix).")
    return PROMPT1_TEMPLATE.format(
        title=work["source_title"],
        about=KIND_ABOUT[work["kind"]],
        syriac=("through the Syriac translator, " if work["kind"] == "festal" else ""),
        units_dir=units_dir,
        first_unit=units[0]["name"],
        more_units=(f" with the files continuing up to \"{units_dir}/{units[-1]['name']}\""
                    if len(units) > 1 else ""),
        piece_word=("These are consecutive pieces cut, in order, from" if len(units) > 1
                    else "It is the whole letter, from"),
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        father=FATHER,
        # (The driver passes the name tagged with the letter, "AthLet11/Part002_...".)
        unit_name=os.path.basename(unit["name"]),
        headings=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        title_rule=title_rule,
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
        # (The agents of this run created 42 files opening with a blank line.)
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
        for no in sorted(per_chapter):
            print(f"  {sections[no - 1]['heading']}: {', '.join(per_chapter[no])}")
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
        if "Letters%2520of%2520Athanasius" not in text:
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
    """Work keys from the arguments: keys ("AthLet05") and ranges ("AthLet05-AthLet20")."""
    keys = sorted(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown work {spec!r} (keys: {', '.join(keys)})")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "works", nargs="+",
        help="Letters to import, run one after another (every piece of each): keys (AthLet05) "
             "and/or ranges (AthLet05-AthLet20).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folders and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true",
                      help="Run only the check (printing only failures when several works).")
    mode.add_argument("--order", action="store_true",
                      help="Check that every file holds the Letters' blocks in letter order "
                           "(any works argument; all files are checked).")
    mode.add_argument("--fix-order", metavar="BASE",
                      help="As --order, and reorder the out-of-order files' appended blocks, "
                           "keeping their content at BASE (the deletion commit) unchanged.")
    args = parser.parse_args()
    if args.order or args.fix_order:
        sys.exit(1 if check_order(args.fix_order) and not args.fix_order else 0)
    keys = expand_works(args.works)

    loaded = {}
    for k in keys:
        pre, secs = load_work(WORKS[k])
        loaded[k] = (pre, secs, make_units(pre, secs, SPLIT_CHARS))

    if args.check:
        bad = [k for k in keys if run_check(WORKS[k], loaded[k][1], quiet=len(keys) > 1)]
        print(f"\n{len(keys) - len(bad)} of {len(keys)} letter(s) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    print(f"Work:       {FATHER}, Letters ({len(keys)} letter(s))")
    print(f"Agent cwd:  {PROJECT_DIR}")
    for k in keys:
        pre, secs, units = loaded[k]
        for u in units:
            size = sum(len(s["html"]) for s in u["sections"])
            print(f"  {k}  {u['name']:<22} {size:>6} chars  "
                  f"{', '.join(s['heading'] for s in u['sections'])}")

    if args.dry_run:
        k = keys[0]
        pre, secs, units = loaded[k]
        print(f"\nSource url: {source_url_for(WORKS[k])}")
        print(f"\n--dry-run: prompt 1 for {k} {units[0]['name']}:\n")
        print(build_prompt1(WORKS[k], units_dir_for(k), units, units[0]))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    if args.split_only:
        for k in keys:
            pre, secs, units = loaded[k]
            print(f"Wrote {len(units)} piece(s) to {write_units(k, pre, units)}")
        return

    log_dir = os.path.join(WORK_DIR, "athanasius_letters_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    failed = []
    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for k in keys:
            pre, secs, units = loaded[k]
            units_dir = write_units(k, pre, units)
            for unit in units:
                # The log's unit names carry the letter ("AthLet11/Part002_S08-15.html").
                tagged = dict(unit, name=f"{k}/{unit['name']}")
                try:
                    process_unit(WORKS[k], units_dir, units, tagged, log, events_log)
                except RuntimeError as exc:
                    print(f"  ABORTING at {k} ({unit['name']}): {exc}")
                    print(f"  (pieces kept in {units_dir})")
                    log.write(json.dumps({"unit": tagged["name"], "error": str(exc)}) + "\n")
                    log.flush()
                    sys.exit(1)
            shutil.rmtree(units_dir)
            if run_check(WORKS[k], secs):
                failed.append(k)

    print(f"\nDone. {len(keys)} letter(s) processed.")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")
    if failed:
        print(f"CHECK FAILED for: {', '.join(failed)} (see above)")


if __name__ == "__main__":
    main()
