#!/usr/bin/env python3
"""Import Ambrosiaster's commentaries on the Pauline epistles (fresh public-domain translations
from the Latin of PL 17) into the Commentaries-Database, one piece at a time, by driving a
headless ``claude`` agent.

A per-father copy of process_cyril_commentary.py (see ../SKILL.md, "Other fathers"): the same
two-prompt flow, splitting, logs and --check. The source layout:

    Writings-Database/Ambrosiaster/Commentary on 1 Corinthians.html

    <h1>..</h1><i>translator's note</i><br><br>   (the preamble)
    <h2>Prologue</h2> ...                          (non-verse: the work's prologue)
    <h2>Chapter I</h2>
    (1 Cor. 1:1) <i>lemma</i> comment ...<br><br>  (a verse label, the edition's, and the lemma)
    comment continued ...<br><br>
    (1 Cor. 1:2) <i>lemma</i> ...

``load_work`` cuts every <h2> group into one section per verse label (a "(1 Cor. C:V)" opening
a paragraph and followed by the italic lemma), as Cyril's does. A section's heading is the label
normalised ("1:14-16"); its html keeps the label (the agent sees it as a hint), its body drops
it. The same "(1 Cor. 1:12)" form inside a paragraph is the translator's citation of a
quotation and stays in the text. Text under an <h2> before its first label (the Prologue) is
a non-verse section headed by the <h2> text.

Keys are "Amb" + the book ("Amb1Cor"), since Jerome's importer already has "Galatians",
"Titus" and "Philemon".

    python3 process_ambrosiaster_commentary.py Amb1Cor --dry-run
    python3 process_ambrosiaster_commentary.py Amb1Cor --split-only
    python3 process_ambrosiaster_commentary.py Amb1Cor Part002_Ch01.html
    python3 process_ambrosiaster_commentary.py Amb1Cor --start-after Part002_Ch01.html
    python3 process_ambrosiaster_commentary.py Amb1Cor --check
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

FATHER = "Ambrosiaster"

# A chapter with more html than this is cut into near-equal parts at <h2> boundaries.
SPLIT_CHARS = 30000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

WORKS = {
    "Amb1Cor": {
        "html": "Ambrosiaster/Commentary on 1 Corinthians.html",
        "book": "1 Corinthians",
        "source_title": "Commentary on 1 Corinthians",
        # The edition's verse label opening a paragraph: "(1 Cor. 14:24–25)".
        "label": "1 Cor.",
        "notes": (
            "The edition's labels follow the Latin verse division and mostly give the KJV verse, "
            "but check each against the wording; several sections open with the second half of "
            "the verse before. The \"1:2\" section opens with \"And Sosthenes, the brother.\" (the "
            "end of KJV 1:1, so that first stretch belongs under 1:1) before reaching 1:2 (\"To "
            "the church of God which is at Corinth\"). The \"1:19\" section opens with the end of "
            "1:18 (\"But to those who are being saved it is the power of God.\"). There is no "
            "\"1:24\" label: the \"1:25\" section opens with KJV 1:24 (\"But to those who are "
            "called, both Jews and Greeks, Christ the power of God and the wisdom of God.\") and "
            "reaches 1:25 at \"Because what is foolish of God is wiser than men.\" The \"1:31\" "
            "section opens with the end of 1:30 (\"Who was made wisdom for us from God, and "
            "righteousness, and sanctification, and redemption.\") before 1:31 (\"So that, as it "
            "is written: Let him who glories, glory in the Lord.\"). The \"5:13\" section opens "
            "with the end of 5:12 (\"Do you not judge those who are within?\"). The 14:10 lemma "
            "stands inside the \"14:9\" section (\"For there are, for instance, many kinds of "
            "tongues in this world, and nothing is without voice.\"), and the \"14:10-11\" "
            "section quotes only 14:11. The \"15:24-26\" lemma runs on into the first half of "
            "15:27 (\"for he has subjected all things under his feet\"), and the \"15:27-28\" "
            "section opens with its second half (\"But when he says: All things are subjected to "
            "him\"). A label with a range (\"7:10-11\") only says which verses the lemma quotes; "
            "file by the commentary. Our filenames never carry a/b: a stretch on half a verse goes "
            "under the whole verse number.\n\n"
            "THE LEMMAS. Every labelled section opens with its lemma in italics, translated from "
            "Ambrosiaster's own Old Latin text of Paul, so the wording often differs from the KJV "
            "(\"Paul, called an apostle of Christ Jesus through the will of God.\"). Inside a "
            "section, further italic phrases are either the next words of the epistle, each "
            "followed by its own comment (the commentary moves phrase by phrase, and sometimes "
            "into the next verse), or other Scripture he quotes, which the translator follows "
            "with a reference in parentheses (\"(Acts 22:21)\"). EVERY LABEL STARTS ITS OWN "
            "BLOCK: each section's first block starts exactly at the section start, with the "
            "opening lemma whole and uncut; never join the end of one section to the next "
            "section's lemma, even when both are the same verse. When the comment after the "
            "opening lemma addresses only its first verse, that block (lemma included, uncut) "
            "goes under that verse alone; when it begins on a later verse, the range starts "
            "there. We are interested in the commentary, not the lemma: the lemma's span never "
            "widens a block's range. Many sections are one paragraph, or a few: cut between "
            "sentences, at the italic phrase where the next verse begins, and don't split a "
            "short comment into fragments.\n\n"
            "Keep everything verbatim: the translator's references in parentheses (\"(Isa. "
            "26:19)\", \"(1 Cor. 1:12)\": only the label that OPENS a paragraph is left out), "
            "the straight quotation marks, the en dashes in references (\"(Phil. 2:10–11)\"), the "
            "one Greek phrase with its gloss (\"κατὰ Λουκᾶν (according to Luke)\"), and "
            "\"maranatha\". The translator's Psalm references keep the Latin (LXX) numbering: "
            "\"(Ps. 50:6)\" is KJV Psalms 51:4, \"(Ps. 81:6)\" is 82:6-7, \"(Ps. 113:1)\" (\"Not to "
            "us, O Lord, not to us\") is 115:1, \"(Ps. 95:10)\" (\"The Lord has reigned from the "
            "wood\") is 96:10, \"(Ps. 8:8)\" is 8:5-6, \"(Ps. 35:7)\" is 36:6, \"(Ps. 140:5)\" is "
            "141:5 and \"(Ps. 1:5)\" is 1:5. Two other references follow the Latin Bible too: "
            "\"(Jon. 2:1)\" is KJV Jonah 1:17 and \"(Sir. 10:28)\" is KJV Sirach 10:25. Match "
            "any cross-reference by its wording.\n\n"
            "Earlier pieces of THIS run have already imported their sections, so you may find "
            "\"Commentary on 1 Corinthians\" blocks in the files you write to (e.g. a "
            "cross-reference from an earlier piece). Those are NOT old imports or duplicates: "
            "leave them exactly as they are and append yours after them. Some 1 Corinthians files "
            "already hold Ambrosiaster's \"Questions on the Old and New Testaments\" blocks (e.g. "
            "\"1 Corinthians 2_8\", \"1 Corinthians 11_7\"): they stay first, untouched.\n\n"
            "THE PROLOGUE (\"Admonished by the Lord's command, the Apostle stayed among the "
            "Corinthians one year and six months\" ... \"which will be seen in the body of the "
            "letter.\"), the list of the causes for which he writes, goes in whole as the FIRST "
            "block of \"1 Corinthians 1_1\" (the file does not exist yet), before the 1:1 "
            "commentary. Nothing is to be skipped as a closing note: the work ends with the "
            "comment on 16:23-24, whose last words are \"not with the affection of the flesh, but "
            "in Christ Jesus.\"; import it to its end."
        ),
    },
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment is
    double-encoded (spaces as %2520), with %2F between segments, matching the existing
    Ambrosiaster source_urls ("file=Ambrosiaster%2FCommentary%2520on%25201%2520Corinthians.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"ambrosiaster_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


# A verse label opening a paragraph: the edition's reference to the lemma that follows,
# "(1 Cor. 1:1)", "(1 Cor. 14:24–25)" (an en dash), always followed by the italic lemma.
# The work's "label" gives the book's abbreviation.
def label_re(work):
    return re.compile(r"\(" + re.escape(work["label"])
                      + r" (?P<lab>\d+:\d+(?:[–-]\d+)?)\)\s*(?=<i>)")


def label_heading(lab):
    """Normalise a verse label to a heading: '14:24–25' -> '14:24-25'."""
    return lab.replace("–", "-")


ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50}


def roman(numeral):
    vals = [ROMAN_VALUES[c] for c in numeral]
    return sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))


def load_work(work):
    """Return (preamble_html, sections): one section per verse label (heading = the label,
    normalised), plus the non-verse sections (text under an <h2> before its first label: the
    Prologue). Each keeps its raw html (heading and label included), its body (without them)
    and its chapter (None if non-verse)."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    label = label_re(work)
    # Editorial marks the work asks to drop from its sections (not from the preamble).
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
        starts = sorted({a for a in para_starts if label.match(body, a)})
        lead = body[:starts[0]] if starts else body
        if _clean(lead) or not starts:
            sections.append({"heading": heading, "chapter": None, "html": h2 + "\n" + lead,
                             "body": lead})
            h2 = ""
        ch = re.fullmatch(r"Chapter ([IVXL]+)", heading)
        for k, a in enumerate(starts):
            chunk = body[a:starts[k + 1] if k + 1 < len(starts) else len(body)]
            m = label.match(chunk)
            head = label_heading(m["lab"])
            chapter = int(re.match(r"\d+", head)[0])
            if not ch or roman(ch[1]) != chapter:
                raise SystemExit(f"label {head} under <h2> {heading!r}")
            sections.append(
                {
                    "heading": head,
                    "chapter": chapter,
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
    "We have Ambrosiaster's {title} here: \"{units_dir}/{first_unit}\" with the files "
    "continuing up to \"{units_dir}/{last_unit}\". These are consecutive pieces cut, in order, "
    "from our fresh, PUBLIC-DOMAIN English translation of the whole work (from the Latin of "
    "Migne's Patrologia Latina 17), \"{html_path}\" (consult it if you need surrounding "
    "context). The work is Ambrosiaster's verse-by-verse commentary on {book} -- file "
    "everything under the book \"{book}\", in the \"{father}/\" folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (the edition's verse labels and headings in it: {headings})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. Each "
    "piece repeats the work's title and the translator's note at the top -- that note is "
    "background for you, not commentary; don't import it.\n\n"
    "VERSE KEYS. The <h2> headings are chapter headings (\"Chapter VII\"). Each passage of "
    "the epistle that Ambrosiaster comments on (the lemma, in italics) opens a paragraph with "
    "the edition's verse label, e.g. \"({label} 7:10–11)\"; his comment follows, up to the "
    "next label. Treat these labels as HINTS ONLY: they may be off. For each stretch of "
    "commentary, work out which KJV verse(s) it actually expounds -- compare the Scripture "
    "Ambrosiaster quotes and discusses with the KJV text, looking it up with `" + KJV_LOOKUP
    + "` -- and file it there, under KJV chapter/verse numbering.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. A labelled "
    "section often quotes the epistle a phrase at a time, each phrase in italics followed by "
    "its own comment, and sometimes runs on into the next verse's words, so do NOT simply "
    "file a section under the range of its label. Break it up wherever the exposition moves "
    "from one verse to the next: e.g. if a stretch comments on 7:11, insert it in 7:11, not "
    "in 7:10-11. It's ok to use a range if necessary to avoid breaking up a coherent "
    "thought/piece, just prefer smaller ranges/individual verses -- but don't chop the text "
    "into fragments of a sentence or two that can't stand alone. When you split a section, "
    "its pieces together must still contain the WHOLE of it, every word -- and you split ONLY "
    "by cutting the text into consecutive stretches: each block must be one continuous "
    "stretch of Ambrosiaster, in his order. Never cut up or move the opening lemma: when it "
    "quotes several verses, that whole quotation stays, uncut, at the start of the first "
    "block from the section. Do NOT duplicate the same stretch of commentary across several "
    "{book} verses -- put it ONCE, at its smallest accurate verse/range.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the within-{book} duplication "
    "forbidden above). Ambrosiaster often quotes other Scripture. Whenever a stretch "
    "genuinely QUOTES AND EXPOUNDS a specific verse from another book -- a Psalm or other OT "
    "verse, a Gospel passage, or another Epistle -- you may ALSO file that portion under that "
    "verse in its own file (e.g. \"Isaiah 26_19\", \"Romans 6_4\"), in addition to its "
    "{book} placement. File a cross-parallel only where Ambrosiaster genuinely expounds the "
    "passage, not for a passing mention or a bare one-line proof-text. Use KJV book/verse "
    "numbering for the target file -- note the translator's references to the Psalms keep "
    "the Latin (LXX) numbering, which is often one lower (e.g. \"(Ps. 17:...)\" = KJV Psalm "
    "18), so match a Psalm by its wording.\n\n"
    "NON-VERSE SECTIONS. The \"Prologue\" introduces the whole epistle: file it under "
    "\"{book} 1_1\" as a block of its own, placed BEFORE the 1:1 commentary -- even if it "
    "discusses some later verse (don't file it under that verse).\n\n"
    "THE TEXT. Copy Ambrosiaster's words VERBATIM -- nothing abridged, paraphrased, "
    "corrected, added or rearranged -- and keep the lemma where it stands in the source. Drop "
    "the html tags (italics simply become plain text; don't turn them into quotation marks) "
    "and separate paragraphs with a single blank line. Leave out the <h2> headings and the "
    "verse labels that open the paragraphs (\"({label} 1:1)\"): a block starts with the "
    "lemma's own words. Keep the translator's references in parentheses INSIDE the text "
    "(\"(Acts 22:21)\", \"(Isa. 26:19)\", \"(1 Cor. 1:23)\") exactly as printed: they are "
    "part of the text. Don't add headings, verse numbers or notes of your own. Don't write a "
    "python script to do this; process the file yourself manually.\n\n"
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
        label=work["label"],
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

    log_dir = os.path.join(WORK_DIR, f"ambrosiaster_{args.work.lower()}_import_logs")
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
