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

_REFERENCE_EXTENSIONS = {".md", ".py", ".js", ".css", ".html", ".yaml", ".yml", ".txt", ".toml"}
_REFERENCE_ROOTS = ("README.md", "CLAUDE.md", "agent", "config", "db", "docs", "plugins", "server", "web", "assets/plugin_examples")
_BLOCKED_REFERENCE_PARTS = {"storages", ".git", "venv", "logs", "__pycache__"}

SYSTEM_HELP_PROMPT = """Você é a ajuda integrada do WhatsBot.
Responda em português brasileiro, com frases curtas e linguagem para uma pessoa sem conhecimento técnico.
Seu único escopo é explicar como usar e configurar o WhatsBot. Consulte as referências somente quando precisar confirmar uma opção ou um comportamento específico. Você pode ler o sistema, mas nunca o modifica.

Você não cria, planeja, pesquisa nem altera plugins neste projeto. Se o usuário quiser criar ou modificar um plugin, explique em uma frase que ele deve clicar no botão + no topo da barra lateral esquerda do Chat, criar um projeto e descrever ali o que deseja. Não faça perguntas sobre o plugin e não use ferramentas para investigar esse pedido.

Nunca mencione endpoints, REST, JSON, IDs, banco de dados, classes ou detalhes de programação, salvo se o próprio usuário pedir uma explicação técnica.
"""

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


def reference_functions(project_root: Path) -> list[Function]:
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

    return [
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
    workspace: Path | None, project_root: Path,
) -> Agent:
    if project_kind == "discovery":
        tools: list = []
        system_message = DISCOVERY_PROMPT
    elif project_kind == "system":
        tools = reference_functions(project_root)
        system_message = SYSTEM_HELP_PROMPT
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
