# Commentaries-Database

See this database in action at https://historicalchristian.faith/

To compile these files into a single data object, use the "compile_data.py" script in this repository. It's a python3 script, and requires you to `pip install tomlkit` first. You can select CSV, SQLITE, or JSON as the output format (resulting in a new file called data.json, data.csv, or data.sqlite). 

Invoke it like so:
```
python3 compile_data.py csv
python3 compile_data.py sqlite
python3 compile_data.py json
```

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

<details>
    <summary><b>Why do we use the long form of people's names? Why Augustine of Hippo, rather than just Augustine?</b></summary>

The reason for this is simple enough - In his Catena Aurea, Aquinas lists "Maximus" as the author for several commentaries. 

On a Maximus commentary of Luke 3:7-9, Aquinas prefixes the quotation with "lib. Ascet.", which easily enough points to Liber Asceticus, a writing by [Maximus the Confessor](https://en.wikipedia.org/wiki/Maximus_the_Confessor#Writings). 

However on a Maximus commentary on Luke 2:8-12 and Matthew 3:1-3, Aquinas prefixes the quotations with "in Serm. Nativ. 4." and "Hom. in Joan. Bap. nat. 1." - and it does not appear Maximus the Confessor left us any sermons or homilies [among his writings](https://en.wikipedia.org/wiki/Maximus_the_Confessor#Writings). However Maximus of Turin [left many of both](https://en.wikipedia.org/wiki/Maximus_of_Turin#Works), and is likely these source for these commentaries Aquinas quoted.

Having to dig into problems like that increase the rate at which my gray hair grows, therefore we seek the most descriptive names possible for each person in this repo.

We also accept that for some people, it is not possible/necessary. For example, `Jerome` is universally understood to refer to a single man, and he doesn't have any kind of commonly known longer-form name. However, while `Augustine` is universally understood to refer to a single man, he does have a common longer-form name which we therefore use, `Augustine of Hippo`.
</details>


## File Contents Format

Each file is in a format called [TOML](https://github.com/toml-lang/toml). This format fits well, as it's a nice balance of human readable/editable and machine-readable.

A single file can contain multiple "commentaries". 

A "commentary" consists of:

- Mandatory keys
    - `quote`: The source quotation, can include unicode as HTML entities but should not include any html
    - `sources`: One or more "url" and "title" values, should always include at least one source.
- Optional keys
    - `append_to_author_name`: Use this for things like when you are quoting from a secondary source, e.g. if Aquinas said that Jerome said something, put the quote under Jerome, but in append_to_author_name put the value " (as quoted by Aquinas, AD 1274)"
    - `time`: The year A.D. that the writing was written. Use a negative value for B.C. Should be just a single numerical value. If not supplied, defaults to metadata.toml's value (which is often the death year of the Church Father)

Minimal Example:
```
[[commentary]]
quote = '''
commentary by a church father goes here.
'''
[[commentary.sources]]
url = 'https://example.com'
title = 'Name of book church father wrote'
```

Kitchen-Sink Example:
```
[[commentary]]
quote = '''
short quotation from a church father with multiple sources
'''
append_to_author_name = ' (as quoted by Aquinas, AD 1274)'

[[commentary.sources]]
url='https://www.ecatholic2000.com/catena/untitled-111.shtml'
title='Catena Aurea by Aquinas'

[[commentary.sources]]
url='https://ccel.org/ccel/aquinas/catena1/catena1.i.html'
title='Catena Aurea by Aquinas'

[[commentary]]
quote = '''
Long quotation from a church father

This text is on a new line
'''
time = 383

[[commentary.sources]]
url = 'https://www.newadvent.org/fathers/3007.htm'
title = 'Against Helvidius'
```
