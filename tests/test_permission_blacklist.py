import pytest

from Licode.permission.blacklist import hits_blacklist


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr ~",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
        "echo x > /dev/nvme0n1",
        "chmod -R 777 /",
    ],
)
def test_dangerous_commands_hit_immutable_blacklist(command: str) -> None:
    assert hits_blacklist(command)


@pytest.mark.parametrize("command", ["rm -rf ./build", "git status", "ls -la"])
def test_normal_commands_do_not_hit_blacklist(command: str) -> None:
    assert not hits_blacklist(command)
