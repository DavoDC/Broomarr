"""The dependency boundary the design draws at the directory level:
src/broomarr.py and src/reclaim.py stay standard-library-only forever,
even though gui/ is free to depend on whatever it needs. If the GUI ever
becomes load-bearing for a decision this test starts failing, and that
failure is the whole point of writing it - see
docs/design/gui-design.md "The stack decision".
"""

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
GUI_MAIN = os.path.join(REPO_ROOT, "gui", "main.py")


def _source_of(module_filename):
    with open(os.path.join(SRC_DIR, module_filename), encoding="utf-8") as fh:
        return fh.read()


def test_broomarr_source_contains_no_nicegui_reference():
    assert "nicegui" not in _source_of("broomarr.py")


def test_reclaim_source_contains_no_nicegui_reference():
    assert "nicegui" not in _source_of("reclaim.py")


def _nicegui_blocking_finder_script(import_line):
    """A meta-path finder built on find_spec(), not the deprecated (and,
    as of Python 3.12+, no-longer-consulted) find_module() hook - a
    finder written with find_module() silently never fires on a current
    interpreter, so it would "pass" this whole test suite without ever
    blocking anything. find_spec() is checked by importlib on every
    supported version, so this one genuinely refuses the import.
    """
    return (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "class _BlockNiceGUI:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'nicegui' or name.startswith('nicegui.'):\n"
        "            raise ImportError('nicegui deliberately blocked for this test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _BlockNiceGUI())\n"
        "%s\n"
        "print('OK')\n"
    ) % (SRC_DIR, import_line)


def test_the_blocking_finder_genuinely_blocks_nicegui():
    """A self-check on the finder itself, not on broomarr/reclaim: proves
    the block is real by attempting "import nicegui" (installed in this
    dev environment) in the same subprocess and requiring it to fail.
    Without this, a finder that silently never fires - such as one built
    on the removed find_module() hook - would let every import through
    and this whole test file would pass for the wrong reason.
    """
    script = _nicegui_blocking_finder_script("import nicegui")
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, (
        "the blocking finder failed to block \"import nicegui\" - it is "
        "not actually blocking anything, so it proves nothing:\n"
        + result.stdout + result.stderr)
    assert "nicegui deliberately blocked for this test" in result.stderr


def test_broomarr_and_reclaim_import_with_nicegui_blocked():
    """Runs in a fresh subprocess with a meta-path finder that refuses to
    import "nicegui" at all, standing in for "NiceGUI uninstalled" without
    requiring an actual separate virtualenv. broomarr and reclaim must
    import cleanly regardless - proof that neither one needs it.
    """
    script = _nicegui_blocking_finder_script("import broomarr\nimport reclaim")
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        "broomarr/reclaim failed to import with nicegui blocked:\n"
        + result.stdout + result.stderr)
    assert "OK" in result.stdout


def test_gui_binds_localhost_not_0000():
    with open(GUI_MAIN, encoding="utf-8") as fh:
        source = fh.read()
    assert '"0.0.0.0"' not in source and "'0.0.0.0'" not in source
    assert "localhost" in source
