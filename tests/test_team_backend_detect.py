from Licode.team import BackendType
from Licode.team.backend.detect import detect


def test_detect_backend_priority(monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.backend.detect.shutil.which", lambda name: None)
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    assert detect() is BackendType.TMUX

    monkeypatch.delenv("TMUX")
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(
        "Licode.team.backend.detect.shutil.which",
        lambda name: "/bin/it2" if name == "it2" else None,
    )
    assert detect() is BackendType.ITERM2

    monkeypatch.delenv("TERM_PROGRAM")
    monkeypatch.setattr(
        "Licode.team.backend.detect.shutil.which",
        lambda name: "/bin/tmux" if name == "tmux" else None,
    )
    assert detect() is BackendType.TMUX

    monkeypatch.setattr("Licode.team.backend.detect.shutil.which", lambda name: None)
    assert detect() is BackendType.IN_PROCESS
