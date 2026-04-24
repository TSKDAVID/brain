from app.indexing.chunking import split_into_chunks


def test_split_empty():
    assert split_into_chunks("") == []
    assert split_into_chunks("   ") == []


def test_split_paragraphs_merged_when_small():
    text = "A\n\nB\n\nC"
    chunks = split_into_chunks(text, max_chars=100)
    assert len(chunks) == 1


def test_split_paragraphs_separate_when_large():
    text = ("A" * 800) + "\n\n" + ("B" * 800) + "\n\n" + ("C" * 800)
    chunks = split_into_chunks(text, max_chars=900)
    assert len(chunks) >= 2


def test_split_long_paragraph():
    long_p = "x" * 2500
    chunks = split_into_chunks(long_p, max_chars=1200)
    assert len(chunks) >= 2
    assert all(len(c) <= 1200 for c in chunks)
