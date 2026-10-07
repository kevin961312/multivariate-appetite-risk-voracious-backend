import pymrcd


def test_version_is_exposed() -> None:
    assert pymrcd.__version__ == "0.1.0"
