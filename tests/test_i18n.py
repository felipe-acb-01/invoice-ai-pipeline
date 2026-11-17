"""The demo in English and Spanish: every sentence on screen has its Spanish, and the choice sticks."""

import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_pipeline import i18n, web
from invoice_pipeline.demo import Demo
from invoice_pipeline.pipeline import NOT_AN_INVOICE, UNSUPPORTED
from invoice_pipeline.validate import FLAGS
from invoice_pipeline.web import create_app

SRC = Path(web.__file__).parent


def template_sentences() -> set[str]:
    """Every literal handed to _() in the templates."""
    pattern = re.compile(r"""_\(\s*(?:"([^"]+)"|'([^']+)')""")
    return {a or b for path in (SRC / "templates").glob("*.html") for a, b in pattern.findall(path.read_text())}


def code_sentences() -> set[str]:
    """Every literal handed to t() / i18n.tr() / DemoLimit() in the Python code."""
    found = set()
    for name in ("web.py", "demo.py"):
        for node in ast.walk(ast.parse((SRC / name).read_text())):
            if isinstance(node, ast.Call) and node.args:
                fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if fn in ("t", "tr", "DemoLimit"):
                    for arg in ast.walk(node.args[0]):
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            found.add(arg.value)
    return found


def test_every_sentence_on_screen_has_its_spanish():
    sentences = (template_sentences() | code_sentences() | set(FLAGS.values()) | set(web.TAB_LABELS.values())
                 | set(web.NOTICES.values()) | {NOT_AN_INVOICE, UNSUPPORTED, "same number", "same date and total", "Demo visitor"})
    assert len(sentences) > 80
    assert sorted(s for s in sentences if s not in i18n.ES) == []


def test_spanish_keeps_the_same_placeholders():
    for en, es in i18n.ES.items():
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", es)), en


@pytest.fixture
def client(tmp_path):
    demo = Demo(tmp_path / "demo", sandbox_limit=2, daily_limit=3, extractor=lambda p: None)
    return TestClient(create_app(approver="Demo visitor", demo=demo))


def test_english_by_default_spanish_on_request_and_remembered(client):
    assert '<html lang="en">' in client.get("/invoices").text
    es = client.get("/invoices?lang=es")
    assert '<html lang="es">' in es.text and "Por aprobar" in es.text and "Pruébala con tu propia factura" in es.text
    again = client.get("/invoices?status=error")
    assert "Apartadas" in again.text and "Set aside" not in again.text
    assert 'hreflang="en"' in again.text and "lang=en" in again.text
    assert "/es/facturas/" in again.text  # «Cómo funciona» goes to the Spanish case study
    assert '<html lang="en">' in client.get("/invoices?lang=en").text


def test_every_screen_in_spanish_leaves_no_english_behind(client):
    client.get("/invoices?lang=es")
    ids = [int(i) for i in re.findall(r'href="/invoices/(\d+)"', client.get("/invoices").text)]
    ids += [int(i) for i in re.findall(r'href="/invoices/(\d+)"', client.get("/invoices?status=error").text)]
    assert len(ids) == 10
    english = ["To approve", "Review before approving", "All checks passed", "Approve<", "Vendor tax ID", "too much",
               "too little", "the invoice says", "Due ", "On receipt", "uploads left", "Reading cost", "Not an invoice",
               "Open original", "Compare with", "Note (optional"]
    pages = [client.get(f"/invoices/{i}").text for i in ids] + [client.get(f"/invoices?status={s}").text
                                                                for s in ("pending", "approved", "rejected", "error")]
    for page in pages:
        body = page.split("<main>")[1]
        assert [w for w in english if w in body] == []
    assert any("de más" in p or "de menos" in p for p in pages)  # the alerts, with their numbers, in Spanish
    assert any(re.search(r"\d+ (ene|feb|mar|abr|may|jun|jul|ago|sept|oct|nov|dic) 2026", p) for p in pages)


def test_upload_errors_in_spanish(client):
    client.get("/invoices?lang=es")
    page = client.post("/invoices", files={"document": ("x.txt", b"hello", "text/plain")})
    assert page.status_code == 400 and "Sube un PDF, JPG o PNG." in page.text


def test_a_bad_language_is_ignored(client):
    page = client.get("/invoices?lang=fr")
    assert '<html lang="en">' in page.text and "lang=fr" not in page.headers.get("set-cookie", "")
