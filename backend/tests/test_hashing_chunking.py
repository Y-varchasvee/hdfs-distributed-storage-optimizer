import hashlib

import pytest
from app.services.hashing import (
    fixed_size_chunks,
    sha256_bytes,
    sha256_file,
    sha256_stream,
)
from conftest import pattern


def test_sha256_matches_known_vector():
    # FIPS 180 test vector for "abc".
    assert sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_of_empty_input():
    assert sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_file_and_stream_hash_agree_with_hashlib(tmp_path):
    data = pattern(1, 3 * 1024 * 1024 + 17)
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_file(path) == (expected, len(data))
    assert sha256_stream([data[:5], data[5:]]) == (expected, len(data))


@pytest.mark.parametrize("input_block", [1, 7, 4096, 100_000])
def test_chunking_does_not_depend_on_input_buffering(input_block):
    data = pattern(2, 50_000)
    stream = [data[i : i + input_block] for i in range(0, len(data), input_block)]
    assert list(fixed_size_chunks(stream, 4096)) == list(fixed_size_chunks([data], 4096))


def test_chunks_have_exact_size_and_rejoin_to_the_original():
    data = pattern(3, 10_001)
    chunks = list(fixed_size_chunks([data], 4096))
    assert [len(c) for c in chunks] == [4096, 4096, 1809]
    assert b"".join(chunks) == data


def test_exact_multiple_has_no_empty_tail():
    chunks = list(fixed_size_chunks([pattern(4, 8192)], 4096))
    assert [len(c) for c in chunks] == [4096, 4096]


def test_empty_stream_yields_no_chunks():
    assert list(fixed_size_chunks([], 4096)) == []


def test_invalid_chunk_size_is_rejected():
    with pytest.raises(ValueError):
        list(fixed_size_chunks([b"x"], 0))
