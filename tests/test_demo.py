"""The public demo: private sandboxes, $0 to open, and limits on what a visitor can spend."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from invoice_pipeline.demo import Demo
from invoice_pipeline.extract import Extraction
from invoice_pipeline.schema import Invoice, LineItem
from invoice_pipeline.web import create_app

PDF = open("samples/003.pdf", "rb").read()  # not one of the demo samples


def fake_invoice(total=100.0):
    return Invoice(invoice_number="X-1", vendor_name="Uploaded Vendor", vendor_tax_id=None, customer_name="Me",
                   issue_date="2026-11-01", due_date=None, currency="USD",
                   line_items=[LineItem(description="Work", quantity=1, unit_price=total, amount=total)],
                   subtotal=total, tax=0, total=total)


@pytest.fixture
def demo(tmp_path):
    calls = []

    def reader(path):
        calls.append(path.name)
        return Extraction(fake_invoice(), "claude-haiku-5-5", 1.0, 2000, 300)
    d = Demo(tmp_path / "demo", sandbox_limit=2, daily_limit=3, extractor=reader)
    d.calls = calls
    return d


def visitor(demo):
    return TestClient(create_app(approver="Demo visitor", demo=demo))


def jpg(color=(200, 10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), color).save(buf, "JPEG")
    return buf.getvalue()


def test_opening_the_demo_shows_samples_and_costs_nothing(demo):
    page = visitor(demo).get("/invoices")
    assert page.status_code == 200 and "Live demo." in page.text and "Try it with your own invoice" in page.text
    assert demo.calls == []  # samples come with Haiku's recorded answers
    assert "need a closer look" in page.text


def test_each_visitor_has_a_private_sandbox(demo):
    ana, ben = visitor(demo), visitor(demo)
    ana.get("/invoices"), ben.get("/invoices")
    first = demo.store(ana.cookies["demo_sandbox"]).list("pending")[0]
    ana.post(f"/invoices/{first.id}/approve")
    assert demo.store(ana.cookies["demo_sandbox"]).get(first.id).status == "approved"
    assert demo.store(ben.cookies["demo_sandbox"]).get(first.id).status == "pending"


def test_uploading_a_sample_again_just_opens_it(demo):
    c = visitor(demo)
    c.get("/invoices")
    sample = open("demo_seed/01-std-001.pdf", "rb").read()
    r = c.post("/invoices", files={"document": ("again.pdf", sample, "application/pdf")}, follow_redirects=False)
    assert r.headers["location"] == "/invoices/1" and demo.calls == []


def test_upload_is_read_and_opens_its_page(demo):
    c = visitor(demo)
    c.get("/invoices")
    r = c.post("/invoices", files={"document": ("my invoice.pdf", PDF, "application/pdf")}, follow_redirects=False)
    assert r.status_code == 303
    page = c.get(r.headers["location"])
    assert "Uploaded Vendor" in page.text and demo.calls == ["my_invoice.pdf"]


def test_same_file_twice_does_not_spend_an_upload(demo):
    c = visitor(demo)
    c.get("/invoices")
    a = c.post("/invoices", files={"document": ("a.jpg", jpg(), "image/jpeg")}, follow_redirects=False)
    b = c.post("/invoices", files={"document": ("copy.jpg", jpg(), "image/jpeg")}, follow_redirects=False)
    assert a.headers["location"] == b.headers["location"] and len(demo.calls) == 1
    assert demo.remaining(c.cookies["demo_sandbox"]) == 1


def test_limits_per_visitor_and_per_day(demo):
    ana, ben = visitor(demo), visitor(demo)
    ana.get("/invoices"), ben.get("/invoices")
    for i in range(2):
        assert ana.post("/invoices", files={"document": (f"{i}.jpg", jpg((40 + 100 * i, 0, 0)), "image/jpeg")}).status_code == 200
    blocked = ana.post("/invoices", files={"document": ("2.jpg", jpg((0, 200, 0)), "image/jpeg")})
    assert blocked.status_code == 400 and "uploads per visitor per day" in blocked.text
    ben.post("/invoices", files={"document": ("b.jpg", jpg((0, 0, 200)), "image/jpeg")})
    day = ben.post("/invoices", files={"document": ("c.jpg", jpg((200, 200, 0)), "image/jpeg")})
    assert day.status_code == 400 and "upload limit" in day.text
    assert len(demo.calls) == 3


@pytest.mark.parametrize("name, data, message", [
    ("notes.txt", b"hello", "Upload a PDF, JPG or PNG."),
    ("empty.pdf", b"", "The file is empty."),
    ("big.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024), "larger than 5 MB"),
    ("broken.pdf", b"%PDF-1.4 garbage", "could not be opened"),
])
def test_bad_files_are_refused_before_spending(demo, name, data, message):
    c = visitor(demo)
    c.get("/invoices")
    r = c.post("/invoices", files={"document": (name, data, "application/octet-stream")})
    assert r.status_code == 400 and message in r.text and demo.calls == []
    assert demo.remaining(c.cookies["demo_sandbox"]) == 2


def test_start_over_gives_a_fresh_sandbox(demo):
    c = visitor(demo)
    c.get("/invoices")
    old = c.cookies["demo_sandbox"]
    first = demo.store(old).list("pending")[0]
    c.post(f"/invoices/{first.id}/approve")
    r = c.post("/demo/restart", follow_redirects=True)
    assert "Started a fresh demo" in r.text and c.cookies["demo_sandbox"] != old
    assert demo.store(c.cookies["demo_sandbox"]).get(first.id).status == "pending"


def test_a_forged_cookie_cannot_reach_outside_the_sandboxes(demo):
    r = visitor(demo).get("/invoices", headers={"cookie": "demo_sandbox=../../etc"})
    assert r.status_code == 200
    issued = r.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    assert issued != "../../etc" and Demo.valid_id(issued)
    assert not (demo.root / "etc").exists()


def test_health():
    assert TestClient(create_app(demo=Demo.__new__(Demo))).get("/health").json() == {"ok": True}


def test_many_pages_at_once_do_not_kill_the_server():
    """PDFium is not thread-safe: the browser asking for every page of a document at once used to crash the process."""
    import subprocess
    import sys

    script = (
        "from concurrent.futures import ThreadPoolExecutor\n"
        "from pathlib import Path\n"
        "from invoice_pipeline.pdf import page_count, page_png\n"
        "docs = sorted(Path('demo_seed').glob('*.pdf'))\n"
        "jobs = [d for d in docs for _ in range(4)]\n"
        "with ThreadPoolExecutor(16) as pool:\n"
        "    pngs = list(pool.map(lambda d: page_png(d, 1), jobs)) + list(pool.map(page_count, jobs))\n"
        "assert all(pngs)\n"
    )
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=120)
    assert run.returncode == 0, run.stderr.decode()[-500:]


def test_a_missing_page_is_a_page_in_the_visitors_language(demo):
    c = visitor(demo)
    c.get("/invoices?lang=es")
    for url in ("/invoices/999", "/invoices?status=nope", "/nope"):
        r = c.get(url)
        assert r.status_code == 404 and "text/html" in r.headers["content-type"]
        assert "Esta página no existe" in r.text and 'href="/invoices"' in r.text


def test_the_link_previews_well_and_monitors_can_ask_with_head(demo):
    c = visitor(demo)
    page = c.get("/invoices?lang=es").text
    assert '<meta property="og:image" content="http://testserver/og-es.png">' in page
    assert 'name="description"' in page and 'rel="icon"' in page
    assert c.get("/og-es.png").headers["content-type"] == "image/png" and c.get("/og-fr.png").status_code == 404
    assert c.get("/favicon.ico").headers["content-type"].startswith("image/svg+xml")
    assert "Disallow: /documents" in c.get("/robots.txt").text and "Disallow: /invoices" not in c.get("/robots.txt").text
    head = c.head("/invoices")
    assert head.status_code == 200 and head.content == b"" and head.headers["x-content-type-options"] == "nosniff"
    assert c.head("/health").status_code == 200


def test_an_api_error_reads_as_a_sentence_with_the_code_underneath(tmp_path):
    from invoice_pipeline.extract import Extraction
    d = Demo(tmp_path / "demo", extractor=lambda p: Extraction(None, "claude-haiku-5-5", 0.4, 0, 0, "529: Overloaded"))
    c = visitor(d)
    c.get("/invoices?lang=es")
    r = c.post("/invoices", files={"document": ("x.jpg", jpg(), "image/jpeg")}, follow_redirects=False)
    page = c.get(r.headers["location"]).text
    assert "El servicio de lectura devolvió un error" in page and "529: Overloaded" in page
    assert "El servicio de lectura devolvió un error. Ábrela" in c.get("/invoices?status=error").text
