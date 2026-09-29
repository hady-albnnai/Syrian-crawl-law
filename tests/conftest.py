"""حماية عامة: لا اختبار يصل إلى الشبكة الحقيقية عبر قناة ويكيبيديا."""
import pytest


@pytest.fixture(autouse=True)
def _no_live_wikipedia(monkeypatch):
    try:
        import autopilot
    except Exception:
        return

    def _blocked(params):
        raise RuntimeError("الشبكة الحية ممنوعة في الاختبارات (ويكيبيديا)")
    monkeypatch.setattr(autopilot, "_wiki_get", _blocked)
