import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_auth_password():
    """Test authentication with password"""

    response = client.post("/auth/password", json={"password": "test_password"})
    assert response.status_code == 200
    assert "token" in response.json()

def test_maps_departure():
    """Test departure time calculation"""

    response = client.post("/maps/departure", json={"destination": "192.168.1.200"})
    assert response.status_code == 200
    assert "duration" in response.json()

def test_ideas_audio():
    """Test audio transcription"""

    response = client.post("/ideas/audio", files={"audio": "test_audio.wav"})
    assert response.status_code == 200
    assert "transcription" in response.json()