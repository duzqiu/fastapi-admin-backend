"""下线功能回归：菜品管理、点菜菜单与待办（倒数日）接口不得再暴露。"""

import pytest


RETIRED_PREFIXES = (
    "/api/v1/dishes",
    "/api/v1/dish-categories",
    "/api/v1/dish-tags",
    "/api/v1/dish-orders",
    "/api/v1/menu",
    "/api/v1/countdowns",
    "/api/v1/member/countdowns",
)

KEPT_PATHS = (
    "/api/v1/official-articles",
    "/api/v1/members",
    "/api/v1/posts",
)


def test_retired_features_absent_from_openapi(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for path in paths:
        assert not any(path == prefix or path.startswith(prefix + "/") for prefix in RETIRED_PREFIXES), path
    for path in KEPT_PATHS:
        assert path in paths, path


@pytest.mark.parametrize("path", RETIRED_PREFIXES)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_retired_endpoints_return_not_found(client, path, method):
    response = client.request(method, path)
    assert response.status_code == 404, response.text
