"""
pipeline/build.py — .NET build and run operations.

Uses an isolated `_build` subdirectory so generated code output
(files, folders) doesn't pollute the project root.
"""

import os
import signal
import shutil
import subprocess
import textwrap
from pathlib import Path

from config import AppConfig
from pipeline.models import BuildResult

_BUILD_DIR_NAME = "_build"


def _run_with_kill(cmd, cwd, timeout):
    """Run a subprocess with guaranteed kill on timeout.

    Uses Popen + communicate so we can explicitly kill the entire
    process tree if the timeout fires, preventing zombie dotnet processes.
    """
    kwargs = dict(
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # On Unix, start_new_session lets us kill the whole process group
    if os.name != "nt":
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        log = (stdout or "") + "\n" + (stderr or "")
        return BuildResult(ok=(proc.returncode == 0), log=log)
    except subprocess.TimeoutExpired:
        # Kill the entire process group (dotnet spawns child processes)
        try:
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            pass
        proc.wait(timeout=5)
        return BuildResult(ok=False, log=f"Timeout after {timeout}s — process killed")
    except Exception as e:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except OSError:
            pass
        return BuildResult(ok=False, log=f"Process error: {e}")


class DotnetBuilder:
    """Handles writing .csproj/Program.cs and running dotnet build/run."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.workspace = Path(config.workspace_path) / _BUILD_DIR_NAME
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.csproj_path = self.workspace / "AsposePdfApi.csproj"
        self.program_cs_path = self.workspace / "Program.cs"

    def write_csproj(self) -> str:
        """Write .csproj with configured TFM and NuGet package."""
        tfm = self.config.build.tfm
        pkg = self.config.build.nuget_package
        ver = self.config.build.nuget_version

        content = textwrap.dedent(f"""\
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup>
                <OutputType>Exe</OutputType>
                <TargetFramework>{tfm}</TargetFramework>
                <ImplicitUsings>disable</ImplicitUsings>
                <Nullable>disable</Nullable>
                <LangVersion>latest</LangVersion>
              </PropertyGroup>
              <ItemGroup>
                <PackageReference Include="{pkg}" Version="{ver}" />
              </ItemGroup>
            </Project>""")

        self.csproj_path.write_text(content, encoding="utf-8")
        return str(self.csproj_path)

    def write_program_cs(self, code: str) -> str:
        """Write Program.cs with guaranteed trailing newline."""
        normalized = code if code.endswith("\n") else code + "\n"
        self.program_cs_path.write_text(normalized, encoding="utf-8")
        return str(self.program_cs_path)

    def build(self) -> BuildResult:
        """Run dotnet build (compile only)."""
        return _run_with_kill(
            ["dotnet", "build", "-v", self.config.dotnet.build_verbosity],
            cwd=self.workspace,
            timeout=self.config.dotnet.build_timeout,
        )

    def run(self) -> BuildResult:
        """Run compiled code (no rebuild)."""
        return _run_with_kill(
            ["dotnet", "run", "--no-build"],
            cwd=self.workspace,
            timeout=self.config.dotnet.run_timeout,
        )

    def clean_output_artifacts(self):
        """Remove runtime-generated files/dirs (PDFs, images, etc.) but keep .csproj, Program.cs, bin, obj."""
        keep = {"AsposePdfApi.csproj", "Program.cs", "bin", "obj"}
        for item in self.workspace.iterdir():
            if item.name in keep:
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                pass

    def build_and_run(self) -> tuple:
        """Build then run. Returns (success: bool, combined_output: str)."""
        self.clean_output_artifacts()
        build_result = self.build()
        if not build_result.ok:
            return False, build_result.log

        run_result = self.run()
        combined = build_result.log + "\n--- RUNTIME OUTPUT ---\n" + run_result.log
        return run_result.ok, combined
