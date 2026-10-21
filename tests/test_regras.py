from datetime import date

from checagem.regras import avaliar, similaridade_nome
from checagem.schemas import Achado, Consulta

HOJE = date(2026, 10, 21)
URL_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/47960950000121"
URL_DOM = "https://brasilapi.com.br/api/registrobr/v1/loja.com.br"


def cnpj(**dados):
    base = {
        "situacao": "ATIVA",
        "data_abertura": "1990-01-01",
        "razao_social": "MAGAZINE LUIZA S/A",
        "nome_fantasia": "MAGAZINE LUIZA",
        "cnae_principal": {"codigo": "4753900", "descricao": "Comércio varejista de eletrodomésticos"},
    }
    return Achado(fonte="cnpj", status="ok", dados={**base, **dados}, url_fonte=URL_CNPJ)


def dominio(data_registro):
    return Achado(
        fonte="dominio",
        status="ok",
        dados={"dominio": "loja.com.br", "data_registro": data_registro},
        url_fonte=URL_DOM,
    )


def web(*rotulos):
    resultados = [
        {"titulo": f"r{i}", "url": f"https://exemplo.org/{i}", "trecho": "...", "rotulo": r}
        for i, r in enumerate(rotulos)
    ]
    return Achado(fonte="web", status="ok" if resultados else "sem_dados", dados={"resultados": resultados})


def ids(sinais, tipo=None):
    return {s.id for s in sinais if tipo is None or s.tipo == tipo}


CONSULTA = Consulta(nome="Magazine Luiza", cnpj="47960950000121", dominio="loja.com.br")


def test_caso1_empresa_grande_ativa_antiga():
    sinais = avaliar([cnpj(), dominio("1998-05-01"), web("mencao", "mencao")], CONSULTA, HOJE)
    assert "empresa_antiga" in ids(sinais, "positivo")
    assert "dominio_antigo" in ids(sinais, "positivo")
    assert ids(sinais, "alerta") == set()


def test_caso3_cnpj_baixado():
    sinais = avaliar([cnpj(situacao="BAIXADA")], CONSULTA, HOJE)
    assert "cnpj_inativo" in ids(sinais, "alerta")


def test_caso4_empresa_e_dominio_novos():
    sinais = avaliar([cnpj(data_abertura="2026-08-01"), dominio("2026-09-15")], CONSULTA, HOJE)
    assert {"empresa_jovem", "dominio_recente"} <= ids(sinais, "alerta")


def test_caso8_sinais_conflitantes_sao_ambos_listados():
    sinais = avaliar([cnpj(data_abertura="2026-08-01"), dominio("2010-01-01")], CONSULTA, HOJE)
    assert "empresa_jovem" in ids(sinais, "alerta")
    assert "dominio_antigo" in ids(sinais, "positivo")


def test_limiares_de_idade():
    # 180 dias exatos não é "menos de 180"; 5 anos exatos não é "mais de 5".
    s = avaliar([cnpj(data_abertura="2026-04-24")], CONSULTA, HOJE)  # 180 dias
    assert "empresa_jovem" not in ids(s)
    s = avaliar([cnpj(data_abertura="2021-10-21")], CONSULTA, HOJE)
    assert "empresa_antiga" not in ids(s)
    s = avaliar([cnpj(data_abertura="2021-10-20")], CONSULTA, HOJE)
    assert "empresa_antiga" in ids(s)


def test_caso5_fonte_falhou_vira_lacuna():
    falha = Achado(fonte="cnpj", status="falhou", dados={"erro": "HTTP 500"}, url_fonte=URL_CNPJ)
    sinais = avaliar([falha, dominio("2010-01-01")], CONSULTA, HOJE)
    assert "fonte_indisponivel" in ids(sinais, "lacuna")
    assert "dominio_antigo" in ids(sinais)


def test_dado_nao_informado_vira_lacuna():
    a = Achado(fonte="dominio", status="sem_dados", dados={"nao_informado": True})
    assert "nao_informado" in ids(avaliar([a], Consulta(), HOJE), "lacuna")


def test_nome_divergente():
    c = Consulta(nome="Super Ofertas Eletro", cnpj="47960950000121")
    assert "nome_divergente" in ids(avaliar([cnpj()], c, HOJE), "alerta")
    c = Consulta(nome="magazine luíza", cnpj="47960950000121")
    assert "nome_divergente" not in ids(avaliar([cnpj()], c, HOJE))


def test_similaridade_ignora_sufixos_e_acentos():
    assert similaridade_nome("Padaria São João", ["PADARIA SAO JOAO LTDA"]) == 1.0


def test_cnae_por_enum():
    c = Consulta(nome="Magazine Luiza", cnpj="47960950000121", produto="tênis")
    assert "cnae_incompativel" in ids(avaliar([cnpj(compatibilidade_cnae="incompativel")], c, HOJE), "alerta")
    assert "cnae_incompativel" not in ids(avaliar([cnpj(compatibilidade_cnae="compativel")], c, HOJE))


def test_incerto_do_llm_gera_lacuna_e_nao_alerta():
    c = Consulta(nome="Magazine Luiza", cnpj="47960950000121", produto="tênis")
    sinais = avaliar([cnpj(compatibilidade_cnae="incerto"), web("incerto", "incerto", "incerto")], c, HOJE)
    assert {"cnae_incerto", "reclamacoes_incertas"} <= ids(sinais, "lacuna")
    assert ids(sinais, "alerta") == set()


def test_reclamacoes_web_exige_minimo_e_url():
    assert "reclamacoes_web" in ids(avaliar([web("reclamacao", "reclamacao")], CONSULTA, HOJE), "alerta")
    sinais = avaliar([web("reclamacao", "nao_relacionado")], CONSULTA, HOJE)
    assert "reclamacoes_web" not in ids(sinais)
    assert "reclamacao_isolada" in ids(sinais, "lacuna")


def test_ausencia_de_reclamacao_nunca_e_positivo():
    sinais = avaliar([web()], CONSULTA, HOJE)
    assert "sem_mencoes_web" in ids(sinais, "lacuna")
    assert ids(sinais, "positivo") == set()
    sinais = avaliar([web("nao_relacionado")], CONSULTA, HOJE)
    assert "sem_mencoes_web" in ids(sinais, "lacuna")


def test_todo_sinal_tem_evidencia_e_ordem():
    achados = [
        cnpj(situacao="INAPTA", data_abertura="2026-08-01"),
        dominio("2010-01-01"),
        web("reclamacao", "reclamacao", "incerto"),
    ]
    sinais = avaliar(achados, CONSULTA, HOJE)
    assert all(s.evidencia for s in sinais)
    tipos = [s.tipo for s in sinais]
    assert tipos == sorted(tipos, key=["alerta", "positivo", "lacuna"].index)
    alertas = [s for s in sinais if s.tipo == "alerta"]
    assert [s.peso for s in alertas] == sorted((s.peso for s in alertas), reverse=True)


def test_incertos_nao_geram_sem_mencoes():
    sinais = avaliar([web("incerto", "incerto")], CONSULTA, HOJE)
    assert "reclamacoes_incertas" in ids(sinais, "lacuna")
    assert "sem_mencoes_web" not in ids(sinais)
