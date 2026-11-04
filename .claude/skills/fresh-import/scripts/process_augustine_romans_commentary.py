#!/usr/bin/env python3
"""Import Augustine's Exposition of Certain Propositions from the Epistle to the Romans
(Expositio quarumdam propositionum ex Epistola ad Romanos; a fresh English translation of the
Latin of PL 35, 2063-2088, as given at augustinus.it) into the Commentaries-Database, one piece
at a time, by driving a headless ``claude`` agent.

A per-work copy of process_theodoret_commentary.py (see ../SKILL.md, "Other fathers"): the same
two-prompt flow, logs and --check. (Augustine's Tractates on John have their own importer,
process_augustine_commentary.py; a work key must not be in two importers, so this one is
"PropRomans", not "Romans", which is Theodoret's.) What differs is the source layout:

    Writings-Database/Augustine of Hippo/Exposition of Certain Propositions from the Epistle
    to the Romans.html

    <h1>..</h1><i>source note</i><br/><br/>                 (the preamble)
    These are the meanings in the Epistle ...<br/><br/>      (Augustine's opening: the prologue)
    <b>1.</b> [1.] When he says: <i>lemma</i>, comment ...   (a proposition, one paragraph)
    <b>7.</b> [7.-8.] When he says: <i>..</i> ...            (the bracket is the standard
    <b>22.</b> [29. 1.] ...                                    numbering, 1-84, merged or split)
    <b>Notes</b><section class="notes">..</section>          (Scripture references, 1-103)

No <h2> and no verse labels: ``load_work`` cuts one section per proposition (76). The html
keeps the paragraph and proposition numbers (the agent sees them) and shows each footnote
inline as ``<sup>[note: Wis 13:9.]</sup>``; the body (imported and checked) drops both. Each
section's heading is a GUESS of the verse its lemma quotes (``guess_verses``: word overlap with
the KJV, on a path that never steps back), written "C:V ¶<proposition>", e.g. "3:20 ¶13-18". It
is a HINT for the audit only (PLACEMENT?, OUTSIDE HEADING), never shown to the agent, who sees
the proposition labels; check the guesses with ``audit_jerome_import.py PropRomans --headings``.

    python3 process_augustine_romans_commentary.py PropRomans --dry-run
    python3 process_augustine_romans_commentary.py PropRomans --split-only
    python3 process_augustine_romans_commentary.py PropRomans Part001_P01-12.html
    python3 process_augustine_romans_commentary.py PropRomans --check
"""

import argparse
import html
import json
import math
import os
import re
import shutil
import sqlite3
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
KJV_DB = os.path.join(SCRIPT_DIR, "kjv.sqlite")
# KJV lookup for the agent, run from PROJECT_DIR.
KJV_LOOKUP = 'python3 .claude/skills/fresh-import/scripts/kjv_lookup.py "<Book> <C>:<V>"'

FATHER = "Augustine of Hippo"

# Runs of whole propositions are packed into pieces of at most this much html.
SPLIT_CHARS = 20000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "PropRomans": {
        "html": "Augustine of Hippo/Exposition of Certain Propositions from the Epistle to the "
                "Romans.html",
        "book": "Romans",
        "source_title": "Exposition of Certain Propositions from the Epistle to the Romans",
        # Each proposition opens with a formula ("When he says:") before its italic lemma; the
        # audit's lemma detector skips it (see audit_jerome_import.py).
        "intro_lemmas": True,
        "notes": (
            "The lemmas are translated from Augustine's Latin, so their wording is often far "
            "from the KJV's: match them by sense. For example, \"For I am certain\" ([58.]) is "
            "KJV 8:38 (\"For I am persuaded\"); \"Blessed is he who does not judge himself in "
            "that which he approves\" ([81.]) is 14:22 (\"Happy is he that condemneth not "
            "himself\"); \"Not only those who do these things, but also those who consent to "
            "those who do them\" ([7.-8.]) is 1:32; \"the prudence of the flesh\" ([49.]) is "
            "the KJV's \"carnal mind\" (8:7). \"He gave them over\" ([5.]) and \"God gave them "
            "over to a reprobate mind\" ([6.]) need care: KJV 1:24, 1:26 and 1:28 all say \"God "
            "gave them up\"/\"over\"; let the comment decide. Augustine follows the epistle's "
            "order, but now and then a proposition takes up an earlier verse again (e.g. [23.] "
            "\"For the law works wrath\", 4:15, comes after [22.] on 4:5): file it under the "
            "verse it explains anyway, and keep the propositions' order inside each file.\n\n"
            "We are interested in the commentary, not the lemma: file every block under the "
            "verse(s) its COMMENTARY addresses. When a lemma quotes two verses but the comment "
            "after it addresses only the first, file that block (lemma included, uncut) under "
            "that verse alone; the lemma's span never widens a block's range. Several "
            "propositions quote the next verse(s) as they go (\"[29. 1.]\" quotes 5:14 in "
            "pieces; \"[13.-18.]\" ranges over the law's purpose with verses from several "
            "chapters): split only where the comment really turns to a new verse of Romans, "
            "never into fragments, and keep a verse Augustine quotes only to support his point "
            "inside the block it supports.\n\n"
            "THE PROLOGUE. The two sentences before [1.] (\"These are the meanings in the "
            "Epistle of the Apostle Paul to the Romans. First of all, that everyone should "
            "understand that in this epistle the question being treated concerns the works of "
            "the law and grace.\") are Augustine's own opening of the work: import them as ONE "
            "block of their own in \"Romans 1_1\", appended after the block already there (an "
            "excerpt of his other Romans commentary, titled \"RUDIMENTARY EXPOSITION OF THE "
            "EPISTLE TO THE ROMANS 2.1-3, 5\", which stays first). Don't cross-file it, and "
            "don't join it to [1.].\n\n"
            "Earlier pieces of THIS run have already imported their propositions, so you may "
            "find \"Exposition of Certain Propositions from the Epistle to the Romans\" blocks "
            "in the files you write to (a block from the piece before yours, or a "
            "cross-reference). Those are NOT old imports or duplicates: leave them exactly as "
            "they are and append yours after them. Many Romans files also hold excerpts of "
            "Augustine's other works (\"LETTER ...\", \"QUESTIONS ...\", \"TO SIMPLICIAN ON "
            "VARIOUS QUESTIONS ...\", \"RUDIMENTARY EXPOSITION ...\", Tractates on John, City "
            "of God): leave them first and untouched."
        ),
    },
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing Augustine of Hippo source_urls ("file=Augustine%2520of%2520Hippo%2F...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"augustine_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>&nbsp;(.*?)</span>', re.S)
NOTES_SECTION_RE = re.compile(r'\s*<b>Notes</b>\s*<section class="notes">.*?</section>\s*', re.S)
# A proposition: "<b>7.</b> [7.-8.] " (paragraph number, then the standard numbering).
PROP_RE = re.compile(r"<b>(\d+)\.</b> \[([^\]]+)\] ")
# The formula before a proposition's lemma: "When he says: ", "When at last he says: ",
# "When he says of Abraham: ", "When he says, according to the testimony of Moses: ".
INTRO_RE = re.compile(r"When [^<:]{0,60}(?:says|said)[^<:]{0,50}: ")
STOP = set("the and of to a in that he shall be his is they for i you your will them their which "
           "with not it are from my by have as on all who but this was me o so at or thee thou thy "
           "ye unto what then said says".split())
BACKSTEP = 0.5
FREE_JUMP = 20
JUMP = 0.005


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _stems(s):
    return {w[:5] for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}


def guess_verses(lemmas, book):
    """The KJV verse each lemma most likely quotes: word overlap with every verse of the book,
    on the best path through them (a step back costs BACKSTEP, a jump forward of more than
    FREE_JUMP verses JUMP per verse beyond). Returns [((chapter, verse), score)]. Audit hints
    only."""
    db = sqlite3.connect(KJV_DB)
    kjv = sorted((l // 1000000, l % 1000000, t) for l, t in db.execute(
        "select txt_location, txt from bible_kjv where book=?", (book.lower(),)))
    ks = [_stems(t) for _, _, t in kjv]
    sc = [[len(lw & k) / max(1, len(lw)) for k in ks] for lw in map(_stems, lemmas)]
    n = len(ks)

    def cost(q, j):
        return BACKSTEP if q > j else JUMP * max(0, j - q - FREE_JUMP)

    best, back = [sc[0][:]], [[None] * n]
    for row in sc[1:]:
        cur, bk = [], []
        for j, x in enumerate(row):
            q = max(range(n), key=lambda q: best[-1][q] - cost(q, j))
            cur.append(x + best[-1][q] - cost(q, j)); bk.append(q)
        best.append(cur); back.append(bk)
    j = max(range(n), key=lambda q: best[-1][q])
    path = []
    for i in range(len(sc) - 1, -1, -1):
        path.append(j)
        j = back[i][j]
    path.reverse()
    return [((kjv[j][0], kjv[j][1]), sc[i][j]) for i, j in enumerate(path)]


def load_work(work):
    """Return (preamble_html, sections): the prologue ("Preface", non-verse) and one section per
    proposition. Each has its raw html (numbers kept, footnotes inline as [note: ...] hints),
    its body (without them), its `label` (the standard numbering, "13.-18." -> "13-18", "29. 1."
    -> "29.1"), its heading (the guessed verse, "3:20 ¶13-18") and its chapter (None if
    non-verse)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    notes = {int(n): _clean(t) for n, t in NOTE_RE.findall(text)}
    text = NOTES_SECTION_RE.sub("\n", text).replace("</article>", "")
    props = list(PROP_RE.finditer(text))
    if [int(m[1]) for m in props] != list(range(1, len(props) + 1)):
        raise SystemExit("paragraph numbers are not 1..n")
    m = re.search(r"</h1>\s*(?:<i>.*?</i><br/><br/>\s*)?", text, re.S)
    preamble = text[:m.end()]
    hint = lambda s: FOOTNOTE_REF_RE.sub(
        lambda r: f"<sup>[note: {html.escape(notes[int(r[1])], quote=False)}]</sup>", s)
    body = lambda s: FOOTNOTE_REF_RE.sub("", s)
    pre = text[m.end():props[0].start()]
    sections = [{"heading": "Preface", "label": "Preface", "chapter": None,
                 "html": hint(pre), "body": body(pre)}]
    lemmas = []
    for k, p in enumerate(props):
        e = props[k + 1].start() if k + 1 < len(props) else len(text)
        raw = text[p.start():e].rstrip() + "\n"
        label = re.sub(r"\.$", "", p[2].replace(". ", ".").replace(".-", "-"))
        sections.append({"label": label, "html": hint(raw), "body": body(text[p.end():e]).rstrip() + "\n"})
        lm = re.match(INTRO_RE.pattern + r"<i>(.*?)</i>", text[p.end():e], re.S)
        if not lm:
            raise SystemExit(f"proposition [{p[2]}] does not open with a formula and a lemma")
        lemmas.append(_clean(lm[1]))
    for s, ((c, v), score) in zip(sections[1:], guess_verses(lemmas, work["book"])):
        s.update(heading=f"{c}:{v} ¶{s['label']}", chapter=c, score=score)
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
    """The ordered list of pieces: {name, sections}, named by the first and last proposition
    (the prologue goes with the first)."""
    units = []
    for run in split_evenly(sections, cap):
        nums = [int(re.match(r"\d+", s["label"])[0]) for s in run if s["chapter"]]
        units.append({"name": f"Part{len(units) + 1:03d}_P{nums[0]:02d}-{nums[-1]:02d}.html",
                      "chapter": None, "sections": run})
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
    "We have Augustine of Hippo's {title} here: \"{units_dir}/{first_unit}\" with the files "
    "continuing up to \"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, "
    "from our own English translation of the whole work (made from the Latin of PL 35), "
    "\"{html_path}\" (consult it if you need surrounding context). The work is Augustine's "
    "early exposition of the Epistle to the {book}: short comments on selected verses, in the "
    "epistle's order -- file everything under the book \"{book}\", in the \"{father}/\" "
    "folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its sections, by the standard proposition numbers: {headings})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. Each "
    "piece repeats the work's title and the source note at the top -- that note is background "
    "for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. The work is a series of numbered propositions, one paragraph each, printed "
    "as \"<b>7.</b> [7.-8.] When he says: <i>lemma</i>, comment ...\": the bold number counts "
    "the paragraphs, the bracketed one is the standard numbering of the propositions (some "
    "are joined, \"[13.-18.]\", or split, \"[29. 1.]\" and \"[29. 2.]\"). Neither says which "
    "verse is meant. Each proposition opens with a formula (\"When he says:\") and the verse "
    "Augustine is explaining, quoted in italics (the lemma), often only in part. For each "
    "stretch of commentary, work out which KJV verse(s) it actually expounds -- compare the "
    "words of the lemma and of the Scripture Augustine quotes and discusses with the KJV "
    "text, looking it up with `" + KJV_LOOKUP + "` -- and file it there, under KJV "
    "chapter/verse numbering. The translation's footnotes are shown inline as \"[note: "
    "...]\" in superscript, after the words they belong to (\"[note: Rom 7:25.]\", \"[note: "
    "Ps 18:13 (19:12).]\": the Latin psalm number, then the KJV one in parentheses; \"Cf. "
    "<i>Retractations</i> 1.22.2\" points to Augustine's later correction of a passage, and "
    "\"Cf. above, 13\" to proposition 13). They identify the OTHER Scripture he quotes; the "
    "lemmas themselves are not footnoted.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Most "
    "propositions comment on one verse: file the whole proposition under it. A longer one "
    "can move on through several verses, quoting each in turn (e.g. a proposition opening on "
    "9:16 that goes on to quote and explain 9:17, 9:18 and 9:19-21): split it there, at a "
    "sentence boundary, filing each part under the verse(s) it explains. Where he treats two "
    "or three verses as one thought, use a range rather than chopping a coherent comment "
    "into fragments; just prefer single verses. Each block must be one continuous stretch of "
    "Augustine, in his order, and the blocks together must hold the WHOLE text, every word. "
    "Do NOT duplicate the same stretch of commentary across several {book} verses -- put it "
    "ONCE, at its smallest accurate verse/range.\n\n"
    "WHERE BLOCKS START. Every proposition starts its own block, with its opening formula "
    "(\"When he says:\"), and its lemma stays whole at the start of that block. Never join "
    "two propositions in one block, even when both explain the same verse (then they are two "
    "blocks in the same file, in order).\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the within-{book} duplication "
    "forbidden above). Augustine quotes much other Scripture. Whenever a stretch genuinely "
    "QUOTES AND EXPOUNDS a specific verse from another book -- says what it means, not merely "
    "cites it -- you may ALSO file that portion under that verse in its own file (e.g. "
    "\"Wisdom 13_9\"), in addition to its {book} placement. Most of his quotations "
    "are passing proof-texts: do not cross-file those, nor the Old Testament verses Paul "
    "himself quotes in the epistle (they are the lemma's, not Augustine's exposition of the "
    "prophet). Use KJV book/verse numbering for the target file, matching a Psalm by its "
    "wording (the notes give its KJV number in parentheses), and only book names from "
    "book_names.json.\n\n"
    "THE TEXT. Copy Augustine's words VERBATIM -- nothing abridged, paraphrased, corrected, "
    "added or rearranged -- and keep the lemma where it stands in the source. Drop the html "
    "tags (italics simply become plain text; don't turn them into quotation marks) and "
    "separate paragraphs with a single blank line. Leave out the numbers (\"7. [7.-8.]\") "
    "and the \"[note: ...]\" hints: copy the text around them as if they were not there. Keep "
    "everything else as printed, including the dashes and quotation marks. Don't add "
    "headings, verse numbers or notes of your own. Don't write a python script to do this; "
    "process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this work, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- the whole work sits behind one page).\n\n"
    "EXISTING BLOCKS. The old imports of this work (url-less excerpts of another translation, "
    "titled \"AUGUSTINE ON ROMANS ...\") have ALREADY been deleted, so you are only ADDING: if "
    "a verse file exists, append your [[commentary]] after its existing blocks; otherwise "
    "create it. Blocks from other works must be left exactly as they are."
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
        headings=", ".join(s["label"] for s in unit["sections"]),
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
            if re.search(r"</?[a-z]+>|\[note:", q):
                problems.append(f"{fn}: leftover html tag or [note: ...] in a block")

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
                        f"section {s['label']!r} paragraph {i} {label} not found: "
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
                "sections": [s["label"] for s in unit["sections"]],
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
    print(f"{unit['name']}: {', '.join(s['label'] for s in unit['sections'])}")
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
        help="Process ONE piece (e.g. Part002_P13-29.html); see --dry-run for the names.",
    )
    parser.add_argument(
        "--start-after", metavar="NAME",
        help="Resume after this piece (e.g. Part001_P01-12.html).",
    )
    parser.add_argument(
        "--through", metavar="NAME",
        help="Stop after this piece (e.g. Part003_P30-45.html); combine with --start-after "
             "to run a chunk.",
    )
    parser.add_argument(
        "--split-chars", type=int, default=SPLIT_CHARS,
        help=f"Pack propositions into pieces of up to this many html chars (default {SPLIT_CHARS}).",
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
          f"(propositions packed into pieces of up to {args.split_chars} chars):")
    for u in units:
        size = sum(len(s["html"]) for s in u["sections"])  # excl. the repeated preamble
        print(f"  {u['name']:<22} {size:>7} chars  "
              f"{', '.join(s['label'] for s in u['sections'])}")

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
