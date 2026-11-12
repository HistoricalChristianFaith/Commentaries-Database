#!/usr/bin/env python3
"""Import the Scripture commentary in Eusebius of Caesarea's Church History (Books 1-10, in
Arthur Cushman McGiffert's public-domain translation, NPNF 2nd series vol. 1, 1890) into the
Commentaries-Database, one piece at a time, by driving a headless ``claude`` agent.

A per-work copy of process_augustine_harmony_commentary.py (see ../SKILL.md, "Other fathers"
and "Selective works") with the same two-prompt flow, splitting, logs and --check; a second
Eusebius importer, since process_eusebius_commentary.py is built for the Proof of the Gospel's
layout. The work is a history, not a commentary, so the import is SELECTIVE (WORKS
"selective": True): the agents read every chapter and file only the stretches where EUSEBIUS
HIMSELF expounds a verse (the user's choice: the documents he quotes from other authors, e.g.
Africanus on the genealogies or Dionysius on the Apocalypse, are not imported).

Each book is its own file in the Writings-Database, with its own url, so each is its own WORKS
entry ("HE01" .. "HE10"):

    Writings-Database/Eusebius of Caesarea/THE CHURCH HISTORY OF EUSEBIUS/Book 2.html

    <h1>Book 2</h1>
    <h2>Introduction.</h2>                      (Books 2, 5, 7, 8: section 0)
    1 text ...<br/><br/>
    <h2>Chapter I. <i>The Course Pursued by the Apostles ...</i></h2>   (one section per chapter)
    1 text ...<sup><a href="#fn1" id="r1">1</a></sup> ...<br/><br/>
    2 text ...
    <section class="notes"><hr/><span id="fn1"><a href="#r1">1</a>&nbsp;Cf. 1 Tim. vi. 20.</span> ...

Book 8's file also prints the Martyrs of Palestine after Chapter XVII ("<h2>Martyrs of
Palestine.</h2>", then its own Chapters I-XIII): included (the user's choice), as sections
1001-1013, titled "Church History, Book 8, Martyrs of Palestine, Chapter N". Book 10 ends with a
colophon <h2> ("The End, with God's Help, ...") that has no text and is dropped.

``load_work`` gives one section per chapter (and a book's Introduction, as chapter 0). The NPNF
section numbers opening paragraphs ("2 ") are dropped (the user's choice), from the pieces as
well as the body. McGiffert's 2,978 notes come to 1.8M chars (twice the text), many of them long
essays, so the html the agent sees carries each one inline, as ``<sup>[note: ...]</sup>``, cut to
its first NOTE_HINT_CHARS chars; the body (the text imported and checked) drops them.

    python3 process_eusebius_history_commentary.py HE01 --dry-run
    python3 process_eusebius_history_commentary.py HE01 --split-only
    python3 process_eusebius_history_commentary.py HE01 Part002_Ch03-05.html
    python3 process_eusebius_history_commentary.py HE01 --start-after Part001_Ch01-02.html
    python3 process_eusebius_history_commentary.py HE01 --check
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

FATHER = "Eusebius of Caesarea"

# A piece holds consecutive chapters up to about this many html chars (the usual 30k: most of
# the text is history and is not imported).
SPLIT_CHARS = 30000

# A note hint is cut to this many chars (McGiffert's notes are often long essays; the Scripture
# references come first).
NOTE_HINT_CHARS = 300

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

HE = "Eusebius of Caesarea/THE CHURCH HISTORY OF EUSEBIUS"

# (book number, notes for that book).
_BOOKS = [
    (1, (
        "BOOK 1 NOTES. Quoted documents (not Eusebius's): Ch. V, Josephus on the census of "
        "Cyrenius and Judas of Galilee, from \"Cyrenius, a member of the senate, one who had held "
        "other offices\" to \"and if they endured, besides God, masters who were mortal.\"; "
        "Eusebius's own sentences before it, setting Luke 2:2 and Acts 5:37 beside Josephus, are "
        "his. Ch. VI: \"But Africanus, who was also no common writer, says that\" begins "
        "Africanus's material in indirect speech (Herod's descent); the rest of the chapter, "
        "Genesis 49:10 fulfilled in Herod and Daniel's weeks, is Eusebius's. Ch. VII: Africanus's "
        "letter on the two genealogies runs from \"For whereas the names of the generations were "
        "reckoned in Israel\" to \"Thus Joseph was the son of both.\"; the paragraphs from \"For "
        "the relatives of our Lord according to the flesh\" (the Desposyni, Herod burning the "
        "records) are STILL Africanus, though no quote mark reopens there. Eusebius resumes at "
        "\"Thus far Africanus.\" (Mary of the same tribe as Joseph, Numbers 36, is his). Ch. "
        "VIII-XI: the Josephus excerpts (Herod's disease; the high priests, \"Valerius Gratus "
        "having put an end to the priesthood of Ananus\" to \"when Josephus, called also Caiaphas, "
        "succeeded him.\"; John the Baptist, \"It seemed to some of the Jews that the army of "
        "Herod\"; \"And there lived at that time Jesus, a wise man\") are Josephus, but Eusebius's "
        "own sentences squaring them with the Gospels (\"Accordingly the whole time of our "
        "Saviour's ministry is shown\", Luke 3:1-2; Herodias and Matthew 14) are his. Ch. XII: the "
        "claims about Sosthenes and Cephas are Clement's report; Eusebius's argument from 1 "
        "Corinthians 15:5-7 after it is his. Ch. XIII: from \"Abgarus, ruler of Edessa, to Jesus "
        "the excellent Saviour\" to \"These things were done in the three hundred and fortieth "
        "year.\" is the Syriac Edessa dossier (Abgar's letter, Jesus' reply, the Acts of "
        "Thaddeus): not Eusebius's. Eusebius's own, and rich in exposition: Ch. II-IV (the Word in "
        "the theophanies, Genesis 1:26, 18-19, 32, Joshua 5, Proverbs 8, Daniel 7; the names Jesus "
        "and Christ, Psalms 2, 45, 110; Christians new and ancient, Isaiah 65-66, Genesis 12, 15), "
        "Ch. VI and Ch. VIII (Matthew 2)."
    )),
    (2, (
        "BOOK 2 NOTES. Quoted documents (not Eusebius's): Ch. I, Clement's Hypotyposes on James; "
        "Ch. IX: \"He says that the one who led James to the judgment-seat\" is Clement in "
        "indirect speech. Josephus: Ch. X (Agrippa's death, \"He had completed the third year of "
        "his reign over all Judea\" to \"and three years during the reign of the Emperor "
        "Claudius.\"), Ch. XI (Theudas; his quotation of the famine runs straight on into Ch. "
        "XII), Ch. XXI (the Egyptian), Ch. XXIII (James's death). Eusebius's own sentences "
        "reconciling them with Acts are his: \"I marvel greatly that Josephus, in these things as "
        "well as\" (Acts 12:21-23), \"You will find this statement also in agreement with the "
        "Acts\" (Acts 11:28-30), \"But it is worth while comparing the account of the Egyptian "
        "given here\" (Acts 21:38). Ch. XIII, Justin on Simon Magus. Ch. XV: the account of how "
        "Mark's Gospel came to be written is Clement and Papias paraphrased; the next sentence, on "
        "1 Peter 5:13 (Babylon a figure for Rome), is Eusebius's. Ch. XVII, Philo on the "
        "Therapeutae: the quoted passages (e.g. \"They expound the Sacred Scriptures figuratively "
        "by means of allegories.\") and Eusebius's indirect paraphrases of Philo (\"He bears "
        "witness, however, that first of all they renounce their property.\") are Philo's "
        "material; Eusebius's own interpretive sentences between them (Acts 4:34-35 applied to "
        "them; their \"writings of ancient men\" taken as the Gospels and apostolic writings) are "
        "his. Ch. XX: the indirect speech after the short Josephus phrase is Josephus paraphrased. "
        "Ch. XXIII, Hegesippus on the martyrdom of James, from \"James, the brother of the Lord, "
        "succeeded to the government of the Church\" to \"And immediately Vespasian besieged "
        "them.\" (Isaiah 3:10, Matthew 26:64), is Hegesippus's. Ch. XXV, Tertullian, Caius and "
        "Dionysius of Corinth. Eusebius's own: Ch. I (James the Lord's brother; Psalm 68:31 "
        "fulfilled in the eunuch), III (Psalm 19:4), VI (John 19:15), VIII-IX (Acts 11:28, 12:1), "
        "XIV (2 Corinthians 10:5), XXII (2 Timothy 4:16-17, \"the mouth of the lion\")."
    )),
    (3, (
        "BOOK 3 NOTES. Quoted documents (not Eusebius's): Ch. VI, Josephus on the siege and famine "
        "(to \"blessed were they that had died before hearing and seeing miseries like these.\"); "
        "Ch. VIII, Josephus on the signs before the war; Ch. VIII §10 reports Josephus on the "
        "oracle, but Eusebius's rebuttal after it (\"But Vespasian did not rule the whole world\", "
        "Psalm 2:8) is his. Ch. X, Josephus on the canon. Ch. XVIII, Irenaeus on the Apocalypse. "
        "Ch. XX: Hegesippus on the grandsons of Jude is quoted from \"Of the family of the Lord "
        "there were still living the grandchildren of Jude\", then continues WITHOUT quote marks, "
        "in indirect speech, from \"Then they showed their hands, exhibiting the hardness of their "
        "bodies\" (Christ's heavenly kingdom, judging quick and dead) to \"These things are "
        "related by Hegesippus.\": all Hegesippus. Eusebius resumes at \"But after Domitian had "
        "reigned fifteen years\". Ch. XXIII, Clement's tale of John and the robber. Ch. XXVIII, "
        "Caius and Dionysius on Cerinthus's millennium. Ch. XXIX-XXX, Clement (Nicolaus; married "
        "apostles). Ch. XXXI, Polycrates and Proclus on Philip's daughters; Eusebius's \"But Luke, "
        "in the Acts of the Apostles, mentions the daughters of Philip\" is his. Ch. XXXII: "
        "\"records that the Church up to that time had remained a pure and uncorrupted virgin\" is "
        "Hegesippus in indirect speech; Eusebius's inference that Symeon saw the Lord (John 19:25) "
        "is his. Ch. XXXVI, Ignatius and Polycarp. Ch. XXXIX: Papias's preface, on Mark (\"This "
        "also the presbyter said: Mark, having become the interpreter of Peter\") and on Matthew "
        "(\"So then Matthew wrote the oracles in the Hebrew language\") are Papias's; in §12 "
        "Papias's thousand years is only reported, and from \"I suppose he got these ideas through "
        "a misunderstanding of the apostolic accounts\" the judgment is Eusebius's own (Revelation "
        "20). Eusebius's own, and likely blocks: Ch. V (the abomination of desolation), Ch. VII "
        "(Christ's prophecies on Jerusalem fulfilled: Matthew 24:19-21, Luke 19:42-44, 21:20-24), "
        "Ch. VIII §11, Ch. XXIV (the order of the Gospels: John's covers the time before the "
        "Baptist's imprisonment, omits the genealogy, begins with the divinity; Luke's preface), "
        "Ch. XXXIX (Justus, Acts 1:23)."
    )),
    (4, (
        "BOOK 4 NOTES. Book 4 is narrative and quoted documents; expect few or no blocks. Quoted "
        "documents touching Scripture (not Eusebius's): Ch. III, Quadratus on Christ's healings; "
        "Ch. XI, Irenaeus on Cerdon and the Marcosians, Justin on Marcion; Ch. XIV, Irenaeus on "
        "Polycarp (Titus 3:10-11); Ch. XV, the Smyrnaean letter on Polycarp's martyrdom, quoted "
        "from \"But when at length he had brought his prayer to an end\" to \"even by the heathen "
        "he is talked about in every place.\" (Romans 13, Matthew 20:22, Genesis 22:13), with "
        "Eusebius's earlier paragraphs only retelling the same letter in indirect speech; Ch. "
        "XVII, Justin on the woman and Ptolemaeus; Ch. XVIII, Justin on Satan; Ch. XXII, "
        "Hegesippus (\"And the church of Corinth continued in the true faith\"; \"And after James "
        "the Just had suffered martyrdom\"); Ch. XXIII, Dionysius of Corinth; Ch. XXVI, Melito's "
        "list of the Old Testament books; Ch. XXIX, Irenaeus on the Encratites (Genesis 1). "
        "Eusebius's own remarks are canon notes and passing allusions (heretics \"like tares\", "
        "Ch. XXIV)."
    )),
    (5, (
        "BOOK 5 NOTES. Book 5 is almost entirely quoted documents; expect few or no blocks. Ch. "
        "I-III: the letter of the churches of Vienne and Lyons (\"The servants of Christ residing "
        "at Vienne and Lyons\"), dense with Scripture (Romans 8:18, John 16:2, Revelation 22:11, "
        "and in Ch. II, Philippians 2:6 and Revelation 1:5, 3:14 on the word witness); its "
        "paragraphs reopening with a quote mark are the same letter, and only Eusebius's one-line "
        "links (\"After certain other words they continue:\") are his. Irenaeus: Ch. VI (Linus), "
        "VII (gifts), VIII (the four Gospels, \"Matthew published his Gospel among the Hebrews\"; "
        "the number of the beast; Isaiah 7:14, \"God in truth became man, and the Lord himself "
        "saved us\"; the Septuagint legend), XX (to Florinus), XXIV (to Victor). Rhodo, Ch. XIII. "
        "The anonymous anti-Montanist, Ch. XVI-XVII (false prophets, Matthew 7:15; ecstasy, \"But "
        "the false prophet falls into an ecstasy\"; the prophetic gift until the final coming). "
        "Apollonius, Ch. XVIII (gifts to prophets; the tree known by its fruit), including the "
        "tradition of the twelve years (Acts 1:4) that Eusebius reports from him in indirect "
        "speech. Polycrates, Ch. XXIV, from \"We observe the exact day; neither adding, nor taking "
        "away.\" (the fourteenth \"according to the Gospel\"). The Little Labyrinth, Ch. XXVIII "
        "(\"They have treated the Divine Scriptures recklessly and without fear.\"; John 3:31). "
        "Eusebius's own: at most Ch. XXIII's note that the fourteenth day is the day the Jews were "
        "commanded to sacrifice the lamb (Exodus 12:6), which is slight."
    )),
    (6, (
        "BOOK 6 NOTES. Book 6 is Eusebius's narrative of Origen and quoted documents; expect few "
        "blocks. Quoted documents (not Eusebius's): Ch. XII, Serapion on the Gospel of Peter. Ch. "
        "XIV: Clement's Hypotyposes in INDIRECT speech with no quote marks, from \"He says that "
        "the Epistle to the Hebrews is the work of Paul\" to \"inspired by the Spirit, composed a "
        "spiritual Gospel.\" (Hebrews by Paul; the order of the Gospels; John's \"spiritual "
        "Gospel\"): all Clement. Eusebius resumes at \"This is the account of Clement.\". Ch. XIX, "
        "Porphyry on allegorical exegesis. Ch. XXV, Origen: his quotation on the Old Testament "
        "canon, from \"It should be stated that the canonical books, as the Hebrews\", is never "
        "closed; it ends at \"which are entitled Sarbeth Sabanaiel.\", and \"He gives these in the "
        "above-mentioned work.\" is Eusebius. Then Origen on the four Gospels (\"Among the four "
        "Gospels, which are the only indisputable ones\"), on John's writings, and on Hebrews (to "
        "\"the author of the Gospel and the Acts, wrote it.\"). Ch. XXXVIII, Origen on the "
        "Elkesites. Ch. XLI-XLII: Dionysius to Fabius begins \"The persecution among us did not "
        "begin with the royal decree\" and runs ACROSS the chapter break: Ch. XLII's \"Many "
        "others, in cities and villages\" is still Dionysius, as far as \"grieve mercy and "
        "overturn order?\" (Hebrews 10:34, Matthew 10:37); Eusebius resumes at \"These words "
        "Dionysius very properly added\". Ch. XLIII, Cornelius on Novatus. Ch. VII reports Judas's "
        "reckoning of Daniel's seventy weeks. Eusebius's own: Ch. VIII, his judgment that Origen "
        "took Matthew 19:12 \"in too literal and extreme a sense\", is the clearest comment."
    )),
    (7, (
        "BOOK 7 NOTES. Book 7 is mostly Dionysius of Alexandria quoted at length; expect few or no "
        "blocks. Paragraphs inside a quotation that reopen with a quote mark are the same author. "
        "Dionysius: Ch. I, V-IX, X (\"And in like manner it is revealed to John;\" to \"his own "
        "wickedness and hatred toward God.\": Revelation 13:5 applied to Valerian, Ezekiel 13:3), "
        "XI, XXI-XXIII (festal letters; the Exodus typology). Ch. XXIV-XXV, On the Promises: "
        "Eusebius's own opening summary of Nepos's view and of Dionysius's books characterizes "
        "them without expounding a verse; Dionysius then speaks from \"But since they bring "
        "forward a certain work of Nepos\" to \"at the spirit of conciliation and harmony which "
        "all had manifested.\", and Ch. XXV, from \"Some before us have set aside and rejected the "
        "book altogether\" to \"showing clearly the difference between the writings.\", is all "
        "Dionysius on the Apocalypse (its authorship, its style against John's Gospel and "
        "Epistle), with only Eusebius's one-line links (\"Farther on he adds:\"). Ch. XXX: the "
        "synodal letter against Paul of Samosata, from \"To Dionysius and Maximus, and to all our "
        "fellow-ministers throughout the world\" to \"let those who think as Artemas does, "
        "communicate with him.\"; its first person plural is the synod, not Eusebius (\"For to "
        "anticipate something of what we shall presently write\"). Eusebius resumes at \"As Paul "
        "had fallen from the episcopate\". Ch. XXXII, Anatolius's Paschal Canons, from \"There is "
        "then in the first year the new moon of the first month\" to \"the teachings also of the "
        "Book of Enoch show.\" (Exodus 12, 2 Corinthians 3:13-18). Eusebius's own remarks are "
        "slight (Ch. XVIII, the statue at Paneas; Ch. XIX, James; Ch. XXXI, knowledge falsely so "
        "called)."
    )),
    (8, (
        "BOOK 8 NOTES. Eusebius's own: Ch. I-II, Lamentations 2 and Psalm 89 applied to the "
        "Church's laxity and the persecution (the dash-gloss inside the Psalm quotation, \"in the "
        "destruction of the churches\", is his); Ch. XVI, Matthew 18:7 applied to Galerius. Quoted "
        "(not Eusebius's): Ch. X, Phileas of Thmuis, from \"Having before them all these examples "
        "and models and noble tokens\" to \"Thou shalt have no other gods before me.\" "
        "(Philippians 2:6-8, 1 John 4:18); Ch. XVII, the edict of Galerius. FIXED: in Ch. XVII, "
        "after the paragraph \"Such is the tenor of this edict, translated, as well as possible, "
        "from the Roman tongue into the Greek.\", the italic line \"That which follows is found in "
        "Some Copies in the Eighth Book.\" and the numbered paragraphs after it (the deaths of the "
        "emperors) are a later scribe's appendix, not Eusebius's: import nothing from it. FIXED: "
        "under the heading \"Martyrs of Palestine.\", the italic note \"The Following also we "
        "found in a Certain Copy in the Eighth Book.\" and the two unnumbered paragraphs before "
        "the Chapter I heading (\"It was in the nineteenth year of the reign of Diocletian, in the "
        "month Xanthicus\") are a near-copy of Ch. II: import nothing from them. The Martyrs of "
        "Palestine chapters are Eusebius's own work; the martyrs' reported words are theirs. His "
        "glosses there are his: MP Ch. VI (\"until the very word of the Saviour should be "
        "fulfilled in him\", Matthew 10:18), MP Ch. XI on the Egyptian martyrs' names and their "
        "Jerusalem (\"thus showing themselves inwardly true Jews, and the genuine Israel of God\"; "
        "Galatians 4:26), MP Ch. XIII (2 Corinthians 3:3)."
    )),
    (9, (
        "BOOK 9 NOTES. The documents in Book 9 (Sabinus's letter, Ch. I; Maximinus's rescript to "
        "Tyre, Ch. VII; his letters and edict, Ch. IX-X; Constantine's inscription) are imperial "
        "texts with no Scripture, and not Eusebius's. All the Scripture in Book 9 is Eusebius's "
        "own: Ch. VII after the rescript (Matthew 24:24), Ch. IX (Maxentius drowned like Pharaoh, "
        "Exodus 15; Psalm 7:15-16), Ch. X (Psalm 33:16-19), Ch. XI (Psalm 146:3-4)."
    )),
    (10, (
        "BOOK 10 NOTES. Ch. I-III are Eusebius's own (Psalms 98, 46, 37 fulfilled; Ezekiel 37:7). "
        "FIXED: Ch. IV begins with Eusebius's introduction (\"A certain one of those of moderate "
        "talent\": he means himself) and the italic title line \"Panegyric upon the building of "
        "the churches, addressed to Paulinus, Bishop of Tyre.\" (a heading), then the oration, "
        "from \"Friends and priests of God who are clothed in the sacred gown\" to \"through whom "
        "be the glory unto him forever and ever. Amen.\" The oration is EUSEBIUS'S OWN, though "
        "printed in quote marks like a document (paragraphs reopening with a quote mark are the "
        "same speech), and full of Scripture expounded (the living temple, the Isaiah prophecies "
        "of the restored Church, the building as an allegory of souls). Ch. V-VII are imperial "
        "documents with no Scripture; Ch. VIII-IX are Eusebius's narrative of Licinius."
    )),
]

WORKS = {
    f"HE{no:02d}": {
        "html": f"{HE}/Book {no}.html",
        # No commented book: the agents choose any book of book_names.json.
        "book": None,
        "selective": True,
        "kind": "history",
        "number": no,
        # "Church History, Book 3, Chapter 39" (the user's choice).
        "source_title": f"Church History, Book {no}",
        "notes": notes,
    }
    for no, notes in _BOOKS
}

# Paragraph-number sequences that are not 1..n in a chapter, as printed (book, chapter): the
# numbers must still rise, except where noted. Others are refused by load_work.
NUMBERING_OK = {
    (1, 7): "no 16 (inside Africanus's letter)",
    (2, 1): "no 6",
    (2, 12): "the first paragraph has no 1",
    (8, 17): "1-11, then the scribe's appendix (\"That which follows is found in Some Copies\") 1-6",
    (10, 4): "no 3-4 (the oration's address runs on)",
}


def _raw_notes(work):
    """McGiffert's notes of a work's file, in printed order (the text of each)."""
    with open(os.path.join(WRITINGS_DIR, work["html"]), encoding="utf-8") as f:
        m = NOTES_RE.search(f.read())
    return [_clean(t) for _, t in NOTE_RE.findall(m.group(1))] if m else []


def note_hints(work, markers):
    """{marker number: note text, cut to NOTE_HINT_CHARS} for the hint of each marker."""
    notes = _raw_notes(work)
    out = {}
    for n in markers:
        if n <= len(notes):
            t = notes[n - 1]
            if len(t) > NOTE_HINT_CHARS:
                t = t[:NOTE_HINT_CHARS].rsplit(" ", 1)[0] + " …"
            out[n] = t
    return out


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520), with %2F between segments, matching
    the existing url'd blocks of the old import ("file=Eusebius%2520of%2520Caesarea%2FTHE...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"eusebius_{work_key.lower()}_units")


# --- Parsing and splitting ----------------------------------------------------

H2_RE = re.compile(r"(<h2>.*?</h2>)", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+(?:-\d+)?">\d+</a></sup>')
NOTES_RE = re.compile(r'(?:<hr\s*/?>\s*)?<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
# "<h2>Chapter XII. <i>Helen, the Queen ...</i></h2>", "<h2>Chapter XIII.</h2>" (Book 8),
# "<h2>Introduction.</h2>", "<h2>Martyrs of Palestine.</h2>" (Book 8), and Book 10's colophon.
CHAPTER_H2_RE = re.compile(r"Chapter ([IVXL]+)\.(?:\s+(.+))?", re.S)
INTRO_H2_RE = re.compile(r"Introduction\.")
MARTYRS_H2_RE = re.compile(r"Martyrs of Palestine\.")
COLOPHON_H2_RE = re.compile(r"The End, with God's Help, of the Tenth Book .*")
# The Martyrs of Palestine's chapters are keyed 1000 + N (its heading section, if it had text,
# would be 1000).
MARTYRS = 1000
# The NPNF section numbers, each opening a paragraph ("<br/><br/>\n25 Matthew proceeds", and
# after a heading "</h2>\n1 It is my purpose"). Dropped from pieces and body alike.
SECTION_NO_RE = re.compile(r"(?:^|(?<=<br/><br/>\n))[ \t]*(\d+)[ \t]+")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman(s):
    n = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN_VALUES[a]
        n += -v if ROMAN_VALUES.get(b, 0) > v else v
    return n


# A note mark before a closing parenthesis keeps a space after it ("... them<sup>..</sup> ),"):
# the agents rightly write "them)," so the body drops the space with the mark.
MARK_BEFORE_PAREN_RE = re.compile(FOOTNOTE_REF_RE.pattern + r" (?=[),;:.])")


# A note mark right after an opening quote keeps a space after it ("<sup>..98..</sup> Now about
# that time", Book 2 Chapter IX): the agents rightly write '"Now', so the body drops the space.
MARK_AFTER_OPEN_QUOTE_RE = re.compile(r'(^|[\s>])"' + FOOTNOTE_REF_RE.pattern + " ")


def _body(raw):
    raw = MARK_AFTER_OPEN_QUOTE_RE.sub(r'\1"', raw)
    return FOOTNOTE_REF_RE.sub("", MARK_BEFORE_PAREN_RE.sub("", raw))


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _ch_name(no):
    if no == 0:
        return "Introduction"
    if no == MARTYRS:
        return "Martyrs of Palestine"
    return f"Chapter {no}"


def chapter_title(work, chapters):
    """The source_title for a block from these chapter numbers (0 = the book's Introduction,
    1001.. = the Martyrs of Palestine's chapters)."""
    a, b = min(chapters), max(chapters)
    base = work["source_title"]
    if a > MARTYRS:
        base, a, b = f"{base}, Martyrs of Palestine", a - MARTYRS, b - MARTYRS
    elif b >= MARTYRS:
        # Crossing from the Church History into the Martyrs: no such block should exist.
        return f"{base}, {_ch_name(a)} to Martyrs of Palestine (one block per work, please)"
    if a == b == 0:
        return f"{base}, Introduction"
    if a == 0:
        return f"{base}, Introduction and Chapter{'s 1-' if b > 1 else ' '}{b}"
    return f"{base}, Chapter {a}" if a == b else f"{base}, Chapters {a}-{b}"


def load_work(work):
    """Return (preamble_html, sections): one section per chapter (and the book's Introduction,
    as chapter 0; the Martyrs of Palestine's chapters as 1001..). A section's heading is
    "Chapter XII. (= 12)" (or "Introduction", "Martyrs of Palestine, Chapter III. (= 3)"), its
    html the chapter as the agent sees it (its <h2> with the editor's title, the text without
    the NPNF section numbers, the footnotes inline as [note: ...] hints), its body the text
    without heading, numbers and notes, and `chapter` None (there are no verse sections);
    `chapter_no` is the chapter's key."""
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
    sections = []
    in_martyrs = False
    for i in range(1, len(parts), 2):
        h2 = parts[i]
        raw = parts[i + 1].replace("</article>", "").lstrip("\n").rstrip() + "\n"
        title = _clean(FOOTNOTE_REF_RE.sub("", h2))
        if COLOPHON_H2_RE.fullmatch(title):
            if _clean(raw):
                raise SystemExit(f"{work['html']}: text after the colophon")
            continue
        if MARTYRS_H2_RE.fullmatch(title):
            in_martyrs = True
            if not _clean(raw):
                continue
            heading, no = "Martyrs of Palestine", MARTYRS
        elif INTRO_H2_RE.fullmatch(title):
            if sections:
                raise SystemExit(f"{work['html']}: Introduction after the first chapter")
            heading, no = "Introduction", 0
        else:
            cm = CHAPTER_H2_RE.fullmatch(title)
            if not cm:
                raise SystemExit(f"{work['html']}: unexpected <h2>: {h2}")
            no = roman(cm.group(1))
            heading = f"Chapter {cm.group(1)}. (= {no})"
            if in_martyrs:
                heading, no = f"Martyrs of Palestine, {heading}", MARTYRS + no
        numbers = [int(n) for n in SECTION_NO_RE.findall(raw)]
        if numbers != list(range(1, len(numbers) + 1)):
            key = (work["number"], no)
            if key not in NUMBERING_OK:
                raise SystemExit(f"{work['html']}: {heading}: section numbers {numbers}")
        raw = SECTION_NO_RE.sub("", raw)
        sections.append({
            "heading": heading,
            "chapter": None,
            "chapter_no": no,
            "html": h2 + "\n" + hinted(raw),
            "body": _body(raw),
        })
    nos = [s["chapter_no"] for s in sections if 0 < s["chapter_no"] < MARTYRS]
    if nos != list(range(1, len(nos) + 1)):
        raise SystemExit(f"{work['html']}: chapters are not numbered 1..n: {nos}")
    mnos = [s["chapter_no"] - MARTYRS for s in sections if s["chapter_no"] > MARTYRS]
    if mnos != list(range(1, len(mnos) + 1)):
        raise SystemExit(f"{work['html']}: Martyrs chapters are not numbered 1..n: {mnos}")
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


def pack_greedily(sections, cap):
    """Cut a list of sections into runs of consecutive chapters, each as long as fits under
    `cap` (as in the Isaac importer: an even split gave stray tiny pieces next to the big
    chapters). A run never crosses from the Church History into the Martyrs of Palestine."""
    runs, cur, acc = [], [], 0
    for s in sections:
        n = len(s["html"])
        crossing = cur and (cur[-1]["chapter_no"] < MARTYRS) != (s["chapter_no"] < MARTYRS)
        if cur and (acc + n > cap or crossing):
            runs.append(cur)
            cur, acc = [], 0
        cur.append(s)
        acc += n
    if cur:
        runs.append(cur)
    return runs


def _label(no):
    """A chapter key in a piece name: "07", or "M03" for the Martyrs of Palestine's."""
    return f"M{no - MARTYRS:02d}" if no >= MARTYRS else f"{no:02d}"


def make_units(preamble, sections, cap):
    """The ordered list of pieces: {name, chapter, sections}; a piece is a run of whole
    chapters, named by its first and last chapter."""
    units = []
    for run in pack_greedily(sections, cap):
        a, b = (_label(run[0]["chapter_no"]), _label(run[-1]["chapter_no"]))
        units.append({
            "name": f"Part{len(units) + 1:03d}_Ch{a}-{b}.html",
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
    "We have Eusebius of Caesarea's \"{title}\" ({work_ref}) here: "
    "\"{units_dir}/{first_unit}\" with the files continuing up to \"{units_dir}/{last_unit}\". "
    "These are consecutive pieces cut, in order, from our PUBLIC-DOMAIN English translation of "
    "the {unit} (Arthur Cushman McGiffert's, 1890), \"{html_path}\" (consult it if you need "
    "surrounding context).\n\n"
    "THIS IS NOT A COMMENTARY. {about} Your task is to EXTRACT from the piece the stretches "
    "in which EUSEBIUS HIMSELF genuinely comments on a specific verse of Scripture, and file "
    "each under that verse in the \"{father}/\" folder. Most of the text will NOT be imported, "
    "and that is expected: a chapter with no exposition of a verse by Eusebius gives no block, "
    "and many whole pieces will give none.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its chapters: {headings})\n\n"
    "Read the WHOLE file. Each piece repeats the {unit}'s title at the top; that is "
    "background for you, not text to import. Each chapter's <h2> heading is the editor's title "
    "for it: a useful hint, but not text to import.\n\n"
    "EUSEBIUS'S OWN WORDS ONLY. Eusebius quotes long documents by other authors: Josephus, "
    "Philo, Africanus, Hegesippus, Papias, Justin, Irenaeus, Clement, Tertullian, Origen, "
    "Dionysius of Alexandria and others, letters of churches and bishops, and imperial edicts. "
    "Do NOT import those quotations, even where they expound Scripture (e.g. Africanus's "
    "letter on the genealogies of Christ, Papias on Mark and Matthew, Dionysius on who wrote "
    "the Apocalypse): they are other authors' words and belong to them (several are already "
    "filed under their own folders). Import only Eusebius's OWN comment: where he himself "
    "interprets a verse, including his comment introducing or drawing a conclusion from a "
    "quoted document (\"Thus far Africanus. And the lineage of Joseph being thus traced, Mary "
    "also is virtually shown to be ...\"). A block never includes the quoted author's words, "
    "except a short phrase Eusebius quotes inside his own sentence. Tell them apart by the "
    "quotation marks and by Eusebius's lead-in (\"he writes as follows:\", \"These things are "
    "related by ...\"); the notes below name the chief quoted documents in this book.\n\n"
    "WHAT COUNTS AS COMMENTARY. Import a stretch when Eusebius QUOTES or plainly refers to a "
    "specific verse AND DOES SOMETHING WITH IT: says what it means, interprets its words "
    "(literally or spiritually), resolves a difficulty in it, applies a figure or type in it, "
    "builds his argument on its wording, shows how a prophecy in it is FULFILLED in the events "
    "he narrates (e.g. Christ's words on Jerusalem fulfilled in the siege; Genesis 49:10 and "
    "Daniel's weeks fulfilled in Herod and the end of the Jewish rulers), reconciles it with "
    "another Gospel's account or with a historian's (e.g. the census of Luke 2:2, Theudas in "
    "Acts 5:36 and Josephus), or says who wrote a book of Scripture, when, and in what order, "
    "with an observation about its text (e.g. why John's Gospel begins where it does). Do NOT "
    "import a verse quoted only in passing, a bare proof-text, a chain of proof-texts without "
    "comment, narrative that merely mentions or retells Scripture, a bare list of the books "
    "of the canon, or martyr stories that only echo a verse. Ask: would a reader studying this "
    "verse learn something about how Eusebius understood it from this stretch? If so, import "
    "it; if it would only learn that Eusebius quoted it, leave it out.\n\n"
    "WHERE TO FILE. File each block under the SMALLEST verse range its exposition really "
    "addresses (\"We are interested in the commentary, not so much the lemma\": a long "
    "quotation never widens the range by itself). Where a stretch genuinely expounds two "
    "passages (a prophecy and the Gospel verse of its fulfilment; parallel Gospel accounts it "
    "reconciles), the same text goes under each. A range crossing chapters is written like "
    "\"Matthew 9_35-10_1\". Never put two overlapping blocks of this {unit} in the SAME file, "
    "and don't split one exposition into fragments under one verse.\n\n"
    "VERSE KEYS. McGiffert's footnotes are shown inline as \"[note: ...]\" in superscript, "
    "after the word they mark, each cut to its first ~300 characters (\" …\" marks a cut; the "
    "full note is in the html file's notes section). Many give the reference of a quotation "
    "(\"Ps. cx. 4.\", \"Cf. 1 Tim. vi. 20.\"); most are historical remarks with no verse. A note "
    "can sit on the wrong quotation, or be missing. Use the notes as HINTS only, and confirm "
    "every verse against the KJV wording with `" + KJV_LOOKUP + "`, filing under KJV "
    "book/chapter/verse numbering. Eusebius quotes the Septuagint, so his wording of the Old "
    "Testament often differs from the KJV's: match by sense. McGiffert gives the English "
    "(KJV) Psalm numbers; a psalm's title goes under its verse 1. Deuterocanonical books are "
    "fine (\"Sirach\", \"Wisdom\", ...): use only the book names in book_names.json.{notes}\n\n"
    "THE BLOCKS. Each block is ONE continuous, verbatim stretch of the text, in Eusebius's "
    "order, starting and ending at sentence boundaries, and able to stand on its own: include "
    "the sentence(s) that bring in the passage (with its quotation) and the whole of his "
    "comment on it. Where he moves on to a different point about different verses, start a "
    "new block. Don't pad a block with narrative before or after the exposition.\n\n"
    "THE TEXT. Copy Eusebius's words VERBATIM: nothing abridged, paraphrased, corrected, "
    "added or rearranged. Drop the html tags (italics simply become plain text; don't turn "
    "them into quotation marks) and separate paragraphs with a single blank line. Leave out "
    "the \"[note: ...]\" footnotes and the <h2> chapter headings. The section numbers of the "
    "printed edition have already been removed: don't add any. Keep the translator's square "
    "brackets, the printed quotation marks (including the nested single quotes), the dashes "
    "\"—\", the accented names (\"Judæa\", \"Irenæus\"), the Greek words, and misprints "
    "exactly as they are. Don't add headings, verse numbers or notes of your own. Don't write "
    "a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY block you import from this {unit}, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}, Chapter N\"\n"
    "where N is the (Arabic) number of the chapter the block comes from, e.g. \"{source_title}, "
    "Chapter 13\" for a block from \"Chapter XIII.\"; a block running across chapters is "
    "\"{source_title}, Chapters 13-14\"; a block from the book's Introduction is "
    "\"{source_title}, Introduction\".{title_extra}\n\n"
    "EXISTING BLOCKS. The old imports of this work have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Earlier pieces of THIS run (and of the other books of the work) may "
    "already have left blocks from Eusebius's Church History in the files you write to: they "
    "are NOT old imports or duplicates; leave them exactly as they are and append yours after "
    "them. Blocks from other works must be left exactly as they are: Eusebius's Proof of the "
    "Gospel, Commentary on the Psalms, Commentary on Isaiah, Commentary on Luke, Gospel "
    "Problems and Solutions, and the Catena Aurea blocks (\"Catena Aurea by Aquinas\") that "
    "quote him; don't touch them, and don't skip a block of yours because one of them covers "
    "similar ground.\n\n"
    "WHEN YOU ARE DONE, list for the reviewer every block you wrote (file <- chapter, opening "
    "words), and every exposition of a verse you considered but left out, with the reason "
    "(including expositions in quoted documents you left out as not Eusebius's own)."
)

PROMPT2 = "Double check, was this fully imported properly?"


KIND_WORDING = {
    "history": {
        "work_ref": "Book {number} of his Church History",
        "unit": "book",
        "about": (
            "The Church History (completed about 325) tells the story of the Church from Christ "
            "to Constantine's victory: the successions of bishops, the writers and their books, "
            "the heresies, the persecutions and martyrs, and the fate of the Jews. Book 1 opens "
            "with Christ's pre-existence and divinity, the names Jesus and Christ, the newness "
            "and antiquity of the Christian religion, and the time of His coming (with "
            "prophecies fulfilled in it); the later books are mostly narrative and quoted "
            "documents, with Eusebius's own remarks on Scripture here and there (the "
            "fulfilment of prophecy, the authorship and order of the books of the New "
            "Testament, the Gospel accounts squared with Josephus). Book 10 includes "
            "Eusebius's own oration at the dedication of the church at Tyre (Chapter IV), "
            "which is full of Scripture."),
    },
}


def build_prompt1(work, units_dir, units, unit):
    notes = work.get("notes", "")
    words = KIND_WORDING[work["kind"]]
    title_extra = (
        " A block from the Martyrs of Palestine (printed after Chapter XVII, with its own "
        "chapters) is \"" + work["source_title"] + ", Martyrs of Palestine, Chapter N\" (N its "
        "own chapter number), and never runs across from Chapter XVII."
        if work["number"] == 8 else "")
    return PROMPT1_TEMPLATE.format(
        **{k: v for k, v in words.items() if k != "work_ref"},
        work_ref=words["work_ref"].format(number=work["number"]),
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
        title_extra=title_extra,
    )


# --- Deterministic post-import check ------------------------------------------


def _norm(s):
    # NFC, as in the Damascene importer (McGiffert prints some Greek).
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
    parser.add_argument("work", choices=sorted(WORKS), help="Which book of the Church History to import.")
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
        units = [{"name": f"Part001_Ch{_label(lo)}-{_label(hi)}.html", "chapter": None, "sections": run}]
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
