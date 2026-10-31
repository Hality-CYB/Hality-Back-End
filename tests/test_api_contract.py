from app.main import app

METODOS_HTTP = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

CONTRATO_ADMIN = {
    "/api/v1/admin/usuarios": {"get", "post"},
    "/api/v1/admin/usuarios/{usuario_id}": {"get", "patch"},
    "/api/v1/admin/profissionais/{usuario_id}": {"patch"},
    "/api/v1/admin/vinculos": {"get", "post"},
    "/api/v1/admin/vinculos/{vinculo_id}": {"patch", "delete"},
    "/api/v1/admin/diagnosticos": {"get"},
    "/api/v1/admin/diagnosticos/{diagnostico_id}": {"get"},
}


def test_openapi_preserva_contrato_minimo_das_rotas_admin() -> None:
    paths = app.openapi()["paths"]

    for path, metodos_esperados in CONTRATO_ADMIN.items():
        assert path in paths, f"rota ausente: {path}"
        assert set(paths[path]) & METODOS_HTTP == metodos_esperados


def test_openapi_nao_possui_operation_ids_duplicados() -> None:
    operacoes = [
        operacao["operationId"]
        for item in app.openapi()["paths"].values()
        for metodo, operacao in item.items()
        if metodo in METODOS_HTTP
    ]

    assert len(operacoes) == len(set(operacoes))
