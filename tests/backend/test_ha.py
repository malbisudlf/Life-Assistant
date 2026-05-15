import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_ha_toggle():
    """Test Home Assistant toggle"""
    response = client.post("/toggle-ha")
    assert response.status_code == 200
    assert "status" in response.json()

def test_ha_notifications():
    """Test Home Assistant notifications"""
    response = client.get("/ha/events/soon")
    assert response.status_code == 200
    assert "notifications" in response.json()