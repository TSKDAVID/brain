from app.gateway import service as gateway


def test_hq_staff_may_access_any_tenant_case(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "_is_chaster_platform_staff",
        lambda user_id: user_id == "hq-user",
    )
    claims = {"sub": "hq-user", "tenant_id": "other-tenant-uuid"}
    assert gateway._tenant_matches_jwt(claims, "case-tenant-uuid") is True


def test_tenant_member_must_match_when_not_staff(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "_is_chaster_platform_staff",
        lambda user_id: False,
    )

    def fake_get_single_row(table, select, filters):
        if table == "tenant_members":
            return {"tenant_id": filters["tenant_id"]}
        return None

    monkeypatch.setattr(gateway, "get_single_row", fake_get_single_row)
    claims = {"sub": "portal-user"}
    assert gateway._tenant_matches_jwt(claims, "case-tenant-uuid") is True


def test_jwt_home_tenant_must_match_when_not_staff(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "_is_chaster_platform_staff",
        lambda user_id: False,
    )
    monkeypatch.setattr(gateway, "get_single_row", lambda *args, **kwargs: None)
    claims = {"sub": "portal-user", "tenant_id": "tenant-a"}
    assert gateway._tenant_matches_jwt(claims, "tenant-a") is True
    assert gateway._tenant_matches_jwt(claims, "tenant-b") is False
