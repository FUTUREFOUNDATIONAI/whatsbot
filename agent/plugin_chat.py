"""Agno-powered assistant used by the built-in Chat / plugin creator."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Iterable

from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAILike
from agno.tools.function import Function
from agno.tools.workspace import Workspace

from config.settings import LLM_API_BASE_URL

logger = logging.getLogger(__name__)

SYSTEM_HELP_KNOWLEDGE_PATH = Path(__file__).with_name("SYSTEM_HELP.md")
_REFERENCE_EXTENSIONS = {".md", ".py", ".js", ".css", ".html", ".yaml", ".yml", ".txt", ".toml"}
_REFERENCE_ROOTS = (
    "README.md", "CLAUDE.md", "AGENTS.md", "agent", "config", "db", "docs", "plugins",
    "server", "web", "assets/plugin_examples", "storages/plugins",
)
_BLOCKED_REFERENCE_PARTS = {".git", "venv", "logs", "__pycache__", "plugin_data"}
_SAFE_HELP_CONFIG_KEYS = {
    "model", "improvement_model", "audio_model", "image_model", "document_model",
    "auto_reply", "default_ai_enabled", "max_context_messages", "inactivity_timeout_min",
    "message_batch_delay", "response_delay_min", "response_delay_max", "split_messages",
    "split_message_delay", "audio_transcription_mode", "audio_transcription_target",
    "audio_transcription_chat_prefix", "image_transcription_enabled",
    "document_transcription_enabled", "transfer_alert_enabled", "transfer_alert_duration",
    "group_reply_mode", "low_balance_enabled", "low_balance_threshold", "max_executions",
    "ai_engine_enabled", "setup_completed", "gowa_auto_check_enabled", "gowa_latest_version",
    "gowa_last_check_at", "gowa_proxy_enabled", "gowa_proxy_mode", "gowa_proxy_scheme",
    "whatsbot_update_notifications_enabled", "whatsbot_skipped_version",
}

SYSTEM_HELP_PROMPT = """Você é a ajuda integrada do WhatsBot.
Responda em português brasileiro, com frases curtas e linguagem para uma pessoa sem conhecimento técnico.
Seu único escopo é explicar como usar e configurar o WhatsBot. Você pode ler o sistema, mas nunca o modifica.

A BASE OFICIAL DE AJUDA abaixo já está carregada nesta mensagem. Consulte-a primeiro e responda sem usar ferramentas quando ela trouxer a orientação necessária.
Use as ferramentas de consulta somente se a informação estiver ausente, incompleta ou parecer incompatível com a versão atual. Nesse caso, faça buscas objetivas nas referências do sistema, no código dos plugins instalados e na estrutura do banco. Nunca consulte nem exponha mensagens, contatos, chaves, senhas ou outros dados pessoais.
Se precisar investigar, conclua a resposta em linguagem simples e apresente apenas o caminho que a pessoa deve seguir. Não cite nomes de arquivos ou detalhes internos, salvo se ela pedir uma explicação técnica.

Você não cria, planeja, pesquisa nem altera plugins neste projeto. Se o usuário quiser criar ou modificar um plugin, explique em uma frase que ele deve clicar no botão + no topo da barra lateral esquerda do Chat, criar um projeto e descrever ali o que deseja. Não faça perguntas sobre o plugin e não use ferramentas para investigar esse pedido.

Nunca mencione endpoints, REST, JSON, IDs, banco de dados, classes ou detalhes de programação, salvo se o próprio usuário pedir uma explicação técnica.
"""


def load_system_help_knowledge(path: Path | None = None) -> str:
    """Read the canonical help base on every help-agent construction.

    Reading it at construction time keeps a long-running development server in
    sync with documentation edits and makes this file the single maintained
    source of end-user navigation guidance.
    """
    knowledge_path = path or SYSTEM_HELP_KNOWLEDGE_PATH
    try:
        content = knowledge_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("System help knowledge could not be loaded from %s: %s", knowledge_path, exc)
        return "Base oficial indisponível. Consulte as referências do sistema antes de responder."
    return content or "Base oficial vazia. Consulte as referências do sistema antes de responder."


def system_help_prompt(panel_base_url: str = "") -> str:
    """Return the help prompt with the canonical base and current address.

    The base URL comes from the current request, so a user accessing a local
    installation receives ``localhost:port`` links while a hosted installation
    receives its public domain. The Markdown base is loaded on each call so it
    remains the source of truth for end-user features and navigation.
    """
    base = (panel_base_url or "").rstrip("/")
    knowledge = load_system_help_knowledge().replace("{{base_url}}", base)
    return f"{SYSTEM_HELP_PROMPT.rstrip()}\n\n--- BASE OFICIAL DE AJUDA ---\n{knowledge}"

PLUGIN_PROMPT = """Você é o Criador de Plugins do WhatsBot. Converse em português brasileiro com uma pessoa que não sabe programar.

Antes de usar qualquer ferramenta ou escrever código, confirme que entendeu:
- o que o plugin deve resolver;
- como ele deve interagir com as conversas do WhatsApp;
- se precisa de uma tela no painel e o que a pessoa fará nela;
- quais informações precisam ser cadastradas ou guardadas;
- um exemplo simples do resultado esperado.

Se essas informações estiverem incompletas, faça no máximo três perguntas curtas por vez. Use palavras comuns e exemplos. Coloque cada pergunta em uma linha própria, numerada, com uma linha em branco entre elas; nunca junte duas perguntas no mesmo parágrafo. Não fale de endpoints, REST, JSON, IDs, tabelas, schemas, classes ou detalhes internos. Não use ferramentas enquanto estiver esclarecendo o pedido. Quando o pedido já estiver claro, diga em uma frase o que entendeu e comece o trabalho sem pedir uma confirmação adicional.

Referência pronta para evitar pesquisas repetidas:
- O projeto usa o formato nativo do WhatsBot, com plugin.yaml na raiz e código Python do próprio plugin.
- O manifesto define id estável, nome, versão, compatibilidade, dependências e, quando existirem, telas e migrations.
- Telas são arquivos do plugin integrados ao painel; dados persistentes ficam fora do código substituível.
- Atualizações mantêm o mesmo id, acrescentam migrations compatíveis e preservam configurações e dados.
- A validação integrada já confere manifesto, dependências, sintaxe, migrations e testes.

Ao implementar, consulte somente as referências exatas necessárias. Evite listar toda a árvore ou reler guias e exemplos já resumidos acima. Prefira uma busca objetiva e leituras direcionadas; comece a editar assim que encontrar o padrão relevante.

Regras de implementação:
- O plugin deve seguir o formato nativo do WhatsBot, usar SQLAlchemy e tabelas prefixadas com plugin_<id>_.
- Preserve o id do plugin e migrations já publicadas. Atualizações adicionam migrations numeradas; nunca reescrevem migrations aplicadas.
- Guarde uploads, imagens geradas e outros arquivos do usuário em plugins.context.plugin_data_dir('<id>'), fora da pasta substituível do código.
- Configuração do plugin vive no próprio plugin. Não altere o painel de configurações do core.
- Execute validações e testes aplicáveis. Ao encontrar erro, investigue e corrija autonomamente.
- Não diga que instalou ou atualizou. A instalação ocorre separadamente após validação e confirmação do usuário na interface.
- Evite dependências externas quando a biblioteca padrão ou dependências do host forem suficientes.

Use list_whatsbot_files, read_whatsbot_file e search_whatsbot para consultar o sistema. Use as ferramentas do Workspace para o projeto. As ações são exibidas ao usuário, portanto use nomes e comandos objetivos.
"""

DISCOVERY_PROMPT = """Você ajuda uma pessoa sem conhecimento técnico a explicar o plugin que deseja criar para o WhatsBot.
Ainda não programe e não mencione detalhes técnicos. Entenda o pedido e faça no máximo três perguntas curtas e específicas. Pergunte apenas o que ainda falta entre: objetivo, interação com as conversas do WhatsApp, necessidade de uma tela no painel, informações que serão guardadas e um exemplo do resultado esperado.
Comece reconhecendo o pedido em uma frase simples. Depois escreva uma frase curta explicando que precisa entender alguns detalhes.

Formatação obrigatória:
- Separe a introdução e as perguntas com uma linha em branco.
- Escreva cada pergunta em uma linha própria, numerada como 1., 2. e 3.
- Comece cada pergunta com um rótulo curto em negrito, por exemplo: **Funcionamento:**.
- Nunca coloque duas perguntas no mesmo parágrafo.
- Termine com uma frase curta dizendo que a pessoa pode responder do jeito dela.

Não use listas longas, entidades HTML nem explique como o sistema será implementado.
"""


def _safe_reference_path(root: Path, relative: str) -> Path:
    relative = (relative or "").replace("\\", "/").lstrip("/")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("caminho fora das referências do WhatsBot") from exc
    parts = set(candidate.relative_to(root.resolve()).parts)
    if parts & _BLOCKED_REFERENCE_PARTS:
        raise ValueError("essa pasta não faz parte das referências disponíveis")
    allowed = any(relative == item or relative.startswith(item + "/") for item in _REFERENCE_ROOTS)
    if not allowed:
        raise ValueError("referência fora das áreas permitidas")
    return candidate


def _is_allowed_reference(relative: Path) -> bool:
    value = relative.as_posix()
    return any(value == item or value.startswith(item + "/") for item in _REFERENCE_ROOTS)


def _inspect_system_state(section: str) -> str:
    """Return support diagnostics without exposing user content or secrets."""
    section = (section or "settings").strip().lower()
    if section == "settings":
        from config.settings import DEFAULT_CONFIG
        from db.repositories import config_repo

        stored = config_repo.get_all()
        settings = {
            key: stored.get(key, DEFAULT_CONFIG.get(key))
            for key in sorted(_SAFE_HELP_CONFIG_KEYS)
            if key in stored or key in DEFAULT_CONFIG
        }
        settings["api_key_configured"] = bool(stored.get("openrouter_api_key"))
        settings["panel_password_configured"] = bool(stored.get("web_password_hash"))
        return json.dumps(settings, ensure_ascii=False, default=str)

    if section == "plugins":
        from db.repositories import plugin_repo

        plugins = [
            {
                "id": row.get("id"),
                "version": row.get("version"),
                "enabled": bool(row.get("enabled")),
                "load_status": "error" if row.get("load_error") else "ok",
            }
            for row in plugin_repo.list_all()
        ]
        return json.dumps(plugins, ensure_ascii=False)

    if section == "schema":
        from sqlalchemy import inspect as sqlalchemy_inspect
        from db.engine import get_engine

        engine = get_engine()
        inspector = sqlalchemy_inspect(engine)
        tables = []
        for table_name in sorted(inspector.get_table_names())[:100]:
            columns = [column["name"] for column in inspector.get_columns(table_name)[:80]]
            tables.append({"table": table_name, "columns": columns})
        return json.dumps({"database": engine.dialect.name, "tables": tables}, ensure_ascii=False)

    return "Error: seção inválida; use settings, plugins ou schema"


def reference_functions(project_root: Path, *, include_state: bool = False) -> list[Function]:
    async def list_files(directory: str = ".", limit: int = 200) -> str:
        base = project_root if directory in ("", ".") else _safe_reference_path(project_root, directory)
        if not base.exists():
            return "Error: pasta não encontrada"
        items: list[str] = []
        for path in base.rglob("*"):
            if len(items) >= max(1, min(limit, 500)):
                break
            rel = path.relative_to(project_root)
            if set(rel.parts) & _BLOCKED_REFERENCE_PARTS:
                continue
            if not _is_allowed_reference(rel):
                continue
            if path.is_file() and path.suffix.lower() in _REFERENCE_EXTENSIONS:
                items.append(rel.as_posix())
        return "\n".join(items) or "Nenhum arquivo encontrado."

    async def read_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
        try:
            target = _safe_reference_path(project_root, path)
        except ValueError as exc:
            return f"Error: {exc}"
        if not target.is_file() or target.suffix.lower() not in _REFERENCE_EXTENSIONS:
            return "Error: arquivo de referência não encontrado ou formato não permitido"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), max(start, min(end_line, start + 799)))
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))

    async def search(query: str, directory: str = ".", limit: int = 20) -> str:
        if not query or len(query) > 200:
            return "Error: busca vazia ou longa demais"
        base = project_root if directory in ("", ".") else _safe_reference_path(project_root, directory)
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        found: list[str] = []
        for path in base.rglob("*"):
            if len(found) >= max(1, min(limit, 100)):
                break
            rel = path.relative_to(project_root)
            if set(rel.parts) & _BLOCKED_REFERENCE_PARTS or not path.is_file():
                continue
            if not _is_allowed_reference(rel):
                continue
            if path.suffix.lower() not in _REFERENCE_EXTENSIONS:
                continue
            try:
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pattern.search(line):
                        found.append(f"{rel.as_posix()}:{number}: {line[:300]}")
                        if len(found) >= limit:
                            break
            except OSError:
                continue
        return "\n".join(found) or "Nenhuma ocorrência encontrada."

    async def inspect_state(section: str = "settings") -> str:
        return await asyncio.to_thread(_inspect_system_state, section)

    functions = [
        Function(
            name="list_whatsbot_files", description="Lista arquivos de documentação e código do WhatsBot disponíveis para consulta.",
            parameters={"type": "object", "properties": {"directory": {"type": "string"}, "limit": {"type": "integer"}}},
            entrypoint=list_files, skip_entrypoint_processing=True,
        ),
        Function(
            name="read_whatsbot_file", description="Lê um trecho numerado de um arquivo do WhatsBot em modo somente leitura.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]},
            entrypoint=read_file, skip_entrypoint_processing=True,
        ),
        Function(
            name="search_whatsbot", description="Pesquisa texto na documentação e no código do WhatsBot em modo somente leitura.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}, "directory": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
            entrypoint=search, skip_entrypoint_processing=True,
        ),
    ]
    if include_state:
        functions.append(Function(
            name="inspect_whatsbot_state",
            description="Consulta o estado seguro do WhatsBot para diagnóstico: configurações operacionais sem segredos, plugins registrados ou estrutura das tabelas sem registros pessoais.",
            parameters={
                "type": "object",
                "properties": {"section": {"type": "string", "enum": ["settings", "plugins", "schema"]}},
            },
            entrypoint=inspect_state, skip_entrypoint_processing=True,
        ))
    return functions


def build_model(api_key: str, model_id: str, reasoning: str = "") -> OpenAILike:
    kwargs = {
        "id": model_id,
        "api_key": api_key,
        "base_url": LLM_API_BASE_URL,
        "max_tokens": 8192,
        # Stable per-conversation prefixes are kept by the caller. OpenRouter
        # and compatible proxies report actual cache reads in usage metrics.
    }
    if reasoning:
        # The configured connection is OpenRouter-compatible. Its normalized
        # Chat Completions contract uses the ``reasoning`` object across model
        # providers (OpenAI, Anthropic, DeepSeek, etc.).
        kwargs["extra_body"] = {"reasoning": {"effort": reasoning}}
    return OpenAILike(**kwargs)


def build_agent(
    *, api_key: str, model_id: str, reasoning: str, project_kind: str,
    workspace: Path | None, project_root: Path, panel_base_url: str = "",
) -> Agent:
    if project_kind == "discovery":
        tools: list = []
        system_message = DISCOVERY_PROMPT
    elif project_kind == "system":
        tools = reference_functions(project_root, include_state=True)
        system_message = system_help_prompt(panel_base_url)
    else:
        tools = reference_functions(project_root)
        system_message = PLUGIN_PROMPT
    if project_kind == "plugin" and workspace is not None:
        workspace.mkdir(parents=True, exist_ok=True)
        tools.insert(0, Workspace(
            workspace,
            allowed=["read", "list", "search", "write", "edit", "move", "delete", "shell"],
            confirm=[],
            require_read_before_write=True,
            exclude_patterns=[".git", "__pycache__", ".pytest_cache", "*.pyc", "versions"],
        ))
        async def validate_plugin() -> str:
            """Run the same independent validation required before installation."""
            try:
                # Lazy import avoids coupling server startup to this optional
                # agent tool while keeping one validation source of truth.
                from server.routes.chat import validate_workspace
                result = await asyncio.to_thread(
                    validate_workspace,
                    {"kind": "plugin", "plugin_id": workspace.name, "workspace_path": str(workspace)},
                    save_version=False,
                )
                return json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                return f"Error: {exc}"

        tools.append(Function(
            name="validate_plugin_project",
            description="Valida manifest, migrations, sintaxe, dependências e testes do plugin atual. Use antes de declarar o trabalho concluído e corrija qualquer erro retornado.",
            parameters={"type": "object", "properties": {}},
            entrypoint=validate_plugin,
            skip_entrypoint_processing=True,
        ))
    return Agent(
        name="WhatsBot Chat",
        model=build_model(api_key, model_id, reasoning),
        system_message=system_message,
        tools=tools,
        markdown=True,
        telemetry=False,
        tool_call_limit=40,
        build_context=False,
        add_history_to_context=False,
        add_datetime_to_context=False,
        resolve_in_context=False,
    )


def history_messages(summary: str, rows: Iterable[dict]) -> list[Message]:
    messages: list[Message] = []
    if summary:
        messages.append(Message(role="system", content="Resumo persistente da conversa anterior:\n" + summary))
    for row in rows:
        if row.get("kind") != "message" or row.get("role") not in ("user", "assistant"):
            continue
        messages.append(Message(role=row["role"], content=row.get("content") or ""))
    return messages


def metrics_dict(metrics) -> dict:
    if not metrics:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    return {
        "input_tokens": getattr(metrics, "input_tokens", 0) or 0,
        "output_tokens": getattr(metrics, "output_tokens", 0) or 0,
        "total_tokens": getattr(metrics, "total_tokens", 0) or 0,
        "cache_read_tokens": getattr(metrics, "cache_read_tokens", 0) or 0,
        "cache_write_tokens": getattr(metrics, "cache_write_tokens", 0) or 0,
        "reasoning_tokens": getattr(metrics, "reasoning_tokens", 0) or 0,
    }
