"""Tests for pipeline/build.py — csproj/Program.cs file generation and artifact cleanup."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import AppConfig
from pipeline.build import DotnetBuilder


@pytest.fixture
def builder(tmp_path):
    cfg = AppConfig()
    cfg.workspace_path = str(tmp_path)
    return DotnetBuilder(cfg)


# ── write_csproj ───────────────────────────────────────────────────────────────

def test_csproj_contains_tfm(builder):
    builder._build_id = "testbuild"
    builder.write_csproj()
    content = builder.csproj_path.read_text()
    assert builder.config.build.tfm in content


def test_csproj_contains_nuget_version(builder):
    builder._build_id = "testbuild"
    builder.write_csproj()
    content = builder.csproj_path.read_text()
    assert builder.config.build.nuget_version in content


def test_csproj_contains_unique_assembly_name(builder):
    builder._build_id = "abc12345"
    builder.write_csproj()
    content = builder.csproj_path.read_text()
    assert "AsposePdfApi_abc12345" in content


def test_csproj_has_implicit_usings(builder):
    builder._build_id = "testbuild"
    builder.write_csproj()
    content = builder.csproj_path.read_text()
    assert "ImplicitUsings" in content
    assert "enable" in content


def test_csproj_different_build_ids_produce_different_assembly_names(builder):
    builder._build_id = "aaa"
    builder.write_csproj()
    content_a = builder.csproj_path.read_text()

    builder._build_id = "bbb"
    builder.write_csproj()
    content_b = builder.csproj_path.read_text()

    assert content_a != content_b


# ── write_program_cs ───────────────────────────────────────────────────────────

def test_program_cs_written_correctly(builder):
    code = 'using Aspose.Pdf;\nvar doc = new Document();\ndoc.Save("out.pdf");'
    builder.write_program_cs(code)
    assert builder.program_cs_path.read_text() == code + "\n"


def test_program_cs_trailing_newline_not_doubled(builder):
    code = "var x = 1;\n"
    builder.write_program_cs(code)
    content = builder.program_cs_path.read_text()
    assert content == code
    assert not content.endswith("\n\n")


def test_program_cs_empty_string(builder):
    builder.write_program_cs("")
    assert builder.program_cs_path.read_text() == "\n"


# ── clean_output_artifacts ─────────────────────────────────────────────────────

def test_clean_preserves_csproj_and_program_cs(builder):
    builder._build_id = "testbuild"
    builder.write_csproj()
    builder.write_program_cs("var x = 1;")

    builder.clean_output_artifacts()

    assert builder.csproj_path.exists()
    assert builder.program_cs_path.exists()


def test_clean_removes_generated_pdf(builder):
    pdf = builder.workspace / "output.pdf"
    pdf.write_bytes(b"%PDF")

    builder.clean_output_artifacts()

    assert not pdf.exists()


def test_clean_removes_generated_subdirectory(builder):
    subdir = builder.workspace / "generated_files"
    subdir.mkdir()
    (subdir / "file.txt").write_text("data")

    builder.clean_output_artifacts()

    assert not subdir.exists()


def test_clean_preserves_bin_and_obj(builder):
    bin_dir = builder.workspace / "bin"
    obj_dir = builder.workspace / "obj"
    bin_dir.mkdir()
    obj_dir.mkdir()

    builder.clean_output_artifacts()

    assert bin_dir.exists()
    assert obj_dir.exists()
