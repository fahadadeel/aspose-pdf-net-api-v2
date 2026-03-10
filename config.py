"""
config.py — All non-secret configuration for the application.

Secrets (API keys, tokens) come from .env via os.getenv().
Everything else is defined here with typed defaults.
Override any value via environment variable.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment-specific .env file:
#   APP_ENV=production  →  .env.production
#   APP_ENV=staging     →  .env.staging
#   (unset / default)   →  .env
_env_name = os.getenv("APP_ENV", "").strip().lower()
_base_dir = Path(__file__).resolve().parent
if _env_name:
    _env_file = _base_dir / f".env.{_env_name}"
    if _env_file.exists():
        load_dotenv(_env_file, override=True)
    else:
        print(f"Warning: APP_ENV={_env_name} but {_env_file} not found, falling back to .env")
        load_dotenv(_base_dir / ".env")
else:
    load_dotenv(_base_dir / ".env")

# Suppress HuggingFace tokenizer fork warning (harmless in our subprocess usage)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


@dataclass
class BuildConfig:
    """Target framework and NuGet package for .NET builds."""
    tfm: str = "net10.0"
    nuget_package: str = "Aspose.PDF"
    nuget_version: str = "26.2.0"


@dataclass
class DotnetConfig:
    """Timeouts and verbosity for dotnet CLI."""
    build_timeout: int = 30
    run_timeout: int = 30
    build_verbosity: str = "minimal"


@dataclass
class PipelineConfig:
    """Retry counts and feature flags for the 5-stage pipeline."""
    llm_fix_attempts: int = 3
    regen_attempts: int = 3
    retrieve_limit: int = 20
    retrieve_max_chars: int = 12000
    use_retrieve_on_llm_fail: bool = True
    decompose_on_llm_fail: bool = False
    final_llm_after_regen_fail: bool = True
    retry_mode: str = "full"
    learn_rules_from_failures: bool = False


@dataclass
class MCPConfig:
    """MCP server endpoints."""
    generate_url: str = "http://172.20.1.175:7050/mcp/generate"
    retrieve_url: str = "http://172.20.1.175:7050/mcp/retrieve"
    product: str = "pdf"
    platform: str = "net"
    retrieval_mode: str = "embedding"
    retrieval_limit: int = 15
    timeout: int = 30
    exclude_namespaces: list = field(default_factory=lambda: ["Aspose.Pdf.Plugins", "Aspose.Pdf.Facades"])


@dataclass
class LLMConfig:
    """LLM client config. Secrets from .env."""
    api_base: str = "https://llm.professionalize.com/v1"
    api_key: str = "sk-V9KD0Qxe5R1psEVZNeKxCA"
    model: str = "gpt-oss"


@dataclass
class RerankerConfig:
    """KB search and LLM reranking parameters."""
    candidate_count: int = 100
    top_k: int = 10
    attempt1_top_k: int = 20
    timeout: int = 20


@dataclass
class AnthropicConfig:
    """Anthropic Claude API configuration for post-pipeline rule learning."""
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"


@dataclass
class GitConfig:
    """Git repo and PR config. Secrets from .env."""
    repo_url: str = "https://github.com/aspose-pdf/agentic-net-examples.git"
    repo_path: str = "/Users/fahadadeelqazi/Projects/Aspose/agentic-net-examples-v2"
    repo_branch: str = "main"
    repo_push: bool = False
    repo_token: str = ""
    repo_user: str = ""
    default_category: str = "uncategorized"
    default_product: str = "aspose.pdf"
    update_agents_md: bool = True
    pr_split_threshold: int = 0  # 0 = single PR; >0 = split by category when total files exceed this


@dataclass
class AppConfig:
    """Top-level config aggregating all sub-configs."""
    build: BuildConfig = field(default_factory=BuildConfig)
    dotnet: DotnetConfig = field(default_factory=DotnetConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    reranker: RerankerConfig = field(default_factory=RerankerConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    git: GitConfig = field(default_factory=GitConfig)

    workspace_path: str = "."
    rules_examples_path: str = "./resources/kb_new.json"
    fix_history_path: str = "./fix_history.json"
    error_catalog_path: str = "./resources/error_catalog.json"
    error_fixes_path: str = "./resources/error_fixes.json"
    auto_fixes_path: str = "./resources/auto_fixes.json"

    # External API proxies (for UI task generator)
    categories_api_url: str = "http://172.20.1.175:7001/api/categories"
    tasks_api_url: str = "http://172.20.1.175:7001/api/tasks"


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def load_config() -> AppConfig:
    """Load config: dataclass defaults overridden by environment variables."""
    cfg = AppConfig()

    # Build
    cfg.build.tfm = _env("BUILD_TFM", cfg.build.tfm)
    cfg.build.nuget_package = _env("NUGET_PACKAGE", cfg.build.nuget_package)
    cfg.build.nuget_version = _env("NUGET_VERSION", cfg.build.nuget_version)

    # Dotnet
    cfg.dotnet.build_timeout = _env_int("BUILD_TIMEOUT", cfg.dotnet.build_timeout)
    cfg.dotnet.run_timeout = _env_int("RUN_TIMEOUT", cfg.dotnet.run_timeout)
    cfg.dotnet.build_verbosity = _env("BUILD_VERBOSITY", cfg.dotnet.build_verbosity)

    # Pipeline
    cfg.pipeline.llm_fix_attempts = _env_int("LLM_FIX_ATTEMPTS", cfg.pipeline.llm_fix_attempts)
    cfg.pipeline.regen_attempts = _env_int("REGEN_ATTEMPTS", cfg.pipeline.regen_attempts)
    cfg.pipeline.retrieve_limit = _env_int("RETRIEVE_LIMIT", cfg.pipeline.retrieve_limit)
    cfg.pipeline.use_retrieve_on_llm_fail = _env_bool("USE_RETRIEVE_ON_LLM_FAIL", cfg.pipeline.use_retrieve_on_llm_fail)
    cfg.pipeline.decompose_on_llm_fail = _env_bool("DECOMPOSE_ON_LLM_FAIL", cfg.pipeline.decompose_on_llm_fail)
    cfg.pipeline.final_llm_after_regen_fail = _env_bool("FINAL_LLM_AFTER_REGEN_FAIL", cfg.pipeline.final_llm_after_regen_fail)
    cfg.pipeline.retry_mode = _env("RETRY_MODE", cfg.pipeline.retry_mode)
    cfg.pipeline.learn_rules_from_failures = _env_bool("LEARN_RULES_FROM_FAILURES", cfg.pipeline.learn_rules_from_failures)

    # MCP
    cfg.mcp.generate_url = _env("API_URL", cfg.mcp.generate_url)
    cfg.mcp.retrieve_url = _env("MCP_RETRIEVE_URL", cfg.mcp.retrieve_url)
    cfg.mcp.product = _env("MCP_PRODUCT", cfg.mcp.product)
    cfg.mcp.platform = _env("MCP_PLATFORM", cfg.mcp.platform)
    cfg.mcp.retrieval_mode = _env("MCP_RETRIEVAL_MODE", cfg.mcp.retrieval_mode)
    cfg.mcp.retrieval_limit = _env_int("MCP_RETRIEVAL_LIMIT", cfg.mcp.retrieval_limit)
    cfg.mcp.timeout = _env_int("MCP_TIMEOUT", cfg.mcp.timeout)

    # LLM (secrets from .env)
    cfg.llm.api_base = _env("LITELLM_API_BASE", cfg.llm.api_base)
    cfg.llm.api_key = _env("LITELLM_API_KEY", "")
    raw_model = _env("LITELLM_MODEL", cfg.llm.model)
    cfg.llm.model = raw_model.split("/")[-1] if "/" in raw_model else raw_model

    # Reranker
    cfg.reranker.candidate_count = _env_int("RERANK_CANDIDATE_COUNT", cfg.reranker.candidate_count)
    cfg.reranker.top_k = _env_int("RERANK_TOP_K", cfg.reranker.top_k)
    cfg.reranker.attempt1_top_k = _env_int("RERANK_ATTEMPT1_TOP_K", cfg.reranker.attempt1_top_k)
    cfg.reranker.timeout = _env_int("RERANK_TIMEOUT", cfg.reranker.timeout)

    # Anthropic
    cfg.anthropic.api_key = _env("ANTHROPIC_API_KEY", cfg.anthropic.api_key)
    cfg.anthropic.model = _env("ANTHROPIC_MODEL", cfg.anthropic.model)

    # Git (secrets from .env)
    cfg.git.repo_url = _env("REPO_URL", cfg.git.repo_url)
    cfg.git.repo_path = _env("REPO_PATH", cfg.git.repo_path)
    cfg.git.repo_branch = _env("REPO_BRANCH", cfg.git.repo_branch)
    cfg.git.repo_push = _env_bool("REPO_PUSH", cfg.git.repo_push)
    cfg.git.repo_token = _env("REPO_TOKEN", "")
    cfg.git.repo_user = _env("REPO_USER", "")
    cfg.git.default_category = _env("DEFAULT_CATEGORY", cfg.git.default_category)
    cfg.git.default_product = _env("DEFAULT_PRODUCT", cfg.git.default_product)
    cfg.git.pr_split_threshold = _env_int("PR_SPLIT_THRESHOLD", cfg.git.pr_split_threshold)

    # App-level
    cfg.workspace_path = _env("WORKSPACE_PATH", cfg.workspace_path)
    cfg.rules_examples_path = _env("RULES_EXAMPLES_PATH", cfg.rules_examples_path)
    cfg.fix_history_path = _env("FIX_HISTORY_PATH", cfg.fix_history_path)
    cfg.error_catalog_path = _env("ERROR_CATALOG_PATH", cfg.error_catalog_path)
    cfg.error_fixes_path = _env("ERROR_FIXES_PATH", cfg.error_fixes_path)
    cfg.auto_fixes_path = _env("AUTO_FIXES_PATH", cfg.auto_fixes_path)
    cfg.categories_api_url = _env("CATEGORIES_API_URL", cfg.categories_api_url)
    cfg.tasks_api_url = _env("TASKS_API_URL", cfg.tasks_api_url)

    return cfg
