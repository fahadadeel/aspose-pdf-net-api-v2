"""
pipeline/build.py — .NET build and run operations.
"""

import subprocess
import textwrap
from pathlib import Path

from config import AppConfig
from pipeline.models import BuildResult


class DotnetBuilder:
    """Handles writing .csproj/Program.cs and running dotnet build/run."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.workspace = Path(config.workspace_path)
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
        try:
            result = subprocess.run(
                ["dotnet", "build", "-v", self.config.dotnet.build_verbosity],
                cwd=self.workspace,
                capture_output=True, text=True,
                timeout=self.config.dotnet.build_timeout,
            )
            log = (result.stdout or "") + "\n" + (result.stderr or "")
            return BuildResult(ok=(result.returncode == 0), log=log)
        except subprocess.TimeoutExpired:
            return BuildResult(ok=False, log=f"Build timeout after {self.config.dotnet.build_timeout}s")
        except Exception as e:
            return BuildResult(ok=False, log=f"Build error: {e}")

    def run(self) -> BuildResult:
        """Run compiled code (no rebuild)."""
        try:
            result = subprocess.run(
                ["dotnet", "run", "--no-build"],
                cwd=self.workspace,
                capture_output=True, text=True,
                timeout=self.config.dotnet.run_timeout,
            )
            log = (result.stdout or "") + "\n" + (result.stderr or "")
            return BuildResult(ok=(result.returncode == 0), log=log)
        except subprocess.TimeoutExpired:
            return BuildResult(ok=False, log=f"Runtime timeout after {self.config.dotnet.run_timeout}s")
        except Exception as e:
            return BuildResult(ok=False, log=f"Runtime error: {e}")

    def build_and_run(self) -> tuple:
        """Build then run. Returns (success: bool, combined_output: str)."""
        build_result = self.build()
        if not build_result.ok:
            return False, build_result.log

        run_result = self.run()
        combined = build_result.log + "\n--- RUNTIME OUTPUT ---\n" + run_result.log
        return run_result.ok, combined
