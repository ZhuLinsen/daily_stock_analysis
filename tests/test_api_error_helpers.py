# -*- coding: utf-8 -*-
"""Tests for shared API error helpers."""

from fastapi import HTTPException

from api.v1.errors import api_error, error_body, error_json_response


def test_error_body_omits_empty_detail() -> None:
    assert error_body("validation_error", "bad input") == {
        "error": "validation_error",
        "message": "bad input",
    }


def test_api_error_uses_standard_detail_shape() -> None:
    exc = api_error(404, "not_found", "missing", detail={"id": 1})

    assert isinstance(exc, HTTPException)
    assert exc.status_code == 404
    assert exc.detail == {
        "error": "not_found",
        "message": "missing",
        "detail": {"id": 1},
    }


def test_error_json_response_uses_standard_content() -> None:
    response = error_json_response(409, "conflict", "already exists")

    assert response.status_code == 409
    assert response.body == b'{"error":"conflict","message":"already exists"}'
