"""
Splits a document into chunks that carry the heading of the section they came from.
"""

import re
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
HEADING_MAX = 90

DIVIDER = re.compile(r"^[=\-_*~#]{4,}[ \t]*$")
SUBSECTION = re.compile(r"^\d+\.\d+")
BLANK_RUN = re.compile(r"\n{3,}")
WORD_BREAK = re.compile(r"[_\-]+")
VERSION_SUFFIX = re.compile(r"[-_. ]v\d+(\.\d+)*$", re.I)

splitter = RecursiveCharacterTextSplitter(chunk_size = CHUNK_SIZE,
                                          chunk_overlap = CHUNK_OVERLAP)

def is_divider(line):
    return bool(DIVIDER.match(line.strip()))

def headings(lines):
    # an underlined short line is the only heading signal that holds across the corpus:
    # testing for upper case also matches error codes, ascii table rows and the
    # upper-case top level of a table of contents
    found = {}
    for i, line in enumerate(lines):
        text = line.strip()
        following = lines[i + 1] if i + 1 < len(lines) else ""
        if text and len(text) <= HEADING_MAX and any(c.isalpha() for c in text) \
                and is_divider(following):
            found[i] = text
    return found

def sections(text):
    lines = text.splitlines()
    found = headings(lines)
    blocks = []
    section = ""

    for i, line in enumerate(lines):
        if is_divider(line): # dividers carry no meaning once they have marked the heading
            continue

        heading = found.get(i)
        if heading and not SUBSECTION.match(heading):
            section = heading

        if blocks and blocks[-1][0] == section:
            blocks[-1][1].append(line)
        else:
            blocks.append([section, [line]])

    return [[section, BLANK_RUN.sub("\n\n", "\n".join(body)).strip()]
            for section, body in blocks]

def title(source):
    # the version suffix has to come off: it is part of the chunk text, so leaving it in
    # makes an unedited passage differ between v1 and v2 and no longer test byte-identical
    return WORD_BREAK.sub(" ", VERSION_SUFFIX.sub("", source.rsplit(".", 1)[0])).strip()

def family(source):
    return title(source).lower()

def split(text, source):
    # naming the subject in a question used to cost recall: only the title, warranty and
    # overview chunks say "Nexus-9000", so the specification that answers it was ranked
    # below them. Every chunk carries the document name for that reason.
    label = title(source)
    chunks = []

    for section, body in sections(text):
        if not body:
            continue

        for piece in splitter.split_text(body):
            # a question asks in the vocabulary of the section title, and a chunk cut from
            # the middle of a section does not otherwise contain it. The piece that opens a
            # section already leads with the title, so repeating it there only weights it twice.
            heading = f"{label} | {section}" if section and not piece.startswith(section) else label
            chunks.append(f"[{heading}]\n{piece}")

    return chunks
