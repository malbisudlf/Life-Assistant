import pytest
from fastapi import Fastapi
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_calendar_events():
    """Test /calendar/events endpoint"""
    response = client.get("/calendar/events")
    assert response.status_code == 200
    assert "events" in response.json()

def test_calendar_classes():
    """Test /calendar/classes endpoint"""
    response = client.get("/calendar/classes")
    assert response.status_code == 200
    assert "events" in response.json()

def test_ha_events():
    """Test /ha/events/soon endpoint"""
    response = client.get("/ha/events/soon")
    assert response.status_code == 200
    assert "events" in response.json()