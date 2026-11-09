#!/usr/bin/env python3
"""Import the Scripture commentary in the Sermons of Leo the Great (Charles Lett Feltoe's
translation, NPNF 2nd series vol. 12, 1895, public domain) into the Commentaries-Database by
driving a headless ``claude`` agent over pieces that each hold a run of consecutive sermons.

A per-father copy of process_basil_letters_commentary.py (see ../SKILL.md, "Other fathers" and
"Selective works") with the same two-prompt flow, --check and --order/--fix-order. The sermons
are festal and fast-day sermons (Christmas, Epiphany, Lent, the Passion, Easter, Ascension,
Whitsun, the Ember fasts, the collections, the apostles' feasts, his own anniversary), so the
import is SELECTIVE (WORKS "selective": True): the agents read every sermon and file only the
stretches that genuinely expound a verse.

Each sermon is its own file in the Writings-Database (the NPNF selection of 48), with its own
url, so each is its own WORKS entry ("LeoSer001" .. "LeoSer095", by the sermon's number), built
by scanning the folder.

    Writings-Database/Leo the Great/Sermons/Sermon 95 A Homily on the Beatitudes, St Matt 5 1-9.html

    <h1>Sermon 95 ...<sup>1</sup></h1>          (a note on the title sometimes sits on the h1)
    <h2>I. Introduction of the subject.</h2>     (the editor's chapter summaries)
    When our Lord Jesus Christ ...<br/><br/>
    <h2>II. The blessedness of humility discussed.</h2> ...
    <section class="notes"><hr/><span id="fn1">... S. Matt. iv. 23-25.</span> ...

``load_work`` gives one section per <h2> chapter, or one section for Sermon 1, which has no
chapters (its italic summary line under the <h1> is heading matter, like the <h2> summaries).
The pieces show each chapter as ``<h2>Chapter N: summary</h2>``; the summaries are the editor's
and are not text. The footnotes (Scripture references, Latin readings, notes on the doctrine and
the occasion) are shown inline as ``<sup>[note: S. Matt. v. 6.]</sup>`` hints and dropped from
the body.

A run is made of PIECES (the user's choice): ``make_batches`` packs consecutive sermons, in
number order, into pieces of up to SPLIT_CHARS html chars ("B007_S039-042.html"); a sermon
bigger than that would be cut at chapter boundaries into pieces of its own
("B010_S095_C01-05.html"; none is, at 25k). The packing is global and deterministic, so piece
names don't depend on what a run selects.

    python3 process_leo_commentary.py B001 --dry-run
    python3 process_leo_commentary.py B001 B010-B014      # run these pieces
    python3 process_leo_commentary.py --list               # all pieces and sermons
    python3 process_leo_commentary.py LeoSer001-LeoSer095 --check
    python3 process_leo_commentary.py LeoSer001 --order      # all files: sermon order
    python3 process_leo_commentary.py LeoSer001 --fix-order BASE   # ... and fix it
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

FATHER = "Leo the Great"

# A piece packs consecutive sermons up to about this many html chars (inline notes included); a
# bigger sermon would be cut at chapter boundaries into pieces of its own.
SPLIT_CHARS = 25000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

SERMONS_DIR = "Leo the Great/Sermons"
# The url substring every Sermons block carries (for --order).
URL_MARK = "Leo%2520the%2520Great%2FSermons%2F"

# Per-sermon settings: `head` = how many paragraphs under the <h1> are heading matter (default
# 0; Sermon 1's italic summary line); `strip` = regexes removed from the raw html (each must
# match).
EXTRA = {
    1: {"head": 1},
}

# Per-sermon notes for the agents.
_NOTES = {
    1: ("The sermon has no chapters; the italic line under its <h1> (\"Having been elected in "
        "absence he returns thanks ...\") is the editor's summary, not text."),
}

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
PARA_SPLIT_RE = re.compile(r"(?:<br\s*/?>\s*){2,}")
H2_RE = re.compile(r"<h2>(.*?)</h2>", re.S)
# An editor's chapter heading: "IV. The blessedness of mourning discussed."
CHAPTER_RE = re.compile(r"([IVXL]+)\.\s+(.*)", re.S)
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50}


def roman(s):
    vals = [ROMAN_VALUES[c] for c in s]
    return sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _plain(p):
    """A paragraph's plain text without its note marks."""
    return _clean(FOOTNOTE_REF_RE.sub("", p))


def _paras(s):
    return [p.strip() for p in PARA_SPLIT_RE.split(s) if p.strip()]


def _read_sermon(fn, extra):
    """(head html up to </h1>, [(h2 text or None, [paragraphs])]) of a sermon file, notes
    section removed and the sermon's `strip` patterns applied. The first chunk (h2 None) is the
    text before the first <h2>."""
    with open(os.path.join(WRITINGS_DIR, SERMONS_DIR, fn), encoding="utf-8") as f:
        text = f.read()
    m = NOTES_RE.search(text)
    if m:
        text = text[:m.start()] + text[m.end():]
    for rx in extra.get("strip", []):
        text, n = re.subn(rx, "", text)
        if not n:
            raise SystemExit(f"{fn}: strip pattern matched nothing: {rx!r}")
    head, rest = text.split("</h1>", 1)
    rest = rest.replace("</article>", "")
    parts = H2_RE.split(rest)
    chunks = [(None, _paras(parts[0]))]
    for i in range(1, len(parts), 2):
        chunks.append((parts[i].strip(), _paras(parts[i + 1])))
    return head, chunks


def _scan():
    """WORKS: one entry per sermon file, by number. Returns (works, skipped), skipped = {file
    name: reason}."""
    works, skipped = {}, {}
    for fn in os.listdir(os.path.join(WRITINGS_DIR, SERMONS_DIR)):
        m = re.fullmatch(r"Sermon (\d+) .*\.html", fn)
        if not m:
            skipped[fn] = "not a sermon's file"
            continue
        no = int(m.group(1))
        extra = EXTRA.get(no, {})
        _, chunks = _read_sermon(fn, extra)
        works[f"LeoSer{no:03d}"] = {
            "html": f"{SERMONS_DIR}/{fn}",
            # No commented book: the agents choose any book of book_names.json.
            "book": None,
            "selective": True,
            "number": no,
            "label": "Chapter" if len(chunks) > 1 else None,
            # "Sermon 95, Chapter 2" / "Sermon 95, Chapters 2-3"; Sermon 1, which has no
            # chapters, is plain "Sermon 1" (the user's choice).
            "source_title": f"Sermon {no}",
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
    the url'd blocks of the old import ("file=Leo%2520the%2520Great%2FSermons%2FSermon%252010%2520On%2520the%2520Collections%252C%25205.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"leo_{work_key.lower()}_units")


BATCH_UNITS_DIR = os.path.join(WORK_DIR, "leo_sermons_units")


# --- Parsing and splitting ----------------------------------------------------


def chapter_title(work, chapters):
    """The source_title for a block from these chapter numbers."""
    if not work["label"]:
        return work["source_title"]
    nos = [c for c in chapters if c]
    a, b = (min(nos), max(nos)) if nos else (0, 0)
    lab = work["label"]
    return f"{work['source_title']}, " + (f"{lab} {a}" if a == b else f"{lab}s {a}-{b}")


def load_work(work):
    """Return (preamble_html, sections): one section per <h2> chapter (or the whole sermon). A
    section's heading is "Chapter 2" / "whole sermon", its html the section as the agent sees it
    (an <h2> with the number and the editor's summary, the text, the footnotes inline as
    [note: ...] hints), its body the text without heading and notes, `chapter` None (there are
    no verse sections) and `chapter_no` its number."""
    fn = os.path.basename(work["html"])
    head, chunks = _read_sermon(fn, work)
    allhtml = head + "".join((h or "") + "".join(ps) for h, ps in chunks)
    hints = note_hints(work, [int(n) for n in FOOTNOTE_REF_RE.findall(allhtml)])

    def hinted(s):
        return FOOTNOTE_REF_RE.sub(
            lambda r: (f"<sup>[note: {html.escape(hints[int(r.group(1))], quote=False)}]</sup>"
                       if int(r.group(1)) in hints else ""), s)

    nhead = work.get("head", 0)
    lead = chunks[0][1]
    if nhead and not all(p.startswith("<i>") for p in lead[:nhead]):
        raise SystemExit(f"{work['html']}: no italic summary line: {lead[0][:100]!r}")
    preamble = (hinted(head) + "</h1>\n"
                + "".join(hinted(p) + "<br/><br/>\n" for p in lead[:nhead]))

    sections = []
    if work["label"]:
        if lead:
            raise SystemExit(f"{work['html']}: text before the first chapter: {lead[0][:100]!r}")
        for h2, ps in chunks[1:]:
            cm = CHAPTER_RE.fullmatch(_clean(h2))
            if not cm:
                raise SystemExit(f"{work['html']}: chapter heading without a numeral: {h2!r}")
            n = roman(cm.group(1))
            if n != len(sections) + 1:
                raise SystemExit(f"{work['html']}: chapter {n} after {len(sections)}: {h2!r}")
            if not ps:
                raise SystemExit(f"{work['html']}: empty chapter {n}")
            sections.append({"heading": f"Chapter {n}", "chapter": None, "chapter_no": n,
                             "h2": f"<h2>Chapter {n}: {html.escape(cm.group(2), quote=False)}"
                                   f"</h2>\n", "paras": ps})
    else:
        sections.append({"heading": "whole sermon", "chapter": None, "chapter_no": 1,
                         "h2": "<h2>The sermon.</h2>\n", "paras": lead[nhead:]})

    for s in sections:
        raw = "<br/><br/>\n".join(s.pop("paras")) + "\n"
        s["html"] = s.pop("h2") + hinted(raw)
        s["body"] = FOOTNOTE_REF_RE.sub("", raw)
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


# --- Pieces: runs of consecutive sermons --------------------------------------


def make_batches():
    """Every piece of the run, in sermon order: {name, sermons: [(key, preamble, sections)],
    part: (i, n) for the pieces of a sermon too big for one piece, else None}. Consecutive
    sermons are packed up to SPLIT_CHARS; the packing runs over the whole collection, so a
    piece's name and content don't depend on what a run selects."""
    batches, cur, acc = [], [], 0

    def flush():
        nonlocal cur, acc
        if cur:
            batches.append({"sermons": cur, "part": None})
        cur, acc = [], 0

    for k in WORKS:
        pre, secs = load_work(WORKS[k])
        size = len(pre) + sum(len(s["html"]) for s in secs)
        if size > SPLIT_CHARS:
            flush()
            runs = split_evenly(secs, SPLIT_CHARS) if len(secs) > 1 else [secs]
            for i, run in enumerate(runs):
                batches.append({"sermons": [(k, pre, run)], "part": (i + 1, len(runs))})
            continue
        if cur and acc + size > SPLIT_CHARS:
            flush()
        cur.append((k, pre, secs))
        acc += size
    flush()
    for i, b in enumerate(batches):
        nos = [WORKS[k]["number"] for k, _, _ in b["sermons"]]
        if b["part"]:
            secs = b["sermons"][0][2]
            b["name"] = (f"B{i + 1:03d}_S{nos[0]:03d}_C{secs[0]['chapter_no']:02d}-"
                         f"{secs[-1]['chapter_no']:02d}.html")
        else:
            b["name"] = (f"B{i + 1:03d}_S{nos[0]:03d}" + (f"-{nos[-1]:03d}" if len(nos) > 1 else "")
                         + ".html")
    return batches


def batch_html(batch):
    """A piece as the agent sees it: each sermon's <h1> (and Sermon 1's summary line) and its
    chapters."""
    out = ['<article class="writing">\n']
    for k, pre, secs in batch["sermons"]:
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
    return sum(len(pre) + sum(len(s["html"]) for s in secs) for _, pre, secs in batch["sermons"])


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have sermons of Leo the Great (Pope Leo I, bishop of Rome 440-461) here: "
    "\"{units_dir}/{unit_name}\". {piece_desc} They come from our PUBLIC-DOMAIN English "
    "translation of his Sermons (Charles Lett Feltoe, Nicene and Post-Nicene Fathers, 2nd "
    "series, vol. 12, 1895); each sermon's full source file is named below (consult it if you "
    "need surrounding context).\n\n"
    "THIS IS NOT A VERSE-BY-VERSE COMMENTARY. The Sermons are Leo's festal and fast-day "
    "sermons to the people of Rome: on his anniversary, the collections for the poor, the Ember "
    "fasts, Christmas, the Epiphany, Lent, the Passion, Easter, the Ascension, Whitsuntide, the "
    "feasts of the apostles and martyrs, with much doctrine on the two natures of Christ "
    "against the Manichees, Nestorius and Eutyches. Your task is to EXTRACT the stretches that "
    "are genuinely commentary on a specific verse of Scripture, and file each under that verse "
    "in the \"{father}/\" folder. Much of the text will NOT be imported, and that is "
    "expected; some sermons may give no block at all.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  ({contents})\n\n"
    "Read the WHOLE file. Each sermon opens with its <h1> (\"Sermon 51 ...\", sometimes with "
    "an editor's note on the occasion), and each chapter with an <h2> (\"Chapter 3: The "
    "object and the meaning of the Transfiguration.\"): the <h1> and the <h2> summaries are "
    "the editor's, background for you, not text to import. A block NEVER runs from one sermon "
    "into the next.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Leo QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words "
    "(literally, morally or spiritually), resolves a difficulty in it, applies a figure or "
    "type in it, expounds the Gospel event or saying the verse records (the feast's Gospel: "
    "the Nativity, the magi and Herod, the Temptation, the Transfiguration, the Passion "
    "narrative, the Resurrection appearances, Pentecost), builds his argument on its wording "
    "(e.g. a point on the two natures of Christ drawn from how a verse is phrased, or a reply "
    "to the heretics' reading of it), or APPLIES it to the Christian life, to fasting, "
    "almsgiving or the feast, in a way that shows how he reads it (a verse brought in to "
    "ground a duty and then drawn out). Do NOT import a verse quoted only in passing, a bare "
    "proof-text dropped into a sentence, a chain of proof-texts quoted without comment, a "
    "scriptural phrase borrowed into his own sentence, or exhortation and doctrine that merely "
    "mention Scripture. Ask: would a reader studying this verse learn something about how Leo "
    "understood or used it from this stretch? If so, import it; if it would only learn that "
    "Leo quoted it, leave it out.\n\n"
    "VERSE KEYS. Feltoe's footnotes are shown inline as \"[note: ...]\" in superscript, after "
    "the word they mark. Many give the reference of a quotation (\"S. Matt. v. 6.\", \"Ps. "
    "xxxiv. 8.\", \"1 S. John iii. 2.\", \"Cf.\" = an allusion; \"(LXX.)\" after one means "
    "Leo's Latin follows the Septuagint's sense); others quote Leo's Latin, discuss the "
    "readings, the doctrine, the occasion or the liturgy, and give no verse. The notes also "
    "cite works that are NOT Scripture: \"Serm.\" / \"Sermon\" another sermon of Leo, "
    "\"Lett.\" / \"Ep.\" his letters (\"Lett. XXVIII. (Tome)\" the Tome to Flavian), "
    "\"Ball.\" / \"the Ballerinii\" the editors of Leo, \"Bright\" Bright's edition, "
    "\"Aug.\" Augustine, \"Cypr.\" Cyprian, \"Ruff. de Symb.\" Rufinus on the Creed, "
    "\"Introd.\" the volume's introduction, \"V.\" / \"R.\" a liturgical versicle and "
    "response, \"A.V.\" / \"R.V.\" / \"P.B.V.\" English versions; \"Ecclus.\" is Sirach, "
    "\"Wisd.\" Wisdom, \"Tob.\" Tobit; the \"Hist. of Susanna\" is not in book_names.json "
    "(don't file under it). The notes' Psalm "
    "numbers are mostly the English (KJV) ones, but some are the Latin (one less: Sermon 1's "
    "\"Ps. cxliv. 21\" is KJV 145:21 and its \"Ps. cxxxv. 23, 24\" KJV 136:23 and 136:4, "
    "Sermon 28's \"Ps. cix. 1\" is KJV 110:1, Sermon 24's "
    "\"Ps. lxxxiv. 12\" is KJV 85:11, Sermon 36's \"Ps. vi. 6\" is KJV 6:5) and a few are "
    "misprinted (Sermon 59's \"Ps. vii. 4\" is KJV 57:4, Sermon 24's \"Ps. xxxi. 14\" is "
    "KJV 132:11). A note can sit on the wrong "
    "quotation, be misprinted, or be missing. Use the notes as HINTS only, and confirm every "
    "verse against the KJV wording with `" + KJV_LOOKUP + "`, filing under KJV "
    "book/chapter/verse numbering. Leo quotes the Latin Bible, so his wording often differs "
    "from the KJV's: match by sense. Deuterocanonical books are fine (\"Sirach\", "
    "\"Wisdom\", \"Tobit\", ...): use only the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of ONE sermon, in Leo's order, "
    "starting and ending at sentence boundaries, and able to stand on its own: include the "
    "sentence(s) that bring in the verse and the whole of his exposition of it. Don't pad a "
    "block with unrelated matter before or after the exposition. File it under the SMALLEST "
    "verse range the exposition really addresses: a single verse when it expounds one verse, a "
    "range only when it expounds several verses as one argument (a range crossing chapters is "
    "written like \"Matthew 4_25-5_1\"). When one stretch genuinely expounds two different "
    "passages (e.g. a Gospel event and the prophecy it fulfils, set side by side and "
    "interpreted together, or the same event told in two Gospels), file the same text under "
    "each, as separate files; that is welcome. But never put two overlapping blocks of the "
    "same sermon in the SAME file, and don't split one exposition into fragments under one "
    "verse.\n\n"
    "THE TEXT. Copy Leo's words VERBATIM: nothing abridged, paraphrased, corrected, added or "
    "rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Leave out the "
    "\"[note: ...]\" footnotes and the <h1>/<h2> headings with their chapter numbers and "
    "summaries. Keep the printed text's quotation marks (‘ ’ “ ”), parentheses, square "
    "brackets, dashes, Latin and Greek words, run-together words and misprints as they are. "
    "Don't add headings, verse numbers or notes of your own. Don't write a python script to "
    "do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. Every sermon has its own source_url and source_title. For EVERY block you "
    "import, set the fields of the sermon it comes from:\n"
    "{fields}\n\n"
    "EXISTING BLOCKS. The old imports of these sermons have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (other sermons of Leo{earlier}) may "
    "already have left blocks from his Sermons in the files you write to: they are NOT old "
    "imports or duplicates; leave them exactly as they are and append yours after them. Blocks "
    "from other works (Leo's Letters and Tome, the Catena Aurea, the old url-less excerpts of "
    "sermons we don't have, ...) must be left exactly as they are.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- sermon and "
    "chapter, opening words), and every exposition of a verse you considered but left out, "
    "with the reason."
)

PROMPT2 = "Double check, was this fully imported properly?"


def _fields(work, secs):
    """The SOURCE FIELDS lines of one sermon in a piece."""
    head = (f"- Sermon {work['number']} (source file \"{os.path.join(WRITINGS_DIR, work['html'])}\"):\n"
            f"    source_url   = {source_url_for(work)}\n")
    st = work["source_title"]
    if not work["label"]:
        return head + f"    source_title = \"{st}\"   (no chapters, so no suffix)"
    return head + (
        f"    source_title = \"{st}, Chapter N\" where N is the chapter the block comes from "
        f"(the <h2> headings), e.g. \"{st}, Chapter {secs[0]['chapter_no']}\"; a block "
        f"running across chapters is \"{st}, Chapters 2-3\"")


def build_prompt1(batch, units_dir):
    sermons = batch["sermons"]
    if batch["part"]:
        k, pre, secs = sermons[0]
        i, n = batch["part"]
        piece_desc = (f"It is piece {i} of {n} of Sermon {WORKS[k]['number']}, which is too "
                      f"long for one piece; the other pieces are processed separately (the "
                      f"earlier ones may already have left blocks of this sermon: don't touch "
                      f"them, and don't import text outside this piece).")
        contents = (f"Sermon {WORKS[k]['number']}: "
                    + ", ".join(s["heading"] for s in secs))
        earlier = ", or earlier pieces of this sermon"
    elif len(sermons) == 1:
        piece_desc = "It holds one whole sermon."
        contents = f"Sermon {WORKS[sermons[0][0]]['number']}"
        earlier = ""
    else:
        a, b = WORKS[sermons[0][0]]["number"], WORKS[sermons[-1][0]]["number"]
        piece_desc = (f"It holds {len(sermons)} consecutive sermons of the collection (the "
                      f"translation's selection, so the numbers have gaps), from Sermon {a} to "
                      f"Sermon {b}, each complete and each opening with its <h1>.")
        contents = "; ".join(_contents(batch))
        earlier = ""
    notes = " ".join(f"In Sermon {WORKS[k]['number']}: {WORKS[k]['notes']}"
                     for k, _, _ in sermons if WORKS[k].get("notes"))
    return PROMPT1_TEMPLATE.format(
        units_dir=units_dir,
        unit_name=batch["name"],
        piece_desc=piece_desc,
        father=FATHER,
        contents=contents,
        notes=f" {notes}" if notes else "",
        fields="\n".join(_fields(WORKS[k], secs) for k, _, secs in sermons),
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
    this sermon is one verbatim stretch of it, found once, under a valid filename, with the
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
    return [f"Sermon {WORKS[k]['number']}"
            + (f" ({', '.join(s['heading'] for s in secs)})" if WORKS[k]["label"] else "")
            for k, _, secs in batch["sermons"]]


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
    """Cross-sermon order: in each file, the Sermons' blocks (all appended after the files'
    BASE content) must follow sermon number, then source position. Sermons run out of
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
        if URL_MARK not in text:
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
        print(f"  OUT OF SERMON ORDER: {fn[:-5]} {[keys[i] for i in mine]}")
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
    print(f"{len(bad)} file(s) out of sermon order" + (" (fixed)" if base and bad else ""))
    return bad


def expand_works(specs):
    """Sermon keys from the arguments: keys ("LeoSer009") and ranges ("LeoSer009-LeoSer027")."""
    keys = list(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown sermon {spec!r} (keys LeoSer001 .. LeoSer095; see --list)")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def expand_batches(specs, batches):
    """Pieces from the arguments: "B007", "B007_S039-042.html", ranges "B007-B012"."""
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
             "sermons (LeoSer009, LeoSer009-LeoSer027).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="List every piece and its sermons.")
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folder and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true",
                      help="Run only the check of these sermons (printing only failures when "
                           "several).")
    mode.add_argument("--order", action="store_true",
                      help="Check that every file holds the Sermons' blocks in sermon order "
                           "(any sermon argument; all files are checked).")
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
        print(f"\n{len(keys) - len(bad)} of {len(keys)} sermon(s) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    batches = make_batches()
    if args.list:
        for b in batches:
            print(f"  {b['name']:<26} {batch_size(b):>6} chars  {'; '.join(_contents(b))}")
        print(f"{len(batches)} pieces, {len(WORKS)} sermons")
        return
    if args.split_only and not args.specs:
        print(f"Wrote {len(batches)} piece(s) to {write_batches(batches)}")
        return
    if not args.specs:
        parser.error("name the pieces to run (see --list)")
    run = expand_batches(args.specs, batches)

    print(f"Work:       {FATHER}, Sermons ({len(run)} piece(s))")
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

    log_dir = os.path.join(WORK_DIR, "leo_sermons_import_logs")
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
            # Check each sermon once its last piece has run.
            for k, _, _ in b["sermons"]:
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
        print("Every sermon of these pieces passes the check.")


if __name__ == "__main__":
    main()
