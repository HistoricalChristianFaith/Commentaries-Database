# Commentaries-Database

## Latest Release

Get the latest compiled sqlite database with all this data in the [Releases on this repository](https://github.com/HistoricalChristianFaith/Commentaries-Database/releases).

## Compile yourself

To compile these files into a single data object, use the "compile_data.py" script in this repository. It's a python3 script, and requires you to `pip install rtoml` first. You can select CSV, SQLITE, or JSON as the output format (resulting in a new file called data.json, data.csv, or data.sqlite).

Invoke it like so:

```
python3 compile_data.py csv -o data.csv
python3 compile_data.py sqlite -o data.sqlite
python3 compile_data.py json -o data.json
```

The full argument system can be seen here:

```commandline
$ python compile_data.py --help
usage: CompileData [-h] [-o OUT] {json,csv,sqlite,dryrun}

Compiles the Commentaries Database into various formats

positional arguments:
  {json,csv,sqlite,dryrun}

optional arguments:
  -h, --help            show this help message and exit
  -o OUT, --out OUT
```

## Implementation

[Here is our reference implementation](https://github.com/HistoricalChristianFaith/Website-Interface) of the sqlite file being utilized in a simple PHP app to show commentaries for a user-specified passage of the Bible.

There are also a number of other applications that have started making use of this database! Check them out:

- [biblesearch.es](https://www.biblesearch.es) (semantic Bible search engine)
- [Catena Vetus](https://github.com/jimbob88/CatenaVetus) (A Terminal User Interface frontend for Historical Christian Commentaries which does not require an internet connection)

(Got a project of your own using this database? Open a pull request to add it here!)

## FILE NAME FORMATS:

```
[Father-Name]/[Book-Name] Chapter_Verse.toml
[Father-Name]/[Book-Name] Chapter_Verse-Verse.toml
[Father-Name]/[Book-Name] Chapter_Verse-Chapter_Verse.toml
```

Examples:

- A commentary by Augustine on Matthew 23:35 = Filename: `Augustine/Matthew 23_35.toml`
- A commentary by Jerome on Matthew 23:35-41 = Filename: `Jerome/Matthew 23_35-41.toml`
- A commentary by Basil of Caesarea on 1 Kings 19:10-20:3 = Filename: `Basil of Caesarea/1 Kings 19_10-20_3.toml`

So the basic rule is write the 'long form' name of everything (books/people), and replace colons (:) with underscores (_). That's it.

## FAQ

<details>
    <summary><b>Why do we use the long form of people's names? Why Augustine of Hippo, rather than just Augustine?</b></summary>

The reason for this is simple enough - In his Catena Aurea, Aquinas lists "Maximus" as the author for several commentaries.

On a Maximus commentary of Luke 3:7-9, Aquinas prefixes the quotation with "lib. Ascet.", which easily enough points to Liber Asceticus, a writing by [Maximus the Confessor](https://en.wikipedia.org/wiki/Maximus_the_Confessor#Writings).

However on a Maximus commentary on Luke 2:8-12 and Matthew 3:1-3, Aquinas prefixes the quotations with "in Serm. Nativ. 4." and "Hom. in Joan. Bap. nat. 1." - and it does not appear Maximus the Confessor left us any sermons or homilies [among his writings](https://en.wikipedia.org/wiki/Maximus_the_Confessor#Writings). However Maximus of Turin [left many of both](https://en.wikipedia.org/wiki/Maximus_of_Turin#Works), and is likely these source for these commentaries Aquinas quoted.

Having to dig into problems like that increase the rate at which my gray hair grows, therefore we seek the most descriptive names possible for each person in this repo.

We also accept that for some people, it is not possible/necessary. For example, `Jerome` is universally understood to refer to a single man, and he doesn't have any kind of commonly known longer-form name. However, while `Augustine` is universally understood to refer to a single man, he does have a common longer-form name which we therefore use, `Augustine of Hippo`.
</details>

<details>
    <summary><b>Why Psalms instead of Psalm? / Which version of a book's name do we use?</b></summary>

We're standardizing on [these names](https://github.com/HistoricalChristianFaith/Commentaries-Interface/blob/master/func.php#L82), which are basically just based off of [this Logos page](https://www.logos.com/bible-book-abbreviations).
</details>

<details>
    <summary><b>How do we handle Church Father quotations of heretics who are quoting Bible passages?</b></summary>

There is a common problem when automating importation of bulk commentaries from early church fathers, where certain commentaries from early church fathers are ascribed to them, but in reality in that work the church father was quoting a heretic verbatim in order to refute him later on - and the commentary came from the heretic (that the church father was quoting) and not the church father themselves. It is important to avoid putting this as a commentary under the church father, in that case (or if it's done accidentally, when one stumbles across it - removing it).
</details>

## File Contents Format

Each file is in a format called [TOML](https://github.com/toml-lang/toml). This format fits well, as it's a nice balance of human readable/editable and machine-readable.

A single file can contain multiple "commentaries".

A "commentary" consists of:

- Mandatory keys
    - `quote`: The source quotation, can include unicode as HTML entities but should not include any html
    - `source_title`: The work the quotation is from.
- Optional keys
    - `source_url`: Strongly recommended/preferred to have. A link to the work available online, preferably in the public domain. If not available in public domain, then a link to the Google book is acceptable.
    - `append_to_author_name`: Use this for things like when you are quoting from a secondary source, e.g. if Aquinas said that Jerome said something, put the quote under Jerome, but in append_to_author_name put the value " (as quoted by Aquinas, AD 1274)"
    - `time`: The year A.D. that the writing was written. Use a negative value for B.C. Should be just a single numerical value. If not supplied, defaults to metadata.toml's value (which is often the death year of the Church Father). Note that 9999 is a special value, used to indicate "unknown date" (9999 is used to make it sort to the end of all other entries, when sorted by date).

Minimal Example:

```
[[commentary]]
quote = '''
commentary by a church father goes here.
'''
source_url = 'https://example.com'
source_title = 'Name of book church father wrote'
```

Kitchen-Sink Example:

```
[[commentary]]
quote = '''
Long quotation from a church father

This text is on a new line
'''
append_to_author_name = ' (as quoted by Aquinas, AD 1274)'
time = 383
source_url='https://ccel.org/ccel/aquinas/catena1/catena1.i.html'
source_title='Catena Aurea by Aquinas'
```

## Pull Requests

Want to make a contribution to the repository? See below for details on file formats, and see [this pull request](https://github.com/HistoricalChristianFaith/Commentaries-Database/pull/1) for an example. We use the pull request feature to add notes/discussion about sources and such.

## Useful Tools

#### Sites that have many church father texts available for free online:

* https://www.ccel.org/
* https://www.newadvent.org/fathers/
* https://www.tertullian.org/fathers/ and https://www.tertullian.org/fathers2/
* https://earlychristianwritings.com/churchfathers.html
* https://catholiclibrary.org/library/browse/ [*Latin texts]
* https://www.thelatinlibrary.com/christian.html [*More Latin texts]
* https://mlat.uzh.ch/ [Migne's Patrologia Latina] [Link2](https://www.roger-pearse.com/weblog/patrologia-latina-pl-volumes-available-online/) [Link3](https://docs.google.com/spreadsheets/d/e/2PACX-1vRkUFBfVVqv5Tr2aZS4apFNpTJ-ys6VqeQxgsAI1v7cH5putIgchYWJAVGHuu0lWGmdD2DU7Vb1o7XH/pubhtml#)
* https://github.com/OGL-PatrologiaGraecaDev [OCR version of Patrologia Graeca]
* http://khazarzar.skeptik.net/pgm/PG_Migne/ [Another OCR version of PG]
* https://scaife.perseus.org/library/ [More texts online]
* https://stephanus.tlg.uci.edu/abridged.php
* https://roger-pearse.com/wiki/index.php?title=Main_Page [Encyclopedia of Syriac Literature]
* https://github.com/OpenGreekAndLatin/csel-dev/ [Corpus Scriptorum Ecclesiasticorum Latinorum: a machine-corrected EpiDoc version of public domain volumes of the monumental collection of Latin Church Fathers]
* https://docs.google.com/spreadsheets/d/e/2PACX-1vRkUFBfVVqv5Tr2aZS4apFNpTJ-ys6VqeQxgsAI1v7cH5putIgchYWJAVGHuu0lWGmdD2DU7Vb1o7XH/pubhtml?gid=627485545 [List of links]
* [$$$] [The Church's Bible project](https://www.amazon.com/Matthew-Churchs-Bible-D-H-Williams/dp/0802825788)

#### Alternative Commentary Collections

- https://catenabible.com
    - The most polished app, and a wonderful bible companion!
    - It's a closed database, which contains data from a wide variety of sources (not just the ANF/NPNF series)
    - Negatives:
        - It identifies the person behind a quote, but not the work in which the quote appears.
        - Its commentaries are tied only to individual verses (and not passages that span multiple verses) 
        - Its commentaries from the ANF/NPNF often are lacking context / are cut off.

- https://www.earlychristianwritings.com/e-catena/
    - A wonderful quick reference
    - Only includes citations from the ANF/NPNF
    - But does identify the work in which a quote appears, AND provides a link directly to that work!
    
- https://www.catholiccrossreference.online/fathers/
    - Similar to earlychristianwritings.com/e-catena
    - Uses citations from the ANF/NPNF
    - Identifies the work in which a quote appears, AND provides a link directly to that work!

- https://www.biblindex.org/
    - The most... scholarly?
    - Laborious to use
    - Requires a bigger brain than I have.

- [Ancient Christian Commentary on Scripture](https://www.logos.com/product/31152/ancient-christian-commentary-on-scripture-complete-set-accs)
    - Contains commentaries from a wide variety of sources, many of which appear to be custom translated just for this product!
    - Identifies the work in which a quote appears, and often provides good historical background!
    - The commentaries shown are not exhaustive, but are curated... usually with just a couple chosen per verse.
    - Costs enough to empty your wallet.
    

- https://jennica.github.io/fathers/bible/bible.html