# -*- coding: utf-8 -*-
"""اختبارات وحدة تنزيل درايف (ف٥). بلا شبكة — كل مسارات الطلب مُحقَنة."""
import drive_source as drv


def test_extract_file_id_from_all_share_shapes():
    fid = "1IZbCdOc9jRcFMZX4EGTQ_R0ElpnMsNg8"
    assert drv.extract_file_id(fid) == fid
    assert drv.extract_file_id(f"https://drive.google.com/file/d/{fid}/view?usp=sharing") == fid
    assert drv.extract_file_id(f"https://drive.google.com/open?id={fid}") == fid
    assert drv.extract_file_id(f"https://drive.google.com/uc?id={fid}&export=download") == fid
    assert drv.extract_file_id("https://example.com/not-drive") is None
    assert drv.extract_file_id("") is None


def test_sniff_kind_by_magic():
    assert drv.sniff_kind(b"%PDF-1.4 rest") == "pdf"
    assert drv.sniff_kind(b"PK\x03\x04zip") == "zip"
    assert drv.sniff_kind(b"Rar!\x1a\x07\x00rest") == "rar"
    assert drv.sniff_kind(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1ole") == "doc"
    assert drv.sniff_kind(b"<html><body>gate</body></html>") == "html"
    assert drv.sniff_kind(b"\x00\x01\x02binary") == "unknown"


class _Resp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status
        self.cookies = {}


class _Session:
    """جلسة مزيفة: أول طلب بوابة تأكيد، الثاني (بمعامل الحقول) يعيد الملف."""
    def __init__(self, gated: bool, payload: bytes = b"%PDF-1.4 fake"):
        self.gated = gated
        self.payload = payload
        self.calls = []
        self.headers = {}

    def get(self, url, timeout=300, params=None, **kw):
        self.calls.append((url, params))
        if self.gated and params is None:
            gate = (b'<html><form action="https://drive.usercontent.google.com/download">'
                    b'<input type="hidden" name="id" value="X"/>'
                    b'<input type="hidden" name="export" value="download"/>'
                    b'<input type="hidden" name="confirm" value="tok"/></form></html>')
            return _Resp(gate)
        return _Resp(self.payload)


def test_download_direct(monkeypatch):
    fake = _Session(gated=False)
    monkeypatch.setattr(drv.requests, "Session", lambda: fake)
    assert drv.download_drive("1IZbCdOc9jRcFMZX4EGTQ_R0ElpnMsNg8") == b"%PDF-1.4 fake"
    assert len(fake.calls) == 1


def test_download_resolves_confirm_gate(monkeypatch):
    fake = _Session(gated=True)
    monkeypatch.setattr(drv.requests, "Session", lambda: fake)
    out = drv.download_drive("https://drive.google.com/file/d/ABCDEF12345/view")
    assert out == b"%PDF-1.4 fake"
    assert len(fake.calls) == 2                     # البوابة ثم إعادة الطلب بالحقول
    assert fake.calls[1][1].get("confirm") == "tok"


def test_download_bad_link_returns_none(monkeypatch):
    assert drv.download_drive("https://example.com/nope") is None


def test_cli_precedents_drive_registered():
    import cli
    p = cli.build_parser()
    args = p.parse_args(["precedents-drive", "someid1234567890", "--dry"])
    assert args.fn is cli.cmd_precedents_drive
    assert args.links == ["someid1234567890"] and args.dry
