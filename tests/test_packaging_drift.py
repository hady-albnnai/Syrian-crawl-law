# -*- coding: utf-8 -*-
"""حارس انجراف التغليف — علة مقاسة: `verify_package`/`package_manifest` أُضيفتا
إلى `py-modules` (دفعة 2) ونُسيتا من `hiddenimports` في مواصفة PyInstaller،
فكانت البوابة تنهار في **النسخة المجمَّدة فقط** والشاشة تبتلع الاستثناء وتعرض
نصّه — أي عطل «ناجح» بصرياً. هذا الملف يمنع الفئة كلها، بالقياس لا بالعين.

القاعدة: كل وحدة جذر يستوردها `app/**` أو `cli.py` أو `mizan_injector.py`
(ولو داخل دالة) يجب أن تظهر في القائمتين معاً.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT_RE = re.compile(r'^\s*(?:from|import)\s+([a-z_][a-z0-9_]*)\b', re.M)


def _root_modules():
    return {p.stem for p in ROOT.glob("*.py")
            if not p.stem.startswith(("test_", "conftest"))}


def _imported_by_app():
    seen = set()
    srcs = list((ROOT / "app").rglob("*.py")) + [ROOT / "cli.py",
                                                 ROOT / "mizan_injector.py",
                                                 ROOT / "autopilot.py"]
    for f in srcs:
        if not f.exists():
            continue
        for name in IMPORT_RE.findall(f.read_text(encoding="utf-8")):
            seen.add(name)
    return seen


def _pyproject_modules():
    import tomllib
    d = tomllib.load(open(ROOT / "pyproject.toml", "rb"))
    return set(d["tool"]["setuptools"]["py-modules"])


def _spec_hiddenimports():
    text = (ROOT / "packaging" / "mizan-harvester.spec").read_text(encoding="utf-8")
    block = text[text.index("hiddenimports = "):]
    return set(re.findall(r'"([a-z_][a-z0-9_]*)"', block))


def test_pyproject_lists_every_root_module():
    """`py-modules` تغطي ملفات الجذر كلها — لا وحدة تُنسى عند التثبيت."""
    missing = _root_modules() - _pyproject_modules()
    assert not missing, f"وحدات جذر خارج py-modules: {sorted(missing)}"


def test_lazy_app_imports_are_in_hiddenimports():
    """أي وحدة تستوردها الواجهة/CLI يجب أن تكون في hiddenimports."""
    hidden = _spec_hiddenimports()
    needed = (_imported_by_app() & _root_modules()) - {"cli"}
    missing = sorted(n for n in needed if n not in hidden)
    assert not missing, (
        f"مفقودة من hiddenimports في packaging/mizan-harvester.spec: {missing} — "
        "هذه الاستيرادات كسولة (داخل دوال)، فلا يراها PyInstaller: "
        "النسخة المجمَّدة ستنهار عند الفعل المعني لا عند الإقلاع")


def test_gate_and_injector_modules_are_shipped():
    """الوحدات الثلاث التي تُمسك العقد والبوابة والحقن — في القائمتين."""
    for mod in ("verify_package", "package_manifest", "mizan_injector",
                "exporter"):
        assert mod in _pyproject_modules(), mod
        assert mod in _spec_hiddenimports(), mod


def test_no_duplicate_entries_in_pyproject():
    import tomllib
    pm = tomllib.load(open(ROOT / "pyproject.toml", "rb"))["tool"]["setuptools"]["py-modules"]
    assert len(pm) == len(set(pm)), [x for x in pm if pm.count(x) > 1]


def test_pyproject_names_exist_as_files():
    for mod in _pyproject_modules():
        assert (ROOT / f"{mod}.py").exists(), f"py-module وهمي: {mod}"
