"""Gera um system prompt grande e FIXO para testar o cache do LLM.

Conteúdo deterministico (seed fixa): a mesma execução sempre gera o mesmo texto,
então o prefixo é idêntico entre mensagens, que é o que o cache exige.

    python tools/gen_test_prompt.py                       # ~25k tokens -> prompt-teste-cache.txt
    python tools/gen_test_prompt.py --tokens 26000
    python tools/gen_test_prompt.py --chars-per-token 2.8 # se o 1º teste mostrar mais tokens que o esperado

Sem tokenizer local, os tokens são ESTIMADOS por caracteres. Calibre com o 1º teste:
veja o "prompt_tokens" real (tela Custos ou log) e ajuste --chars-per-token.
"""

import argparse
import random
from pathlib import Path

CATEGORIAS = {
    "Cafeteiras": ["Cafeteira elétrica", "Cafeteira italiana", "Cafeteira de cápsulas", "Prensa francesa"],
    "Moedores": ["Moedor manual", "Moedor elétrico de lâminas", "Moedor de discos cônicos"],
    "Grãos": ["Café em grãos", "Café moído", "Café descafeinado", "Blend especial"],
    "Acessórios": ["Coador de pano", "Filtro de papel", "Jarra térmica", "Balança de precisão", "Chaleira de bico fino"],
    "Xícaras": ["Xícara de porcelana", "Copo térmico", "Caneca de cerâmica", "Conjunto de xícaras"],
}
ADJ = ["Clássica", "Premium", "Compacta", "Profissional", "Essencial", "Artesanal", "Inox", "Duo", "Plus", "Mini"]
USOS = [
    "ideal para o preparo diário em casa", "pensada para escritórios com várias pessoas",
    "recomendada para quem busca extração mais precisa", "ótima opção de presente",
    "indicada para iniciantes que querem aprender métodos de preparo",
    "feita para quem valoriza durabilidade e fácil limpeza",
]
CUIDADOS = [
    "Lave com água morna e detergente neutro; não use esponja abrasiva.",
    "Não leve ao micro-ondas nem à lava-louças.",
    "Seque bem antes de guardar para evitar manchas e odores.",
    "Descalcifique a cada 30 dias se a água da sua região for dura.",
    "Evite choques térmicos bruscos para preservar o material.",
]
FAQ = [
    ("Qual o prazo de entrega?", "Capitais: 2 a 5 dias úteis. Demais regiões: 5 a 12 dias úteis, conforme o CEP. O prazo conta a partir da confirmação do pagamento."),
    ("Posso trocar um produto?", "Sim, em até 30 dias corridos após o recebimento, com o produto sem uso e na embalagem original. O frete da primeira troca é por nossa conta."),
    ("Quais formas de pagamento?", "Pix com 5% de desconto, cartão em até 10x sem juros acima de R$ 200 e boleto bancário com vencimento em 3 dias."),
    ("Como funciona a garantia?", "Todos os eletrônicos têm 12 meses de garantia contra defeito de fabricação. Acessórios de vidro e porcelana têm 90 dias."),
    ("Vocês emitem nota fiscal?", "Sim, toda compra tem nota fiscal eletrônica enviada ao e-mail cadastrado."),
    ("Posso retirar na loja?", "Sim. A retirada fica disponível 24 horas após a confirmação do pagamento, de segunda a sábado, das 9h às 18h."),
]

def produtos(rng: random.Random, n: int) -> list[str]:
    out = []
    for i in range(n):
        cat = rng.choice(list(CATEGORIAS))
        nome = f"{rng.choice(CATEGORIAS[cat])} {rng.choice(ADJ)} {rng.randint(100, 999)}"
        preco = rng.randint(19, 890) + rng.choice([0.0, 0.9, 0.5])
        est = rng.randint(0, 80)
        out.append(
            f"- SKU CF-{i + 1:04d} | {nome} | Categoria: {cat} | Preço: R$ {preco:.2f}".replace(".", ",", 1)
            + f" | Estoque: {est} un.\n"
            f"  Descrição: {nome} {rng.choice(USOS)}. Material de alta qualidade, "
            f"garantia de {rng.choice([3, 6, 12])} meses. Cuidados: {rng.choice(CUIDADOS)}"
        )
    return out

def montar(target_chars: int) -> str:
    rng = random.Random(42)
    cab = (
        "Você é a Bia, atendente virtual da loja Cafeteria Aurora, especializada em cafés e acessórios.\n"
        "Responda em português do Brasil, de forma curta, simpática e objetiva (no máximo 3 frases).\n"
        "Use SOMENTE as informações abaixo (catálogo, políticas e perguntas frequentes). Se não souber, "
        "diga que vai verificar com a equipe. Nunca invente preços, prazos ou estoque.\n\n"
        "## POLÍTICAS E PERGUNTAS FREQUENTES\n"
        + "\n".join(f"P: {q}\nR: {a}" for q, a in FAQ)
        + "\n\n## CATÁLOGO DE PRODUTOS (consulte aqui preço, estoque e descrição)\n"
    )
    partes, tam, i = [], len(cab), 0
    while tam < target_chars:
        lote = produtos(random.Random(1000 + i), 20)  # lotes fixos
        i += 1
        # SKU precisa ser único e sequencial: renumera
        for p in lote:
            n = sum(1 for _ in partes) + 1
            p = p.replace(p.split(" ")[2], f"CF-{n:04d}", 1)
            partes.append(p)
            tam += len(p) + 1
            if tam >= target_chars:
                break
    return cab + "\n".join(partes) + "\n"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", type=int, default=25000)
    ap.add_argument("--chars-per-token", type=float, default=3.0)
    ap.add_argument("--out", default="prompt-teste-cache.txt")
    a = ap.parse_args()
    txt = montar(int(a.tokens * a.chars_per_token))
    Path(a.out).write_text(txt, encoding="utf-8")
    print(f"{a.out}: {len(txt):,} caracteres, ~{int(len(txt) / a.chars_per_token):,} tokens (ESTIMADO a {a.chars_per_token} car/token)")

if __name__ == "__main__":
    main()
