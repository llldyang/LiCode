from pathlib import Path

from Licode.session import Writer


def test_writer_path_is_absolute_and_exists(tmp_path: Path) -> None:
    with Writer(str(tmp_path)) as writer:
        assert Path(writer.path).is_absolute()
        assert Path(writer.path).is_file()
