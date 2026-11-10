"""Thử tái cấu trúc tts-tool trên một bản sao (chạy ở gốc repo). Chỉ di chuyển + sửa import/đường dẫn."""
import re
import subprocess
from pathlib import Path

R = Path(".").resolve()


def mv(a, b):
    b = R / b
    b.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "mv", a, str(b)], check=True, cwd=R)


G = "giongviet"
MOVES = {
    "server.py": f"{G}/server.py", "library.py": f"{G}/library.py",
    "settings.py": f"{G}/settings.py", "history.py": f"{G}/history.py",
    "text_normalize.py": f"{G}/speech/text_normalize.py", "lexicon.py": f"{G}/speech/lexicon.py",
    "sfx.py": f"{G}/speech/sfx.py", "dialogue.py": f"{G}/speech/dialogue.py",
    "books.py": f"{G}/books/store.py", "bookq.py": f"{G}/books/jobs.py",
    "narrate.py": f"{G}/books/narrate.py", "cast.py": f"{G}/books/cast.py",
    "voice_age.py": f"{G}/books/voice_age.py", "html_import.py": f"{G}/books/html_import.py",
    "exporter.py": f"{G}/books/exporter.py",
    "engines": f"{G}/engines",
    "app.py": f"{G}/desktop/app.py", "app_gtk.py": f"{G}/desktop/gtk.py",
    "desktop/giong-viet.svg": f"{G}/desktop/giong-viet.svg",
    "static": "web",
    "scripts/masked_words.txt": "config/masked_words.txt",
    "scripts/vi-du-chuong-1.txt": "tests/fixtures/vi-du-chuong-1.txt",
    "scripts/install_desktop.sh": "packaging/linux/install_desktop.sh",
    "scripts/uninstall_desktop.sh": "packaging/linux/uninstall_desktop.sh",
    "PROMPTS.md": "docs/prompts/PROMPTS.md", "PROMPTS-UX.md": "docs/prompts/PROMPTS-UX.md",
}
for f in ["smoke_test.sh", "smoke_books.py", "smoke_queue.py", "smoke_ui.py"]:
    MOVES[f"scripts/{f}"] = f"tests/smoke/{f}"
for f in ["bench_vieneu", "clean_html", "lexicon_probe", "measure_pauses", "mix_experiment",
          "normalize_probe", "perf_books", "webview_probe", "webview_dnd_source"]:
    MOVES[f"scripts/{f}.py"] = f"tools/{f}.py"
for a, b in MOVES.items():
    mv(a, b)
for d in ["scripts", "desktop"]:
    if (R / d).exists() and not any((R / d).iterdir()):
        (R / d).rmdir()

for pkg in [G, f"{G}/speech", f"{G}/books", f"{G}/desktop"]:
    (R / pkg / "__init__.py").touch()
(R / G / "paths.py").write_text('''"""Mọi đường dẫn cố định của dự án ở một chỗ."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # gốc repo
WEB = ROOT / "web"                               # giao diện (HTML/CSS/JS, không build)
CONFIG = ROOT / "config"                         # file người dùng sửa được
''')
(R / G / "__main__.py").write_text('''"""python -m giongviet: chạy server web (thay cho `python server.py`)."""
import runpy

runpy.run_module("giongviet.server", run_name="__main__")
''')
(R / G / "desktop" / "__main__.py").write_text('''"""python -m giongviet.desktop: app cửa sổ riêng."""
import sys

from giongviet.desktop.app import main

sys.exit(main())
''')

# module cũ → câu import mới (giữ tên biến cũ để không phải sửa chỗ gọi)
NEW = {
    "library": f"from {G} import library", "settings": f"from {G} import settings",
    "history": f"from {G} import history", "server": f"from {G} import server",
    "text_normalize": f"from {G}.speech import text_normalize", "lexicon": f"from {G}.speech import lexicon",
    "sfx": f"from {G}.speech import sfx", "dialogue": f"from {G}.speech import dialogue",
    "books": f"from {G}.books import store as books", "bookq": f"from {G}.books import jobs as bookq",
    "narrate": f"from {G}.books import narrate", "cast": f"from {G}.books import cast",
    "voice_age": f"from {G}.books import voice_age", "html_import": f"from {G}.books import html_import",
    "exporter": f"from {G}.books import exporter",
}
FROM = {"engines": f"{G}.engines", "html_import": f"{G}.books.html_import"}


def fix_imports(src: str) -> str:
    def plain(m):
        ind, mod, alias, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        if mod not in NEW:
            return m.group(0)
        stmt = NEW[mod]
        if alias:
            stmt = re.sub(r" as \w+$", "", stmt) + f" as {alias}"
        return f"{ind}{stmt}{rest}"

    src = re.sub(r"^([ \t]*)import (\w+)(?: as (\w+))?([ \t]*(?:#.*)?)$", plain, src, flags=re.M)
    src = re.sub(r"^([ \t]*)from (engines)(\.\w+)? import ", lambda m: f"{m.group(1)}from {FROM['engines']}{m.group(3) or ''} import ", src, flags=re.M)
    src = re.sub(r"^([ \t]*)from html_import import ", rf"\1from {FROM['html_import']} import ", src, flags=re.M)
    src = re.sub(r"^([ \t]*)import app_gtk as (\w+)", rf"\1from {G}.desktop import gtk as \2", src, flags=re.M)
    return src


for p in list((R / G).rglob("*.py")) + list((R / "tools").glob("*.py")) + list((R / "tests").rglob("*.py")):
    s = p.read_text()
    t = fix_imports(s)
    if t != s:
        p.write_text(t)


def sub(path, a, b, count=1):
    p = R / path
    s = p.read_text()
    assert a in s, (path, a)
    p.write_text(s.replace(a, b, count))


E = f"{G}/engines"
sub(f"{E}/registry.py", '"engines.edge:EdgeEngine"', f'"{G}.engines.edge:EdgeEngine"')
sub(f"{E}/registry.py", '"engines.vieneu:VieNeuEngine"', f'"{G}.engines.vieneu:VieNeuEngine"')
sub(f"{G}/library.py", 'Path(__file__).parent / "data"', "paths.ROOT / \"data\"")
sub(f"{G}/library.py", "\nimport os\n", f"\nimport os\n\nfrom {G} import paths\n")
sub(f"{G}/books/store.py", 'Path(__file__).resolve().parent / "scripts" / "masked_words.txt"', 'paths.CONFIG / "masked_words.txt"')
sub(f"{G}/books/store.py", f"from {G} import library", f"from {G} import library, paths")
sub(f"{G}/books/narrate.py", 'Path(__file__).resolve().parent / "config" / "speech_verbs.txt"', 'paths.CONFIG / "speech_verbs.txt"')
sub(f"{G}/books/narrate.py", f"from {G}.books import cast as castmod", f"from {G} import paths\nfrom {G}.books import cast as castmod")
sub(f"{G}/speech/lexicon.py", 'Path(__file__).resolve().parent / "config" / "name_stopwords.txt"', 'paths.CONFIG / "name_stopwords.txt"')
sub(f"{G}/speech/lexicon.py", f"from {G} import library", f"from {G} import library, paths")
sub(f"{G}/server.py", "ROOT = Path(__file__).parent", "ROOT = paths.WEB.parent  # gốc repo")
s = (R / G / "server.py").read_text().replace('ROOT / "static"', "paths.WEB")
(R / G / "server.py").write_text(s)
sub(f"{G}/server.py", f"from {G} import library", f"from {G} import library, paths")
A = f"{G}/desktop/app.py"
sub(A, "ROOT = Path(__file__).resolve().parent", f"from {G}.paths import ROOT, WEB  # noqa: E402  (app.py có hàm paths() riêng, đừng import module paths)")
sub(A, 'ROOT / "desktop" / "giong-viet.svg"', 'Path(__file__).resolve().parent / "giong-viet.svg"')
sub(A, 'ROOT / "static" / "css" / "app-window.css"', 'WEB / "css" / "app-window.css"')
sub(A, '[sys.executable, str(ROOT / "app.py"), "/giong"]', f'[sys.executable, "-m", "{G}.desktop", "/giong"]')
sub(A, 'sys.modules.get("bookq")', f'sys.modules.get("{G}.books.jobs")')
s = (R / A).read_text()
s = re.sub(r'\[sys\.executable, str\(Path\(__file__\)\.resolve\(\)\), "--selftest"\]',
           f'[sys.executable, "-m", "{G}.desktop", "--selftest"]', s)
(R / A).write_text(s)

# tools/ + tests/smoke: bỏ hack sys.path (cài `pip install -e .`), sửa đường dẫn
for p in list((R / "tools").glob("*.py")) + list((R / "tests/smoke").glob("*.py")):
    s = p.read_text()
    s = re.sub(r"^sys\.path\.insert\(0, str\(.*\)\)\s*(#.*)?\n", "", s, flags=re.M)
    s = re.sub(r"^(\s+)sys\.path\.insert\(0, str\(ROOT\)\)\n", "", s, flags=re.M)
    s = s.replace("Path(__file__).resolve().parent.parent", "Path(__file__).resolve().parents[2]" if "tests" in str(p) else "Path(__file__).resolve().parent.parent")
    s = s.replace('[PY, "server.py"]', f'[PY, "-m", "{G}"]')
    p.write_text(s)
sub("tools/clean_html.py", 'default=str(HERE / "masked_words.txt")', 'default=str(HERE.parent / "config" / "masked_words.txt")')

for p in (R / "tests/js").glob("*.mjs"):
    s = p.read_text().replace("../../static/", "../../web/")
    p.write_text(s)
# shell: đường dẫn + Python nhúng trong heredoc
sh = R / "tests/smoke/smoke_test.sh"
t = sh.read_text()
for a, b in [('cd "$(dirname "$0")/.."', 'cd "$(dirname "$0")/../.."'), ("scripts/smoke_test.sh", "tests/smoke/smoke_test.sh"),
             ("$PY server.py", f"$PY -m {G}"), ("$PY scripts/smoke_", "$PY tests/smoke/smoke_"),
             ("$PY scripts/measure_pauses.py", "$PY tools/measure_pauses.py"), ("static/js/", "web/js/"),
             ("sys.path.insert(0, '.'); import app_gtk", f"import {G}.desktop.gtk"),
             ('"$PY" app.py --selftest', f'"$PY" -m {G}.desktop --selftest'), ("app.py --selftest", f"-m {G}.desktop --selftest")]:
    t = t.replace(a, b)
sh.write_text(fix_imports(t))
for n in ["install_desktop.sh", "uninstall_desktop.sh"]:
    f = R / "packaging/linux" / n
    t = f.read_text()
    for a, b in [('"$(dirname "${BASH_SOURCE[0]}")/.."', '"$(dirname "${BASH_SOURCE[0]}")/../.."'),
                 ("scripts/uninstall_desktop.sh", "packaging/linux/uninstall_desktop.sh"),
                 ("scripts/install_desktop.sh", "packaging/linux/install_desktop.sh"),
                 ("pip install -r requirements.txt", 'pip install -e ".[vieneu]"'),
                 ('"$PY" -m pip install -q -r "$REPO/requirements-app.txt"', '"$PY" -m pip install -q -e "$REPO[app]"'),
                 ('(cd "$REPO" && "$PY" -c "import app_gtk" 2>&1)', f'("$PY" -c "import {G}.desktop.gtk" 2>&1)'),
                 ("app_gtk.py báo", f"{G}/desktop/gtk.py báo"),
                 ('exec "$PY" "$REPO/app.py" "\\$@"', f'exec "$PY" -m {G}.desktop "\\$@"'),
                 ('"$REPO/desktop/giong-viet.svg"', f'"$REPO/{G}/desktop/giong-viet.svg"')]:
        t = t.replace(a, b)
    f.write_text(t)

# requirements*.txt + ruff.toml → pyproject.toml (nội dung lấy từ file mẫu cạnh script)
(R / "pyproject.toml").write_text((Path(__file__).parent / "pyproject.toml").read_text())
subprocess.run(["git", "rm", "-q", "requirements.txt", "requirements-app.txt", "requirements-dev.txt", "ruff.toml"], check=True, cwd=R)
subprocess.run(["git", "add", "-A"], check=True, cwd=R)
# sắp lại import + bỏ import thừa do đổi đường dẫn (chỉ 2 luật này, không đụng lỗi cũ)
subprocess.run(["ruff", "check", "-q", "--select", "I,F401", "--fix", G, "tools", "tests"], cwd=R)
# README: chỉ thay đường dẫn/lệnh (đoạn văn về requirements*.txt để agent viết lại)
RD = R / "README.md"
t = RD.read_text()
for a, b in [("`scripts/masked_words.txt`", "`config/masked_words.txt`"), ("`scripts/vi-du-chuong-1.txt`", "`tests/fixtures/vi-du-chuong-1.txt`"),
             ("scripts/install_desktop.sh", "packaging/linux/install_desktop.sh"), ("scripts/uninstall_desktop.sh", "packaging/linux/uninstall_desktop.sh"),
             ("scripts/smoke_", "tests/smoke/smoke_"), ("`smoke_test.sh`", "`tests/smoke/smoke_test.sh`"), ("scripts/", "tools/"),
             (".venv/bin/python app.py", f".venv/bin/python -m {G}.desktop"), ("app.py --selftest", f"-m {G}.desktop --selftest"),
             ("python server.py", f"python -m {G}"), ("`server.py`", f"`{G}/server.py`"), ("`app_gtk.py`", f"`{G}/desktop/gtk.py`"),
             ("static/", "web/"), ("`engines/", f"`{G}/engines/"),
             ("`text_normalize.py`", f"`{G}/speech/text_normalize.py`"), ("`lexicon.py`", f"`{G}/speech/lexicon.py`"),
             ("`html_import.py`", f"`{G}/books/html_import.py`"), ("`narrate.py`", f"`{G}/books/narrate.py`"),
             ("`cast.py`", f"`{G}/books/cast.py`"), ("`voice_age.py`", f"`{G}/books/voice_age.py`"), ("`settings.py`", f"`{G}/settings.py`")]:
    t = t.replace(a, b)
RD.write_text(t)
gi = R / ".gitignore"
gi.write_text(gi.read_text().rstrip("\n") + "\n.ruff_cache/\n*.egg-info/\n")
subprocess.run(["git", "add", "-A"], check=True, cwd=R)
print("done")
